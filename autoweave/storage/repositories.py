"""In-memory canonical repositories for AutoWeave entities."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from autoweave.models import (
    AttemptState,
    ArtifactRecord,
    TaskAttemptRecord,
    TaskEdgeRecord,
    TaskRecord,
    WorkflowGraph,
    WorkflowRunRecord,
)


@dataclass(frozen=True)
class WorkflowSnapshot:
    workflow_run: WorkflowRunRecord
    tasks: list[TaskRecord]
    edges: list[TaskEdgeRecord]


class InMemoryWorkflowRepository:
    """Source-of-truth repository for workflow runs, tasks, and attempts."""

    def __init__(self) -> None:
        self._graphs: dict[str, WorkflowGraph] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._task_to_run: dict[str, str] = {}
        self._task_key_index: dict[tuple[str, str], str] = {}
        self._attempts: dict[str, TaskAttemptRecord] = {}
        self._attempts_by_run: dict[str, list[str]] = defaultdict(list)

    def save_graph(self, graph: WorkflowGraph) -> WorkflowGraph:
        snapshot = graph.model_copy(deep=True)
        self._graphs[snapshot.workflow_run.id] = snapshot
        for task in snapshot.tasks:
            self._tasks[task.id] = task.model_copy(deep=True)
            self._task_to_run[task.id] = snapshot.workflow_run.id
            self._task_key_index[(snapshot.workflow_run.id, task.task_key)] = task.id
        return snapshot

    def get_graph(self, workflow_run_id: str) -> WorkflowGraph:
        try:
            return self._graphs[workflow_run_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"workflow run {workflow_run_id!r} is not registered") from exc

    def save_task(self, task: TaskRecord) -> TaskRecord:
        record = task.model_copy(deep=True)
        self._tasks[record.id] = record
        self._task_to_run[record.id] = record.workflow_run_id
        self._task_key_index[(record.workflow_run_id, record.task_key)] = record.id
        graph = self._graphs.get(record.workflow_run_id)
        if graph is not None:
            graph_tasks = [existing if existing.id != record.id else record.model_copy(deep=True) for existing in graph.tasks]
            if record.id not in {existing.id for existing in graph.tasks}:
                graph_tasks.append(record.model_copy(deep=True))
            self._graphs[record.workflow_run_id] = graph.model_copy(update={"tasks": graph_tasks}, deep=True)
        return record

    def save_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord:
        record = attempt.model_copy(deep=True)
        self._attempts[record.id] = record
        task = self._tasks.get(record.task_id)
        if task is not None:
            attempt_ids = self._attempts_by_run[task.workflow_run_id]
            if record.id not in attempt_ids:
                attempt_ids.append(record.id)
        return record

    def update_attempt_state(self, attempt_id: str, state: AttemptState) -> TaskAttemptRecord:
        attempt = self.get_attempt(attempt_id)
        updated = attempt.transition(state)
        self._attempts[attempt_id] = updated
        return updated

    def list_active_attempts(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        active_states = {AttemptState.QUEUED, AttemptState.DISPATCHING, AttemptState.RUNNING, AttemptState.PAUSED, AttemptState.NEEDS_INPUT}
        active_attempts: list[TaskAttemptRecord] = []
        for attempt_id in self._attempts_by_run.get(workflow_run_id, []):
            attempt = self._attempts.get(attempt_id)
            if attempt is not None and attempt.state in active_states:
                active_attempts.append(attempt.model_copy(deep=True))
        return active_attempts

    def get_task(self, task_id: str) -> TaskRecord:
        try:
            return self._tasks[task_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"task {task_id!r} is not registered") from exc

    def get_task_by_key(self, workflow_run_id: str, task_key: str) -> TaskRecord:
        task_id = self._task_key_index.get((workflow_run_id, task_key))
        if task_id is None:
            raise KeyError(f"task {task_key!r} is not registered in workflow run {workflow_run_id!r}")
        return self.get_task(task_id)

    def get_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        try:
            return self._attempts[attempt_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"attempt {attempt_id!r} is not registered") from exc

    def graph_for_task(self, task_id: str) -> WorkflowGraph:
        workflow_run_id = self._task_to_run.get(task_id)
        if workflow_run_id is None:
            raise KeyError(f"task {task_id!r} is not registered")
        return self.get_graph(workflow_run_id)

    def upstream_task_ids(self, task_id: str) -> list[str]:
        graph = self.graph_for_task(task_id)
        upstream: set[str] = set()
        frontier = [task_id]
        edge_map: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            if edge.is_hard_dependency:
                edge_map[edge.to_task_id].append(edge.from_task_id)
        while frontier:
            current = frontier.pop()
            for parent in edge_map.get(current, []):
                if parent not in upstream:
                    upstream.add(parent)
                    frontier.append(parent)
        return list(upstream)

    def dependent_task_ids(self, task_id: str) -> list[str]:
        graph = self.graph_for_task(task_id)
        dependents: set[str] = set()
        frontier = [task_id]
        edge_map: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            if edge.is_hard_dependency:
                edge_map[edge.from_task_id].append(edge.to_task_id)
        while frontier:
            current = frontier.pop()
            for child in edge_map.get(current, []):
                if child not in dependents:
                    dependents.add(child)
                    frontier.append(child)
        return list(dependents)

    def snapshot(self, workflow_run_id: str) -> WorkflowSnapshot:
        graph = self.get_graph(workflow_run_id)
        return WorkflowSnapshot(workflow_run=graph.workflow_run, tasks=graph.tasks, edges=graph.edges)


class InMemoryRepositoryIndex:
    """Convenience index used by storage-side tests."""

    def __init__(self, repository: InMemoryWorkflowRepository) -> None:
        self.repository = repository

    def task_state(self, task_id: str) -> str:
        return self.repository.get_task(task_id).state.value
