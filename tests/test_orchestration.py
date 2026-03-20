from __future__ import annotations

from textwrap import dedent

import pytest

from autoweave.exceptions import StateTransitionError
from autoweave.models import TaskState
from autoweave.orchestration import OrchestrationService, WorkflowRunState
from autoweave.workflows import (
    build_workflow_graph,
    example_notifications_workflow_graph,
    parse_workflow_definition,
)


def test_example_workflow_unlocks_parallel_branches_in_order() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))

    initial = service.schedule()
    assert service.state.task("manager_plan").state == TaskState.READY
    assert initial.ready_tasks == [service.state.task("manager_plan").id]
    assert service.state.task("backend_contract").state == TaskState.WAITING_FOR_DEPENDENCY
    assert service.state.task("frontend_ui").state == TaskState.WAITING_FOR_DEPENDENCY

    service.complete_task(service.state.task("manager_plan").id)
    after_root = service.schedule()
    assert service.state.task("backend_contract").state == TaskState.READY
    assert service.state.task("frontend_ui").state == TaskState.READY
    assert set(after_root.ready_tasks) == {
        service.state.task("backend_contract").id,
        service.state.task("frontend_ui").id,
    }

    service.complete_task(service.state.task("backend_contract").id)
    after_contract = service.schedule()
    assert service.state.task("backend_impl").state == TaskState.READY
    assert service.state.task("frontend_ui").state == TaskState.READY
    assert service.state.task("backend_impl").id in after_contract.ready_tasks

    service.complete_task(service.state.task("backend_impl").id)
    after_backend_impl = service.schedule()
    assert service.state.task("integration").state == TaskState.WAITING_FOR_DEPENDENCY
    assert service.state.task("review").state == TaskState.WAITING_FOR_DEPENDENCY
    assert service.state.task("integration").id not in after_backend_impl.ready_tasks

    service.complete_task(service.state.task("frontend_ui").id)
    after_frontend = service.schedule()
    assert service.state.task("integration").state == TaskState.READY
    assert set(after_frontend.ready_tasks) == {
        service.state.task("integration").id,
    }

    service.complete_task(service.state.task("integration").id)
    after_integration = service.schedule()
    assert service.state.task("review").state == TaskState.READY
    assert after_integration.ready_tasks == [service.state.task("review").id]


def test_cycle_detection_rejects_invalid_workflow_graph() -> None:
    definition = parse_workflow_definition(
        dedent(
            """
            name: cyclic
            version: "1.0"
            roles: [manager]
            stages: [planning]
            entrypoint: a
            task_templates:
              - key: a
                title: A
                assigned_role: manager
                description_template: A
                hard_dependencies: [c]
              - key: b
                title: B
                assigned_role: manager
                description_template: B
                hard_dependencies: [a]
              - key: c
                title: C
                assigned_role: manager
                description_template: C
                hard_dependencies: [b]
            completion_rules: {}
            """
        )
    )

    with pytest.raises(ValueError, match="cycle"):
        build_workflow_graph(definition, project_id="proj", team_id="team")


def test_blocked_branch_does_not_stop_unrelated_branches() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()
    service.complete_task(service.state.task("manager_plan").id)
    service.schedule()

    blocked = service.block_task(service.state.task("backend_contract").id, reason="graph_change")
    assert blocked.state == TaskState.BLOCKED
    assert service.state.task("frontend_ui").state == TaskState.READY

    service.complete_task(service.state.task("frontend_ui").id)
    service.schedule()
    assert service.state.task("backend_impl").state == TaskState.WAITING_FOR_DEPENDENCY
    assert service.state.task("frontend_ui").state == TaskState.COMPLETED


def test_clarification_opens_waiting_for_human_and_resumes_safely() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()
    service.complete_task(service.state.task("manager_plan").id)
    service.schedule()
    service.complete_task(service.state.task("backend_contract").id)
    service.complete_task(service.state.task("frontend_ui").id)
    service.schedule()
    service.complete_task(service.state.task("backend_impl").id)
    service.schedule()

    integration_task = service.state.task("integration")
    integration_attempt = service.open_attempt(task_id=integration_task.id, agent_definition_id="agent-integration")
    service.start_task(integration_task.id)
    service.start_attempt(integration_attempt.id)
    request = service.request_clarification(
        task_id=integration_task.id,
        task_attempt_id=integration_attempt.id,
        question="Confirm wording for the settings page.",
        context_summary="Integration needs human guidance on copy.",
    )
    assert service.state.task("integration").state == TaskState.WAITING_FOR_HUMAN

    service.answer_human_request(request.id, answer_text="Use the short form copy.", answered_by="human")
    assert service.state.task("integration").state == TaskState.READY

    service.complete_task(service.state.task("integration").id)
    assert service.state.task("integration").state == TaskState.COMPLETED

    late = service.answer_human_request(request.id, answer_text="late update", answered_by="human")
    assert late.answer_text == "late update"
    assert service.state.task("integration").state == TaskState.COMPLETED


def test_duplicate_attempt_dispatch_is_blocked() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()

    task = service.state.task("manager_plan")
    service.open_attempt(task_id=task.id, agent_definition_id="agent-manager")

    with pytest.raises(StateTransitionError, match="active attempt"):
        service.open_attempt(task_id=task.id, agent_definition_id="agent-manager")


def test_timeout_recovery_blocks_then_reopens_with_late_human_answer_ignored() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()

    task = service.state.task("manager_plan")
    attempt_one = service.open_attempt(task_id=task.id, agent_definition_id="agent-manager")
    service.start_task(task.id)
    service.start_attempt(attempt_one.id)
    request = service.request_clarification(
        task_id=task.id,
        task_attempt_id=attempt_one.id,
        question="Need confirmation before proceeding.",
        context_summary="Attempt one hit a blocker.",
    )

    service.finalize_attempt_failure(task.id, attempt_one.id, reason="worker_timeout", recoverable=True)
    assert service.state.task(task.id).state == TaskState.BLOCKED
    assert service.state.attempt(attempt_one.id).state.value == "orphaned"

    service.unblock_task(task.id)
    attempt_two = service.open_attempt(task_id=task.id, agent_definition_id="agent-manager")
    service.start_task(task.id)
    service.start_attempt(attempt_two.id)

    service.answer_human_request(request.id, answer_text="late response", answered_by="human")
    assert service.state.task(task.id).state == TaskState.IN_PROGRESS
    assert service.state.attempt(attempt_two.id).state.value == "running"


def test_approval_rejection_prevents_completion() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()
    task = service.state.task("manager_plan")
    attempt = service.open_attempt(task_id=task.id, agent_definition_id="agent-manager")
    service.start_task(task.id)

    request = service.request_approval(
        task_id=task.id,
        task_attempt_id=attempt.id,
        approval_type="signoff",
        reason="Need manager signoff before continuing.",
    )
    rejected = service.resolve_approval(request.id, approved=False, resolved_by="lead")
    assert rejected.status.value == "rejected"
    assert service.state.task("manager_plan").state == TaskState.BLOCKED

    with pytest.raises(StateTransitionError):
        service.complete_task(service.state.task("manager_plan").id)


def test_unresolved_hard_dependencies_prevent_completion() -> None:
    service = OrchestrationService(WorkflowRunState.from_graph(example_notifications_workflow_graph()))
    service.schedule()

    with pytest.raises(StateTransitionError, match="unresolved hard dependencies"):
        service.complete_task(service.state.task("backend_impl").id)
