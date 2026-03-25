"""In-memory canonical repositories for AutoWeave entities."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from autoweave.models import (
    AttemptState,
    ArtifactRecord,
    ApprovalRequestRecord,
    EventRecord,
    HumanRequestRecord,
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
        self._graphs_order: list[str] = []
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._artifacts_by_run: dict[str, list[str]] = defaultdict(list)
        self._artifacts_by_task: dict[str, list[str]] = defaultdict(list)
        self._events: dict[str, EventRecord] = {}
        self._events_by_run: dict[str, list[str]] = defaultdict(list)
        self._human_requests: dict[str, HumanRequestRecord] = {}
        self._human_requests_by_run: dict[str, list[str]] = defaultdict(list)
        self._approval_requests: dict[str, ApprovalRequestRecord] = {}
        self._approval_requests_by_run: dict[str, list[str]] = defaultdict(list)

    def save_graph(self, graph: WorkflowGraph) -> WorkflowGraph:
        snapshot = graph.model_copy(deep=True)
        self._graphs[snapshot.workflow_run.id] = snapshot
        if snapshot.workflow_run.id not in self._graphs_order:
            self._graphs_order.append(snapshot.workflow_run.id)
        for task in snapshot.tasks:
            self._tasks[task.id] = task.model_copy(deep=True)
            self._task_to_run[task.id] = snapshot.workflow_run.id
            self._task_key_index[(snapshot.workflow_run.id, task.task_key)] = task.id
        return snapshot

    def list_workflow_runs(self) -> list[WorkflowRunRecord]:
        runs = [self._graphs[run_id].workflow_run.model_copy(deep=True) for run_id in self._graphs_order if run_id in self._graphs]
        return runs

    def get_graph(self, workflow_run_id: str) -> WorkflowGraph:
        try:
            return self._graphs[workflow_run_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"workflow run {workflow_run_id!r} is not registered") from exc

    def delete_workflow_run(self, workflow_run_id: str) -> bool:
        graph = self._graphs.pop(workflow_run_id, None)
        if graph is None:
            return False
        self._graphs_order = [run_id for run_id in self._graphs_order if run_id != workflow_run_id]
        task_ids = [task.id for task in graph.tasks]
        for task in graph.tasks:
            self._task_key_index.pop((workflow_run_id, task.task_key), None)
        for task_id in task_ids:
            self._tasks.pop(task_id, None)
            self._task_to_run.pop(task_id, None)
            for artifact_id in self._artifacts_by_task.pop(task_id, []):
                artifact = self._artifacts.pop(artifact_id, None)
                if artifact is not None:
                    self._artifacts_by_run[artifact.workflow_run_id] = [
                        existing
                        for existing in self._artifacts_by_run.get(artifact.workflow_run_id, [])
                        if existing != artifact_id
                    ]
        for attempt_id in self._attempts_by_run.pop(workflow_run_id, []):
            self._attempts.pop(attempt_id, None)
        for request_id in self._human_requests_by_run.pop(workflow_run_id, []):
            self._human_requests.pop(request_id, None)
        for request_id in self._approval_requests_by_run.pop(workflow_run_id, []):
            self._approval_requests.pop(request_id, None)
        for artifact_id in self._artifacts_by_run.pop(workflow_run_id, []):
            self._artifacts.pop(artifact_id, None)
        for event_id in self._events_by_run.pop(workflow_run_id, []):
            self._events.pop(event_id, None)
        return True

    def list_tasks_for_run(self, workflow_run_id: str) -> list[TaskRecord]:
        return [task.model_copy(deep=True) for task in self.get_graph(workflow_run_id).tasks]

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

    def list_attempts_for_run(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        attempt_ids = self._attempts_by_run.get(workflow_run_id, [])
        return [self._attempts[attempt_id].model_copy(deep=True) for attempt_id in attempt_ids if attempt_id in self._attempts]

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

    def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]:
        return [
            self._human_requests[request_id].model_copy(deep=True)
            for request_id in self._human_requests_by_run.get(workflow_run_id, [])
            if request_id in self._human_requests
        ]

    def save_human_request(self, request: HumanRequestRecord) -> HumanRequestRecord:
        record = request.model_copy(deep=True)
        self._human_requests[record.id] = record
        if record.id not in self._human_requests_by_run[record.workflow_run_id]:
            self._human_requests_by_run[record.workflow_run_id].append(record.id)
        return record

    def list_approval_requests_for_run(self, workflow_run_id: str) -> list[ApprovalRequestRecord]:
        return [
            self._approval_requests[request_id].model_copy(deep=True)
            for request_id in self._approval_requests_by_run.get(workflow_run_id, [])
            if request_id in self._approval_requests
        ]

    def save_approval_request(self, request: ApprovalRequestRecord) -> ApprovalRequestRecord:
        record = request.model_copy(deep=True)
        self._approval_requests[record.id] = record
        if record.id not in self._approval_requests_by_run[record.workflow_run_id]:
            self._approval_requests_by_run[record.workflow_run_id].append(record.id)
        return record

    def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]:
        artifact_ids = self._artifacts_by_run.get(workflow_run_id, [])
        return [self._artifacts[artifact_id].model_copy(deep=True) for artifact_id in artifact_ids if artifact_id in self._artifacts]

    def list_artifacts_for_task(self, task_id: str) -> list[ArtifactRecord]:
        artifact_ids = self._artifacts_by_task.get(task_id, [])
        return [self._artifacts[artifact_id].model_copy(deep=True) for artifact_id in artifact_ids if artifact_id in self._artifacts]

    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        record = artifact.model_copy(deep=True)
        self._artifacts[record.id] = record
        if record.id not in self._artifacts_by_run[record.workflow_run_id]:
            self._artifacts_by_run[record.workflow_run_id].append(record.id)
        if record.id not in self._artifacts_by_task[record.task_id]:
            self._artifacts_by_task[record.task_id].append(record.id)
        return record

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        event_ids = self._events_by_run.get(workflow_run_id, [])
        return [self._events[event_id].model_copy(deep=True) for event_id in event_ids if event_id in self._events]

    def save_event(self, event: EventRecord) -> EventRecord:
        record = event.model_copy(deep=True)
        self._events[record.id] = record
        if record.id not in self._events_by_run[record.workflow_run_id]:
            self._events_by_run[record.workflow_run_id].append(record.id)
        return record

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
