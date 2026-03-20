"""Mutable orchestration state and task-transition helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from autoweave.exceptions import StateTransitionError
from autoweave.models import (
    ApprovalRequestRecord,
    ApprovalStatus,
    AttemptState,
    HumanRequestRecord,
    HumanRequestStatus,
    HumanRequestType,
    TaskRecord,
    TaskState,
    TaskAttemptRecord,
    WorkflowRunStatus,
    utc_now,
    WorkflowGraph,
)
from autoweave.orchestration.graph import DependencyView, build_dependency_view


@dataclass(slots=True)
class WorkflowRunState:
    """In-memory state for a workflow run."""

    graph: WorkflowGraph
    tasks_by_id: dict[str, TaskRecord]
    tasks_by_key: dict[str, str]
    attempts_by_id: dict[str, TaskAttemptRecord] = field(default_factory=dict)
    attempts_by_task_id: dict[str, list[str]] = field(default_factory=dict)
    human_requests: dict[str, HumanRequestRecord] = field(default_factory=dict)
    approval_requests: dict[str, ApprovalRequestRecord] = field(default_factory=dict)
    graph_revision: int = 1

    @classmethod
    def from_graph(cls, graph: WorkflowGraph) -> "WorkflowRunState":
        return cls(
            graph=graph,
            tasks_by_id={task.id: task for task in graph.tasks},
            tasks_by_key={task.task_key: task.id for task in graph.tasks},
            graph_revision=graph.workflow_run.graph_revision,
        )

    def dependency_view(self) -> DependencyView:
        return build_dependency_view(self.graph)

    def task(self, task_id_or_key: str) -> TaskRecord:
        task_id = self.tasks_by_key.get(task_id_or_key, task_id_or_key)
        try:
            return self.tasks_by_id[task_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown task {task_id_or_key!r}") from exc

    def update_task(self, task: TaskRecord) -> TaskRecord:
        self.tasks_by_id[task.id] = task
        self.tasks_by_key[task.task_key] = task.id
        self.graph = self.graph.model_copy(update={"tasks": [self.tasks_by_id[t.id] for t in self.graph.tasks]})
        return task

    def _active_attempt_states(self) -> set[AttemptState]:
        return {
            AttemptState.QUEUED,
            AttemptState.DISPATCHING,
            AttemptState.RUNNING,
            AttemptState.PAUSED,
            AttemptState.NEEDS_INPUT,
        }

    def _latest_active_attempt_id(self, task_id: str) -> str | None:
        for attempt_id in reversed(self.attempts_by_task_id.get(task_id, [])):
            attempt = self.attempts_by_id.get(attempt_id)
            if attempt is not None and attempt.state in self._active_attempt_states():
                return attempt_id
        return None

    def _all_tasks_completed(self) -> bool:
        return all(task.state == TaskState.COMPLETED for task in self.tasks_by_id.values())

    def _any_task_in_progress(self) -> bool:
        return any(task.state == TaskState.IN_PROGRESS for task in self.tasks_by_id.values())

    def mark_workflow_running(self) -> None:
        workflow_run = self.graph.workflow_run
        if workflow_run.status != WorkflowRunStatus.RUNNING:
            self.graph = self.graph.model_copy(
                update={
                    "workflow_run": workflow_run.model_copy(
                        update={
                            "status": WorkflowRunStatus.RUNNING,
                            "started_at": workflow_run.started_at or utc_now(),
                        }
                    )
                }
            )

    def mark_workflow_completed(self) -> None:
        workflow_run = self.graph.workflow_run
        self.graph = self.graph.model_copy(
            update={
                "workflow_run": workflow_run.model_copy(
                    update={
                        "status": WorkflowRunStatus.COMPLETED,
                        "ended_at": workflow_run.ended_at or workflow_run.started_at or utc_now(),
                    }
                )
            }
        )

    def mark_workflow_failed(self) -> None:
        workflow_run = self.graph.workflow_run
        self.graph = self.graph.model_copy(
            update={
                "workflow_run": workflow_run.model_copy(
                    update={
                        "status": WorkflowRunStatus.FAILED,
                        "ended_at": workflow_run.ended_at or workflow_run.started_at or utc_now(),
                    }
                )
            }
        )

    def open_attempt(
        self,
        task_id: str,
        *,
        agent_definition_id: str,
        workspace_id: str | None = None,
        compiled_worker_config_json: dict[str, object] | None = None,
        model_route_id: str | None = None,
        lease_key: str | None = None,
    ) -> TaskAttemptRecord:
        task = self.task(task_id)
        if self._latest_active_attempt_id(task.id) is not None:
            raise StateTransitionError(f"task {task.task_key!r} already has an active attempt")
        attempt_number = len(self.attempts_by_task_id.get(task.id, [])) + 1
        attempt = TaskAttemptRecord(
            task_id=task.id,
            attempt_number=attempt_number,
            agent_definition_id=agent_definition_id,
            workspace_id=workspace_id,
            compiled_worker_config_json=compiled_worker_config_json or {},
            model_route_id=model_route_id,
            lease_key=lease_key,
        )
        return self.record_attempt(attempt)

    def record_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord:
        record = attempt.model_copy(deep=True)
        self.attempts_by_id[record.id] = record
        task_attempt_ids = self.attempts_by_task_id.setdefault(record.task_id, [])
        if record.id not in task_attempt_ids:
            task_attempt_ids.append(record.id)
        return record

    def attempt(self, attempt_id: str) -> TaskAttemptRecord:
        try:
            return self.attempts_by_id[attempt_id].model_copy(deep=True)
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"attempt {attempt_id!r} is not registered") from exc

    def active_attempts(self, task_id: str | None = None) -> list[TaskAttemptRecord]:
        attempt_ids = (
            self.attempts_by_task_id.get(task_id, [])
            if task_id is not None
            else list(self.attempts_by_id)
        )
        active: list[TaskAttemptRecord] = []
        for attempt_id in attempt_ids:
            attempt = self.attempts_by_id.get(attempt_id)
            if attempt is not None and attempt.state in self._active_attempt_states():
                active.append(attempt.model_copy(deep=True))
        return active

    def dispatch_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.DISPATCHING)
        self.attempts_by_id[attempt_id] = updated
        self.mark_workflow_running()
        return updated

    def start_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        if attempt.state == AttemptState.QUEUED:
            attempt = attempt.transition(AttemptState.DISPATCHING)
        updated = attempt.transition(AttemptState.RUNNING)
        self.attempts_by_id[attempt_id] = updated
        self.mark_workflow_running()
        return updated

    def resume_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        if attempt.state == AttemptState.QUEUED:
            attempt = attempt.transition(AttemptState.DISPATCHING)
        updated = attempt.transition(AttemptState.RUNNING)
        self.attempts_by_id[attempt_id] = updated
        self.mark_workflow_running()
        return updated

    def pause_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.PAUSED)
        self.attempts_by_id[attempt_id] = updated
        return updated

    def needs_input_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.NEEDS_INPUT)
        self.attempts_by_id[attempt_id] = updated
        return updated

    def complete_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.SUCCEEDED)
        self.attempts_by_id[attempt_id] = updated
        return updated

    def fail_attempt(self, attempt_id: str, *, recoverable: bool = False) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.ORPHANED if recoverable else AttemptState.ERRORED)
        self.attempts_by_id[attempt_id] = updated
        return updated

    def abort_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        attempt = self.attempt(attempt_id)
        updated = attempt.transition(AttemptState.ABORTED)
        self.attempts_by_id[attempt_id] = updated
        return updated

    def hard_predecessors(self, task_id: str) -> list[TaskRecord]:
        view = self.dependency_view()
        return [self.tasks_by_id[parent_id] for parent_id in view.hard_predecessors.get(task_id, ())]

    def hard_dependencies_satisfied(self, task_id: str) -> bool:
        return all(parent.state == TaskState.COMPLETED for parent in self.hard_predecessors(task_id))

    def task_readiness_reasons(self, task_id: str) -> list[str]:
        task = self.task(task_id)
        reasons: list[str] = []
        if task.state == TaskState.BLOCKED:
            reasons.append(f"blocked:{task.block_reason or 'unspecified'}")
        elif task.state == TaskState.WAITING_FOR_HUMAN:
            reasons.append("waiting_for_human")
        elif task.state == TaskState.WAITING_FOR_APPROVAL:
            reasons.append("waiting_for_approval")
        elif task.state == TaskState.IN_PROGRESS:
            reasons.append("already_running")
        if not self.hard_dependencies_satisfied(task.id):
            pending = [
                parent.task_key
                for parent in self.hard_predecessors(task.id)
                if parent.state != TaskState.COMPLETED
            ]
            reasons.append(f"waiting_on_dependencies:{','.join(sorted(pending))}")
        return reasons

    def can_run(self, task_id: str) -> bool:
        task = self.task(task_id)
        if task.state not in {TaskState.CREATED, TaskState.WAITING_FOR_DEPENDENCY, TaskState.READY}:
            return False
        return self.hard_dependencies_satisfied(task.id)

    def promote_ready_tasks(self) -> list[TaskRecord]:
        ready: list[TaskRecord] = []
        for task_id in self.dependency_view().topological_order:
            task = self.tasks_by_id[task_id]
            if task.state in {TaskState.CREATED, TaskState.WAITING_FOR_DEPENDENCY}:
                if self.hard_dependencies_satisfied(task.id):
                    if task.state != TaskState.READY:
                        task = task.transition(TaskState.READY)
                        self.update_task(task)
                    ready.append(task)
                else:
                    if task.state != TaskState.WAITING_FOR_DEPENDENCY:
                        task = task.transition(TaskState.WAITING_FOR_DEPENDENCY)
                        self.update_task(task)
            elif task.state == TaskState.READY and self.hard_dependencies_satisfied(task.id):
                ready.append(task)
            elif task.state == TaskState.READY and not self.hard_dependencies_satisfied(task.id):
                task = task.transition(TaskState.WAITING_FOR_DEPENDENCY)
                self.update_task(task)
        return ready

    def start_task(self, task_id: str) -> TaskRecord:
        task = self.task(task_id)
        if task.state != TaskState.READY:
            raise StateTransitionError(f"task {task.task_key!r} must be ready before it can start")
        if not self.hard_dependencies_satisfied(task.id):
            raise StateTransitionError(
                f"task {task.task_key!r} cannot start with unresolved hard dependencies"
            )
        task = task.transition(TaskState.IN_PROGRESS)
        self.mark_workflow_running()
        return self.update_task(task)

    def fail_task(self, task_id: str, *, reason: str) -> TaskRecord:
        task = self.task(task_id)
        if task.state not in {
            TaskState.READY,
            TaskState.IN_PROGRESS,
            TaskState.WAITING_FOR_DEPENDENCY,
            TaskState.WAITING_FOR_HUMAN,
            TaskState.WAITING_FOR_APPROVAL,
            TaskState.BLOCKED,
        }:
            raise StateTransitionError(f"task {task.task_key!r} cannot fail from state {task.state.value}")
        task = task.transition(TaskState.FAILED, reason=reason)
        updated = self.update_task(task)
        self.mark_workflow_failed()
        return updated

    def unblock_task(self, task_id: str) -> TaskRecord:
        task = self.task(task_id)
        if task.state != TaskState.BLOCKED:
            raise StateTransitionError(f"task {task.task_key!r} must be blocked before it can resume")
        task = task.transition(TaskState.READY)
        return self.update_task(task)

    def block_task(self, task_id: str, *, reason: str) -> TaskRecord:
        task = self.task(task_id)
        if task.state not in {
            TaskState.READY,
            TaskState.IN_PROGRESS,
            TaskState.WAITING_FOR_DEPENDENCY,
            TaskState.WAITING_FOR_HUMAN,
            TaskState.WAITING_FOR_APPROVAL,
        }:
            raise StateTransitionError(f"task {task.task_key!r} cannot be blocked from state {task.state.value}")
        task = task.transition(TaskState.BLOCKED, reason=reason)
        return self.update_task(task)

    def complete_task(self, task_id: str) -> TaskRecord:
        task = self.task(task_id)
        if not self.hard_dependencies_satisfied(task.id):
            pending = [
                parent.task_key
                for parent in self.hard_predecessors(task.id)
                if parent.state != TaskState.COMPLETED
            ]
            raise StateTransitionError(
                f"task {task.task_key!r} cannot complete with unresolved hard dependencies: {pending}"
            )
        if task.state == TaskState.READY:
            task = task.transition(TaskState.IN_PROGRESS)
            self.update_task(task)
        if task.state != TaskState.IN_PROGRESS:
            raise StateTransitionError(f"task {task.task_key!r} must be running before completion")
        task = task.transition(TaskState.COMPLETED)
        updated = self.update_task(task)
        if self._all_tasks_completed():
            self.mark_workflow_completed()
        return updated

    def request_clarification(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        question: str,
        context_summary: str,
    ) -> HumanRequestRecord:
        task = self.task(task_id)
        open_request = self._open_human_request_for_task(task.id, HumanRequestType.CLARIFICATION)
        if open_request is not None:
            open_request = open_request.model_copy(
                update={"question": question, "context_summary": context_summary}
            )
            self.human_requests[open_request.id] = open_request
            if task.state != TaskState.WAITING_FOR_HUMAN:
                task = task.transition(TaskState.WAITING_FOR_HUMAN)
                self.update_task(task)
            return open_request

        request = HumanRequestRecord(
            workflow_run_id=self.graph.workflow_run.id,
            task_id=task.id,
            task_attempt_id=task_attempt_id,
            request_type=HumanRequestType.CLARIFICATION,
            question=question,
            context_summary=context_summary,
        )
        self.human_requests[request.id] = request
        if task.state != TaskState.WAITING_FOR_HUMAN:
            task = task.transition(TaskState.WAITING_FOR_HUMAN)
            self.update_task(task)
        return request

    def answer_human_request(self, request_id: str, *, answer_text: str, answered_by: str) -> HumanRequestRecord:
        request = self.human_requests[request_id]
        task = self.task(request.task_id)
        request = request.model_copy(
            update={
                "status": HumanRequestStatus.ANSWERED,
                "answer_text": answer_text,
                "answered_by": answered_by,
            }
        )
        self.human_requests[request.id] = request
        if task.state == TaskState.WAITING_FOR_HUMAN and self._latest_active_attempt_id(task.id) == request.task_attempt_id:
            task = task.transition(TaskState.READY)
            self.update_task(task)
        return request

    def request_approval(
        self,
        *,
        task_id: str,
        task_attempt_id: str,
        approval_type: str,
        reason: str,
    ) -> ApprovalRequestRecord:
        task = self.task(task_id)
        open_request = self._open_approval_request_for_task(task.id, approval_type)
        if open_request is not None:
            open_request = open_request.model_copy(update={"reason": reason})
            self.approval_requests[open_request.id] = open_request
            if task.state != TaskState.WAITING_FOR_APPROVAL:
                task = task.transition(TaskState.WAITING_FOR_APPROVAL)
                self.update_task(task)
            return open_request

        request = ApprovalRequestRecord(
            workflow_run_id=self.graph.workflow_run.id,
            task_id=task.id,
            task_attempt_id=task_attempt_id,
            approval_type=approval_type,
            reason=reason,
        )
        self.approval_requests[request.id] = request
        if task.state != TaskState.WAITING_FOR_APPROVAL:
            task = task.transition(TaskState.WAITING_FOR_APPROVAL)
            self.update_task(task)
        return request

    def resolve_approval(self, request_id: str, *, approved: bool, resolved_by: str) -> ApprovalRequestRecord:
        request = self.approval_requests[request_id]
        task = self.task(request.task_id)
        request = request.model_copy(
            update={
                "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                "resolved_by": resolved_by,
            }
        )
        self.approval_requests[request.id] = request
        if task.state == TaskState.WAITING_FOR_APPROVAL and self._latest_active_attempt_id(task.id) == request.task_attempt_id:
            if approved:
                task = task.transition(TaskState.READY)
            else:
                task = task.transition(TaskState.BLOCKED, reason="approval_rejected")
            self.update_task(task)
        return request

    def resume_ready_tasks(self) -> list[TaskRecord]:
        ready = self.promote_ready_tasks()
        return [task for task in ready if task.state == TaskState.READY]

    def _open_human_request_for_task(
        self, task_id: str, request_type: HumanRequestType
    ) -> HumanRequestRecord | None:
        for request in self.human_requests.values():
            if request.task_id == task_id and request.request_type == request_type and request.status == HumanRequestStatus.OPEN:
                return request
        return None

    def _open_approval_request_for_task(self, task_id: str, approval_type: str) -> ApprovalRequestRecord | None:
        for request in self.approval_requests.values():
            if request.task_id == task_id and request.approval_type == approval_type and request.status == ApprovalStatus.REQUESTED:
                return request
        return None
