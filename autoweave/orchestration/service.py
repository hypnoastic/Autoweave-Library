"""High-level orchestration service."""

from __future__ import annotations

from dataclasses import dataclass, field

from autoweave.models import ApprovalRequestRecord, HumanRequestRecord, TaskAttemptRecord, TaskRecord
from autoweave.orchestration.scheduler import ScheduleResult, WorkflowScheduler
from autoweave.orchestration.state import WorkflowRunState


@dataclass(slots=True)
class OrchestrationService:
    """Authoritative task-state manager for a workflow run."""

    state: WorkflowRunState
    scheduler: WorkflowScheduler = field(default_factory=WorkflowScheduler)

    def schedule(self) -> ScheduleResult:
        return self.scheduler.promote(self.state)

    def start_task(self, task_id: str) -> TaskRecord:
        return self.state.start_task(task_id)

    def fail_task(self, task_id: str, *, reason: str) -> TaskRecord:
        return self.state.fail_task(task_id, reason=reason)

    def unblock_task(self, task_id: str) -> TaskRecord:
        return self.state.unblock_task(task_id)

    def complete_task(self, task_id: str) -> TaskRecord:
        return self.state.complete_task(task_id)

    def block_task(self, task_id: str, *, reason: str) -> TaskRecord:
        return self.state.block_task(task_id, reason=reason)

    def open_attempt(
        self,
        *,
        task_id: str,
        agent_definition_id: str,
        workspace_id: str | None = None,
        compiled_worker_config_json: dict[str, object] | None = None,
        model_route_id: str | None = None,
        lease_key: str | None = None,
    ) -> TaskAttemptRecord:
        return self.state.open_attempt(
            task_id,
            agent_definition_id=agent_definition_id,
            workspace_id=workspace_id,
            compiled_worker_config_json=compiled_worker_config_json,
            model_route_id=model_route_id,
            lease_key=lease_key,
        )

    def record_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord:
        return self.state.record_attempt(attempt)

    def attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.attempt(attempt_id)

    def active_attempts(self, task_id: str | None = None) -> list[TaskAttemptRecord]:
        return self.state.active_attempts(task_id)

    def dispatch_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.dispatch_attempt(attempt_id)

    def start_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.start_attempt(attempt_id)

    def resume_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.resume_attempt(attempt_id)

    def pause_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.pause_attempt(attempt_id)

    def needs_input_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.needs_input_attempt(attempt_id)

    def complete_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.complete_attempt(attempt_id)

    def fail_attempt(self, attempt_id: str, *, recoverable: bool = False) -> TaskAttemptRecord:
        return self.state.fail_attempt(attempt_id, recoverable=recoverable)

    def abort_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        return self.state.abort_attempt(attempt_id)

    def finalize_attempt_success(self, task_id: str, attempt_id: str) -> tuple[TaskRecord, TaskAttemptRecord]:
        attempt = self.complete_attempt(attempt_id)
        task = self.complete_task(task_id)
        return task, attempt

    def finalize_attempt_failure(
        self,
        task_id: str,
        attempt_id: str,
        *,
        reason: str,
        recoverable: bool = False,
    ) -> tuple[TaskRecord, TaskAttemptRecord]:
        if recoverable:
            attempt = self.fail_attempt(attempt_id, recoverable=True)
            task = self.block_task(task_id, reason=reason)
        else:
            attempt = self.fail_attempt(attempt_id, recoverable=False)
            task = self.fail_task(task_id, reason=reason)
        return task, attempt

    def recover_attempt(self, task_id: str, attempt_id: str, *, reason: str) -> tuple[TaskRecord, TaskAttemptRecord]:
        attempt = self.fail_attempt(attempt_id, recoverable=True)
        task = self.block_task(task_id, reason=reason)
        return task, attempt

    def request_clarification(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        question: str,
        context_summary: str,
    ) -> HumanRequestRecord:
        return self.state.request_clarification(
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            question=question,
            context_summary=context_summary,
        )

    def answer_human_request(self, request_id: str, *, answer_text: str, answered_by: str) -> HumanRequestRecord:
        return self.state.answer_human_request(
            request_id,
            answer_text=answer_text,
            answered_by=answered_by,
        )

    def request_approval(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        approval_type: str,
        reason: str,
    ) -> ApprovalRequestRecord:
        return self.state.request_approval(
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            approval_type=approval_type,
            reason=reason,
        )

    def resolve_approval(self, request_id: str, *, approved: bool, resolved_by: str) -> ApprovalRequestRecord:
        return self.state.resolve_approval(
            request_id,
            approved=approved,
            resolved_by=resolved_by,
        )
