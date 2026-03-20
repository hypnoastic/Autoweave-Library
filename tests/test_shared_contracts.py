from __future__ import annotations

import pytest

from autoweave.config_models import TaskTemplateConfig, WorkflowDefinitionConfig
from autoweave.exceptions import StateTransitionError
from autoweave.models import AttemptState, TaskAttemptRecord, TaskRecord, TaskState, WorkflowGraph, WorkflowRunRecord


def test_workflow_definition_requires_valid_entrypoint() -> None:
    template = TaskTemplateConfig(
        key="manager_plan",
        title="Manager plan",
        assigned_role="manager",
        description_template="Plan work",
    )
    config = WorkflowDefinitionConfig(
        name="team",
        version="1.0",
        roles=["manager"],
        stages=["planning"],
        entrypoint="manager_plan",
        task_templates=[template],
    )
    assert config.entrypoint == "manager_plan"


def test_task_transition_rejects_illegal_completion() -> None:
    task = TaskRecord(
        workflow_run_id="run_1",
        task_key="backend_impl",
        title="Backend impl",
        description="Implement backend",
        assigned_role="backend",
    )
    with pytest.raises(StateTransitionError):
        task.transition(TaskState.COMPLETED)


def test_attempt_transition_rejects_backward_move() -> None:
    attempt = TaskAttemptRecord(task_id="task_1", attempt_number=1, agent_definition_id="agent_1")
    attempt = attempt.transition(AttemptState.DISPATCHING)
    with pytest.raises(StateTransitionError):
        attempt.transition(AttemptState.QUEUED)


def test_workflow_graph_rejects_unknown_edge_targets() -> None:
    task = TaskRecord(
        workflow_run_id="run_1",
        task_key="frontend_ui",
        title="Frontend UI",
        description="Build UI",
        assigned_role="frontend",
    )
    run = WorkflowRunRecord(project_id="proj_1", team_id="team_1", workflow_definition_id="def_1")
    with pytest.raises(ValueError):
        WorkflowGraph.model_validate(
            {
                "workflow_run": run.model_dump(),
                "tasks": [task.model_dump()],
                "edges": [
                    {
                        "workflow_run_id": run.id,
                        "from_task_id": task.id,
                        "to_task_id": "missing_task",
                    }
                ],
            }
        )
