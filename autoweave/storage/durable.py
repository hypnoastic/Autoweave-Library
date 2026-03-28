"""Durable SQLite-backed canonical storage for AutoWeave.

The repository keeps the architecture boundaries intact while providing a
persistent local backing store for canonical workflow state, artifacts,
events, approvals, human requests, decisions, and memory records.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from autoweave.models import (
    ApprovalRequestRecord,
    ApprovalStatus,
    ArtifactRecord,
    AttemptState,
    DecisionRecord,
    EventRecord,
    HumanRequestRecord,
    HumanRequestStatus,
    MemoryEntryRecord,
    TaskAttemptRecord,
    TaskEdgeRecord,
    TaskRecord,
    TaskState,
    WorkflowDefinitionRecord,
    WorkflowGraph,
    WorkflowRunRecord,
)
from autoweave.storage.repositories import WorkflowSnapshot


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_load(value: str | bytes | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row.keys())
    placeholders = ", ".join([":" + key for key in row.keys()])
    updates = ", ".join([f"{key}=excluded.{key}" for key in row.keys() if key != "id"])
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        row,
    )


def _memory_entry_belongs_to_workflow_run(
    entry: MemoryEntryRecord,
    *,
    workflow_run_id: str,
    task_ids: set[str],
) -> bool:
    metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    metadata_workflow_run_id = str(metadata.get("workflow_run_id") or "").strip()
    metadata_task_id = str(metadata.get("task_id") or "").strip()
    return metadata_workflow_run_id == workflow_run_id or metadata_task_id in task_ids


@dataclass(frozen=True)
class DurableStorePaths:
    canonical: Path
    projection: Path


class SQLiteWorkflowRepository:
    """SQLite-backed canonical repository used by the local runtime.

    The repository is intentionally schema-driven and defensive. It persists the
    same canonical state that AutoWeave owns in the design docs, while keeping
    Neo4j and Redis downstream and ephemeral respectively.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    def _initialize(self) -> None:
        with _connect(self.database_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    graph_revision INTEGER NOT NULL DEFAULT 1,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    graph_revision INTEGER NOT NULL DEFAULT 1,
                    task_key TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(workflow_run_id, graph_revision, task_key)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    graph_revision INTEGER NOT NULL DEFAULT 1,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    graph_revision INTEGER NOT NULL DEFAULT 1,
                    task_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(task_id, attempt_number)
                );
                CREATE TABLE IF NOT EXISTS human_requests (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    memory_layer TEXT NOT NULL,
                    content TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        """Compatibility no-op for repository fixtures."""

    def save_graph(self, graph: WorkflowGraph) -> WorkflowGraph:
        snapshot = graph.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            self.save_workflow_run(snapshot.workflow_run, _conn=conn)
            conn.execute("DELETE FROM tasks WHERE workflow_run_id = ?", (snapshot.workflow_run.id,))
            for task in snapshot.tasks:
                self.save_task(task, _conn=conn)
            conn.execute("DELETE FROM edges WHERE workflow_run_id = ?", (snapshot.workflow_run.id,))
            for edge in snapshot.edges:
                conn.execute(
                    "INSERT INTO edges (id, workflow_run_id, graph_revision, data_json) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                    "graph_revision=excluded.graph_revision, data_json=excluded.data_json",
                    (
                        edge.id,
                        edge.workflow_run_id,
                        snapshot.workflow_run.graph_revision,
                        edge.model_dump_json(),
                    ),
                )
        return snapshot

    def get_graph(self, workflow_run_id: str) -> WorkflowGraph:
        with _connect(self.database_path) as conn:
            workflow_row = conn.execute(
                "SELECT data_json, graph_revision FROM workflow_runs WHERE id = ?",
                (workflow_run_id,),
            ).fetchone()
            if workflow_row is None:
                raise KeyError(f"workflow run {workflow_run_id!r} is not registered")
            task_rows = conn.execute(
                "SELECT data_json FROM tasks WHERE workflow_run_id = ? AND graph_revision = ? ORDER BY rowid",
                (workflow_run_id, workflow_row["graph_revision"]),
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT data_json FROM edges WHERE workflow_run_id = ? AND graph_revision = ? ORDER BY rowid",
                (workflow_run_id, workflow_row["graph_revision"]),
            ).fetchall()
        workflow_run = WorkflowRunRecord.model_validate_json(workflow_row["data_json"])
        tasks = [TaskRecord.model_validate_json(row["data_json"]) for row in task_rows]
        edges = [TaskEdgeRecord.model_validate_json(row["data_json"]) for row in edge_rows]
        return WorkflowGraph(workflow_run=workflow_run, tasks=tasks, edges=edges)

    def delete_workflow_run(self, workflow_run_id: str) -> bool:
        with _connect(self.database_path) as conn:
            workflow_row = conn.execute(
                "SELECT data_json FROM workflow_runs WHERE id = ?",
                (workflow_run_id,),
            ).fetchone()
            if workflow_row is None:
                return False
            workflow_run = WorkflowRunRecord.model_validate_json(workflow_row["data_json"])
            task_rows = conn.execute(
                "SELECT id FROM tasks WHERE workflow_run_id = ?",
                (workflow_run_id,),
            ).fetchall()
            task_ids = [str(row["id"]) for row in task_rows]
            if task_ids:
                placeholders = ", ".join(["?"] * len(task_ids))
                conn.execute(
                    f"DELETE FROM memory_entries WHERE scope_type = 'task' AND scope_id IN ({placeholders})",
                    task_ids,
                )
            conn.execute(
                "DELETE FROM memory_entries WHERE scope_type = 'workflow_run' AND scope_id = ?",
                (workflow_run_id,),
            )
            project_memory_rows = conn.execute(
                "SELECT id, data_json FROM memory_entries WHERE scope_type = 'project' AND scope_id = ?",
                (workflow_run.project_id,),
            ).fetchall()
            stale_project_memory_ids = [
                str(row["id"])
                for row in project_memory_rows
                if _memory_entry_belongs_to_workflow_run(
                    MemoryEntryRecord.model_validate_json(row["data_json"]),
                    workflow_run_id=workflow_run_id,
                    task_ids=set(task_ids),
                )
            ]
            if stale_project_memory_ids:
                placeholders = ", ".join(["?"] * len(stale_project_memory_ids))
                conn.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
                    stale_project_memory_ids,
                )
            for table in (
                "events",
                "artifacts",
                "approval_requests",
                "human_requests",
                "decisions",
                "attempts",
                "edges",
                "tasks",
            ):
                conn.execute(f"DELETE FROM {table} WHERE workflow_run_id = ?", (workflow_run_id,))
            conn.execute("DELETE FROM workflow_runs WHERE id = ?", (workflow_run_id,))
        return True

    def list_workflow_runs(self) -> list[WorkflowRunRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute("SELECT data_json FROM workflow_runs").fetchall()
        runs = [WorkflowRunRecord.model_validate_json(row["data_json"]) for row in rows]
        runs.sort(
            key=lambda item: (
                item.started_at.isoformat() if item.started_at is not None else "",
                item.ended_at.isoformat() if item.ended_at is not None else "",
                item.id,
            ),
            reverse=True,
        )
        return runs

    def save_workflow_definition(
        self,
        workflow_definition: WorkflowDefinitionRecord,
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> WorkflowDefinitionRecord:
        record = workflow_definition.model_copy(deep=True)
        owns_connection = _conn is None
        conn = _conn or _connect(self.database_path)
        try:
            conn.execute(
                "INSERT INTO workflow_definitions (id, project_id, version, data_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id, version=excluded.version, "
                "data_json=excluded.data_json",
                (
                    record.id,
                    record.project_id,
                    record.version,
                    record.model_dump_json(),
                ),
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()
        return record

    def get_workflow_definition(self, definition_id: str) -> WorkflowDefinitionRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM workflow_definitions WHERE id = ?",
                (definition_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow definition {definition_id!r} is not registered")
            return WorkflowDefinitionRecord.model_validate_json(row["data_json"])

    def save_workflow_run(
        self,
        workflow_run: WorkflowRunRecord,
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> WorkflowRunRecord:
        record = workflow_run.model_copy(deep=True)
        owns_connection = _conn is None
        conn = _conn or _connect(self.database_path)
        try:
            conn.execute(
                "INSERT INTO workflow_runs (id, graph_revision, data_json) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET graph_revision=excluded.graph_revision, data_json=excluded.data_json",
                (
                    record.id,
                    record.graph_revision,
                    record.model_dump_json(),
                ),
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()
        return record

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRunRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM workflow_runs WHERE id = ?",
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow run {workflow_run_id!r} is not registered")
            return WorkflowRunRecord.model_validate_json(row["data_json"])

    def save_task(self, task: TaskRecord, *, _conn: sqlite3.Connection | None = None) -> TaskRecord:
        record = task.model_copy(deep=True)
        owns_connection = _conn is None
        conn = _conn or _connect(self.database_path)
        try:
            graph_revision = self._graph_revision_for_run(conn, record.workflow_run_id)
            conn.execute(
                "INSERT INTO tasks (id, workflow_run_id, graph_revision, task_key, data_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                "graph_revision=excluded.graph_revision, task_key=excluded.task_key, data_json=excluded.data_json",
                (
                    record.id,
                    record.workflow_run_id,
                    graph_revision,
                    record.task_key,
                    record.model_dump_json(),
                ),
            )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()
        return record

    def get_task(self, task_id: str) -> TaskRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute("SELECT data_json FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"task {task_id!r} is not registered")
            return TaskRecord.model_validate_json(row["data_json"])

    def list_tasks_for_run(self, workflow_run_id: str) -> list[TaskRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM tasks WHERE workflow_run_id = ? ORDER BY task_key",
                (workflow_run_id,),
            ).fetchall()
        return [TaskRecord.model_validate_json(row["data_json"]) for row in rows]

    def get_task_by_key(self, workflow_run_id: str, task_key: str) -> TaskRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM tasks WHERE workflow_run_id = ? AND task_key = ?",
                (workflow_run_id, task_key),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"task {task_key!r} is not registered in workflow run {workflow_run_id!r}"
                )
            return TaskRecord.model_validate_json(row["data_json"])

    def save_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord:
        record = attempt.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            self._save_attempt(record, conn)
        return record

    def update_attempt_state(self, attempt_id: str, state: AttemptState) -> TaskAttemptRecord:
        attempt = self.get_attempt(attempt_id)
        updated = attempt.transition(state)
        return self.save_attempt(updated)

    def list_active_attempts(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        active_states = {
            AttemptState.QUEUED.value,
            AttemptState.DISPATCHING.value,
            AttemptState.RUNNING.value,
            AttemptState.PAUSED.value,
            AttemptState.NEEDS_INPUT.value,
        }
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM attempts WHERE workflow_run_id = ? AND state IN (?, ?, ?, ?, ?) ORDER BY rowid",
                (
                    workflow_run_id,
                    *sorted(active_states),
                ),
            ).fetchall()
        return [TaskAttemptRecord.model_validate_json(row["data_json"]) for row in rows]

    def get_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute("SELECT data_json FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(f"attempt {attempt_id!r} is not registered")
            return TaskAttemptRecord.model_validate_json(row["data_json"])

    def list_attempts_for_run(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM attempts WHERE workflow_run_id = ? ORDER BY attempt_number, rowid",
                (workflow_run_id,),
            ).fetchall()
        return [TaskAttemptRecord.model_validate_json(row["data_json"]) for row in rows]

    def graph_for_task(self, task_id: str) -> WorkflowGraph:
        task = self.get_task(task_id)
        return self.get_graph(task.workflow_run_id)

    def upstream_task_ids(self, task_id: str) -> list[str]:
        graph = self.graph_for_task(task_id)
        upstream: set[str] = set()
        frontier = [task_id]
        edge_map: dict[str, list[str]] = {}
        for edge in graph.edges:
            if edge.is_hard_dependency:
                edge_map.setdefault(edge.to_task_id, []).append(edge.from_task_id)
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
        edge_map: dict[str, list[str]] = {}
        for edge in graph.edges:
            if edge.is_hard_dependency:
                edge_map.setdefault(edge.from_task_id, []).append(edge.to_task_id)
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

    def save_human_request(self, request: HumanRequestRecord) -> HumanRequestRecord:
        record = request.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            self._save_human_request(record, conn)
        return record

    def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM human_requests WHERE workflow_run_id = ? ORDER BY rowid",
                (workflow_run_id,),
            ).fetchall()
        return [HumanRequestRecord.model_validate_json(row["data_json"]) for row in rows]

    def get_human_request(self, request_id: str) -> HumanRequestRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM human_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"human request {request_id!r} is not registered")
            return HumanRequestRecord.model_validate_json(row["data_json"])

    def save_approval_request(self, request: ApprovalRequestRecord) -> ApprovalRequestRecord:
        record = request.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            self._save_approval_request(record, conn)
        return record

    def list_approval_requests_for_run(self, workflow_run_id: str) -> list[ApprovalRequestRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM approval_requests WHERE workflow_run_id = ? ORDER BY rowid",
                (workflow_run_id,),
            ).fetchall()
        return [ApprovalRequestRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_runtime_state(
        self,
        *,
        workflow_run: WorkflowRunRecord,
        tasks: Iterable[TaskRecord],
        attempts: Iterable[TaskAttemptRecord],
        human_requests: Iterable[HumanRequestRecord] = (),
        approval_requests: Iterable[ApprovalRequestRecord] = (),
        graph: WorkflowGraph | None = None,
    ) -> None:
        with _connect(self.database_path) as conn:
            if graph is not None:
                snapshot = graph.model_copy(deep=True)
                self.save_workflow_run(snapshot.workflow_run, _conn=conn)
                conn.execute("DELETE FROM tasks WHERE workflow_run_id = ?", (snapshot.workflow_run.id,))
                for task in snapshot.tasks:
                    self.save_task(task, _conn=conn)
                conn.execute("DELETE FROM edges WHERE workflow_run_id = ?", (snapshot.workflow_run.id,))
                for edge in snapshot.edges:
                    conn.execute(
                        "INSERT INTO edges (id, workflow_run_id, graph_revision, data_json) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                        "graph_revision=excluded.graph_revision, data_json=excluded.data_json",
                        (
                            edge.id,
                            edge.workflow_run_id,
                            snapshot.workflow_run.graph_revision,
                            edge.model_dump_json(),
                        ),
                    )
            else:
                self.save_workflow_run(workflow_run, _conn=conn)
                for task in tasks:
                    self.save_task(task, _conn=conn)
            for attempt in attempts:
                self._save_attempt(attempt, conn)
            for request in human_requests:
                self._save_human_request(request, conn)
            for request in approval_requests:
                self._save_approval_request(request, conn)

    def get_approval_request(self, request_id: str) -> ApprovalRequestRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM approval_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"approval request {request_id!r} is not registered")
            return ApprovalRequestRecord.model_validate_json(row["data_json"])

    def append_event(self, event: EventRecord) -> EventRecord:
        record = event.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            if record.sequence_no <= 0:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM events WHERE workflow_run_id = ?",
                    (record.workflow_run_id,),
                ).fetchone()
                record = record.model_copy(update={"sequence_no": int(row["next_sequence"])})
            conn.execute(
                "INSERT INTO events (id, workflow_run_id, sequence_no, data_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                "sequence_no=excluded.sequence_no, data_json=excluded.data_json",
                (record.id, record.workflow_run_id, record.sequence_no, record.model_dump_json()),
            )
        return record

    def save_event(self, event: EventRecord) -> EventRecord:
        return self.append_event(event)

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM events WHERE workflow_run_id = ? ORDER BY sequence_no, rowid",
                (workflow_run_id,),
            ).fetchall()
        return [EventRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        record = artifact.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            conn.execute(
                "INSERT INTO artifacts (id, workflow_run_id, task_id, artifact_type, status, version, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                "task_id=excluded.task_id, artifact_type=excluded.artifact_type, status=excluded.status, "
                "version=excluded.version, data_json=excluded.data_json",
                (
                    record.id,
                    record.workflow_run_id,
                    record.task_id,
                    record.artifact_type,
                    record.status.value,
                    record.version,
                    record.model_dump_json(),
                ),
            )
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"artifact {artifact_id!r} is not registered")
            return ArtifactRecord.model_validate_json(row["data_json"])

    def list_artifacts_for_task(self, task_id: str) -> list[ArtifactRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM artifacts WHERE task_id = ? ORDER BY version, rowid",
                (task_id,),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM artifacts WHERE workflow_run_id = ? ORDER BY version, rowid",
                (workflow_run_id,),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_decision(self, decision: DecisionRecord) -> DecisionRecord:
        record = decision.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            conn.execute(
                "INSERT INTO decisions (id, workflow_run_id, task_id, data_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
                "task_id=excluded.task_id, data_json=excluded.data_json",
                (
                    record.id,
                    record.workflow_run_id,
                    record.task_id,
                    record.model_dump_json(),
                ),
            )
        return record

    def get_decision(self, decision_id: str) -> DecisionRecord:
        with _connect(self.database_path) as conn:
            row = conn.execute(
                "SELECT data_json FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"decision {decision_id!r} is not registered")
            return DecisionRecord.model_validate_json(row["data_json"])

    def list_decisions_for_task(self, task_id: str) -> list[DecisionRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM decisions WHERE task_id = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
        return [DecisionRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_memory_entry(self, entry: MemoryEntryRecord) -> MemoryEntryRecord:
        record = entry.model_copy(deep=True)
        with _connect(self.database_path) as conn:
            conn.execute(
                "INSERT INTO memory_entries (id, project_id, scope_type, scope_id, memory_layer, content, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id, scope_type=excluded.scope_type, "
                "scope_id=excluded.scope_id, memory_layer=excluded.memory_layer, content=excluded.content, "
                "data_json=excluded.data_json",
                (
                    record.id,
                    record.project_id,
                    record.scope_type,
                    record.scope_id,
                    record.memory_layer.value,
                    record.content,
                    record.model_dump_json(),
                ),
            )
        return record

    def _graph_revision_for_run(self, conn: sqlite3.Connection, workflow_run_id: str) -> int:
        row = conn.execute(
            "SELECT graph_revision FROM workflow_runs WHERE id = ?",
            (workflow_run_id,),
        ).fetchone()
        return int(row["graph_revision"]) if row is not None else 1

    def _task_workflow_run_id(self, conn: sqlite3.Connection, task_id: str) -> str:
        row = conn.execute(
            "SELECT workflow_run_id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"task {task_id!r} is not registered")
        return str(row["workflow_run_id"])

    def _save_attempt(self, attempt: TaskAttemptRecord, conn: sqlite3.Connection) -> None:
        record = attempt.model_copy(deep=True)
        workflow_run_id = self._task_workflow_run_id(conn, record.task_id)
        graph_revision = self._graph_revision_for_run(conn, workflow_run_id)
        conn.execute(
            "INSERT INTO attempts (id, workflow_run_id, graph_revision, task_id, attempt_number, state, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
            "graph_revision=excluded.graph_revision, task_id=excluded.task_id, attempt_number=excluded.attempt_number, "
            "state=excluded.state, data_json=excluded.data_json",
            (
                record.id,
                workflow_run_id,
                graph_revision,
                record.task_id,
                record.attempt_number,
                record.state.value,
                record.model_dump_json(),
            ),
        )

    def _save_human_request(self, request: HumanRequestRecord, conn: sqlite3.Connection) -> None:
        record = request.model_copy(deep=True)
        conn.execute(
            "INSERT INTO human_requests (id, workflow_run_id, task_id, status, data_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
            "task_id=excluded.task_id, status=excluded.status, data_json=excluded.data_json",
            (
                record.id,
                record.workflow_run_id,
                record.task_id,
                record.status.value,
                record.model_dump_json(),
            ),
        )

    def _save_approval_request(self, request: ApprovalRequestRecord, conn: sqlite3.Connection) -> None:
        record = request.model_copy(deep=True)
        conn.execute(
            "INSERT INTO approval_requests (id, workflow_run_id, task_id, status, data_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, "
            "task_id=excluded.task_id, status=excluded.status, data_json=excluded.data_json",
            (
                record.id,
                record.workflow_run_id,
                record.task_id,
                record.status.value,
                record.model_dump_json(),
            ),
        )

    def search_memory(self, query: str, scope: str, top_k: int) -> list[MemoryEntryRecord]:
        scope_type, _, scope_id = scope.partition(":")
        if not scope_type:
            scope_type, scope_id = "project", scope
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        clauses = " AND ".join(["LOWER(content) LIKE ?"] * len(terms))
        params = [f"%{term}%" for term in terms]
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                f"SELECT data_json FROM memory_entries WHERE scope_type = ? AND scope_id = ? AND {clauses} "
                "ORDER BY rowid LIMIT ?",
                [scope_type, scope_id, *params, top_k],
            ).fetchall()
        return [MemoryEntryRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_memory_entries(self, scope_type: str, scope_id: str) -> list[MemoryEntryRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT data_json FROM memory_entries WHERE scope_type = ? AND scope_id = ? ORDER BY rowid",
                (scope_type, scope_id),
            ).fetchall()
        return [MemoryEntryRecord.model_validate_json(row["data_json"]) for row in rows]
