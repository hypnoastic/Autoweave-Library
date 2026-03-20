"""Dependency-aware scheduler for workflow runs."""

from __future__ import annotations

from dataclasses import dataclass

from autoweave.models import TaskReadiness, TaskState
from autoweave.orchestration.state import WorkflowRunState


@dataclass(slots=True)
class ScheduleResult:
    promoted_tasks: list[str]
    ready_tasks: list[str]
    blocked_tasks: list[str]


class WorkflowScheduler:
    """Recompute task readiness and promote runnable tasks."""

    def evaluate(self, state: WorkflowRunState) -> list[TaskReadiness]:
        readiness: list[TaskReadiness] = []
        for task_id in state.dependency_view().topological_order:
            task = state.tasks_by_id[task_id]
            reasons = state.task_readiness_reasons(task.id)
            is_runnable = task.state in {
                TaskState.CREATED,
                TaskState.WAITING_FOR_DEPENDENCY,
                TaskState.READY,
            } and not reasons
            readiness.append(
                TaskReadiness(
                    task_id=task.id,
                    ready=is_runnable,
                    reasons=reasons,
                    missing_artifacts=[],
                )
            )
        return readiness

    def promote(self, state: WorkflowRunState) -> ScheduleResult:
        promoted = state.promote_ready_tasks()
        readiness = self.evaluate(state)
        return ScheduleResult(
            promoted_tasks=[task.id for task in promoted],
            ready_tasks=[item.task_id for item in readiness if item.ready],
            blocked_tasks=[item.task_id for item in readiness if not item.ready],
        )

    def runnable_tasks(self, state: WorkflowRunState) -> list[str]:
        return [item.task_id for item in self.evaluate(state) if item.ready]
