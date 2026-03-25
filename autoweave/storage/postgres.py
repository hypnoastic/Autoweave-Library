"""Postgres-backed canonical repository for AutoWeave."""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from autoweave.models import (
    ApprovalRequestRecord,
    ArtifactRecord,
    AttemptState,
    DecisionRecord,
    EventRecord,
    HumanRequestRecord,
    MemoryEntryRecord,
    TaskAttemptRecord,
    TaskEdgeRecord,
    TaskRecord,
    WorkflowDefinitionRecord,
    WorkflowGraph,
    WorkflowRunRecord,
)
from autoweave.storage.repositories import WorkflowSnapshot

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    if not _IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


@dataclass(frozen=True)
class PostgresRepositoryConfig:
    dsn: str
    schema: str = "autoweave"
    connect_timeout_seconds: int = 10


class PostgresWorkflowRepository:
    """Canonical repository backed by the configured Postgres target."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "autoweave",
        connect_timeout_seconds: int = 10,
    ) -> None:
        self.config = PostgresRepositoryConfig(
            dsn=dsn,
            schema=_validate_identifier(schema),
            connect_timeout_seconds=connect_timeout_seconds,
        )
        self.schema = self.config.schema
        self._cached_connection: psycopg.Connection | None = None
        self._initialize()

    def _qualified(self, table_name: str) -> sql.Composed:
        return sql.SQL("{}.{}").format(
            sql.Identifier(self.config.schema),
            sql.Identifier(table_name),
        )

    def _connect(self) -> psycopg.Connection:
        cached = self._cached_connection
        if cached is not None and not cached.closed and not getattr(cached, "broken", False):
            return cached
        if cached is not None and not cached.closed:
            cached.close()
        conn = psycopg.connect(
            self.config.dsn,
            connect_timeout=self.config.connect_timeout_seconds,
            row_factory=dict_row,
        )
        setattr(conn, "_pool", self)
        self._cached_connection = conn
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(self.config.schema)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            graph_revision INTEGER NOT NULL DEFAULT 1,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("workflow_runs"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            version TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("workflow_definitions"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            graph_revision INTEGER NOT NULL DEFAULT 1,
                            task_key TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            UNIQUE(workflow_run_id, graph_revision, task_key)
                        )
                        """
                    ).format(self._qualified("tasks"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            graph_revision INTEGER NOT NULL DEFAULT 1,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("edges"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            graph_revision INTEGER NOT NULL DEFAULT 1,
                            task_id TEXT NOT NULL,
                            attempt_number INTEGER NOT NULL,
                            state TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            UNIQUE(task_id, attempt_number)
                        )
                        """
                    ).format(self._qualified("attempts"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            task_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("human_requests"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            task_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("approval_requests"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            task_id TEXT NOT NULL,
                            artifact_type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            version INTEGER NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("artifacts"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            task_id TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("decisions"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            scope_type TEXT NOT NULL,
                            scope_id TEXT NOT NULL,
                            memory_layer TEXT NOT NULL,
                            content TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("memory_entries"))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            sequence_no BIGINT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                        """
                    ).format(self._qualified("events"))
                )
            conn.commit()

    def close(self) -> None:
        conn = self._cached_connection
        if conn is not None and not conn.closed:
            conn.close()
        self._cached_connection = None

    def save_graph(self, graph: WorkflowGraph) -> WorkflowGraph:
        snapshot = graph.model_copy(deep=True)
        with self._connect() as conn:
            self._save_graph(snapshot, conn)
            conn.commit()
        return snapshot

    def get_graph(self, workflow_run_id: str) -> WorkflowGraph:
        with self._connect() as conn:
            workflow_row = conn.execute(
                sql.SQL("SELECT data_json, graph_revision FROM {} WHERE id = %s").format(
                    self._qualified("workflow_runs")
                ),
                (workflow_run_id,),
            ).fetchone()
            if workflow_row is None:
                raise KeyError(f"workflow run {workflow_run_id!r} is not registered")
            task_rows = conn.execute(
                sql.SQL(
                    "SELECT data_json FROM {} WHERE workflow_run_id = %s AND graph_revision = %s ORDER BY id"
                ).format(self._qualified("tasks")),
                (workflow_run_id, workflow_row["graph_revision"]),
            ).fetchall()
            edge_rows = conn.execute(
                sql.SQL(
                    "SELECT data_json FROM {} WHERE workflow_run_id = %s AND graph_revision = %s ORDER BY id"
                ).format(self._qualified("edges")),
                (workflow_run_id, workflow_row["graph_revision"]),
            ).fetchall()
        workflow_run = WorkflowRunRecord.model_validate_json(workflow_row["data_json"])
        tasks = [TaskRecord.model_validate_json(row["data_json"]) for row in task_rows]
        edges = [TaskEdgeRecord.model_validate_json(row["data_json"]) for row in edge_rows]
        return WorkflowGraph(workflow_run=workflow_run, tasks=tasks, edges=edges)

    def delete_workflow_run(self, workflow_run_id: str) -> bool:
        with self._connect() as conn:
            workflow_row = conn.execute(
                sql.SQL("SELECT id FROM {} WHERE id = %s").format(self._qualified("workflow_runs")),
                (workflow_run_id,),
            ).fetchone()
            if workflow_row is None:
                return False
            task_rows = conn.execute(
                sql.SQL("SELECT id FROM {} WHERE workflow_run_id = %s").format(self._qualified("tasks")),
                (workflow_run_id,),
            ).fetchall()
            task_ids = [str(row["id"]) for row in task_rows]
            if task_ids:
                conn.execute(
                    sql.SQL(
                        "DELETE FROM {} WHERE scope_type = %s AND scope_id = ANY(%s)"
                    ).format(self._qualified("memory_entries")),
                    ("task", task_ids),
                )
            conn.execute(
                sql.SQL("DELETE FROM {} WHERE scope_type = %s AND scope_id = %s").format(
                    self._qualified("memory_entries")
                ),
                ("workflow_run", workflow_run_id),
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
                conn.execute(
                    sql.SQL("DELETE FROM {} WHERE workflow_run_id = %s").format(self._qualified(table)),
                    (workflow_run_id,),
                )
            conn.execute(
                sql.SQL("DELETE FROM {} WHERE id = %s").format(self._qualified("workflow_runs")),
                (workflow_run_id,),
            )
            conn.commit()
        return True

    def list_workflow_runs(self) -> list[WorkflowRunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {}").format(self._qualified("workflow_runs"))
            ).fetchall()
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

    def save_workflow_definition(self, workflow_definition: WorkflowDefinitionRecord) -> WorkflowDefinitionRecord:
        record = workflow_definition.model_copy(deep=True)
        with self._connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (id, project_id, version, data_json)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET project_id = EXCLUDED.project_id,
                        version = EXCLUDED.version,
                        data_json = EXCLUDED.data_json
                    """
                ).format(self._qualified("workflow_definitions")),
                (
                    record.id,
                    record.project_id,
                    record.version,
                    record.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def get_workflow_definition(self, definition_id: str) -> WorkflowDefinitionRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("workflow_definitions")
                ),
                (definition_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow definition {definition_id!r} is not registered")
            return WorkflowDefinitionRecord.model_validate_json(row["data_json"])

    def save_workflow_run(self, workflow_run: WorkflowRunRecord) -> WorkflowRunRecord:
        with self._connect() as conn:
            self._save_workflow_run(workflow_run, conn)
            conn.commit()
        return workflow_run.model_copy(deep=True)

    def _save_workflow_run(self, workflow_run: WorkflowRunRecord, conn: psycopg.Connection) -> None:
        record = workflow_run.model_copy(deep=True)
        conn.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, graph_revision, data_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET graph_revision = EXCLUDED.graph_revision,
                    data_json = EXCLUDED.data_json
                """
            ).format(self._qualified("workflow_runs")),
            (
                record.id,
                record.graph_revision,
                record.model_dump_json(),
            ),
        )

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRunRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("workflow_runs")
                ),
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow run {workflow_run_id!r} is not registered")
            return WorkflowRunRecord.model_validate_json(row["data_json"])

    def save_task(self, task: TaskRecord) -> TaskRecord:
        with self._connect() as conn:
            self._save_task(task, conn)
            conn.commit()
        return task.model_copy(deep=True)

    def _save_task(self, task: TaskRecord, conn: psycopg.Connection) -> None:
        record = task.model_copy(deep=True)
        graph_revision = self._graph_revision_for_run(conn, record.workflow_run_id)
        conn.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, workflow_run_id, graph_revision, task_key, data_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET workflow_run_id = EXCLUDED.workflow_run_id,
                    graph_revision = EXCLUDED.graph_revision,
                    task_key = EXCLUDED.task_key,
                    data_json = EXCLUDED.data_json
                """
            ).format(self._qualified("tasks")),
            (
                record.id,
                record.workflow_run_id,
                graph_revision,
                record.task_key,
                record.model_dump_json(),
            ),
        )

    def get_task(self, task_id: str) -> TaskRecord:
        last_error: psycopg.OperationalError | None = None
        for _ in range(2):
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                            self._qualified("tasks")
                        ),
                        (task_id,),
                    ).fetchone()
                    if row is None:
                        raise KeyError(f"task {task_id!r} is not registered")
                    return TaskRecord.model_validate_json(row["data_json"])
            except psycopg.OperationalError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def get_task_by_key(self, workflow_run_id: str, task_key: str) -> TaskRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s AND task_key = %s").format(
                    self._qualified("tasks")
                ),
                (workflow_run_id, task_key),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"task {task_key!r} is not registered in workflow run {workflow_run_id!r}"
                )
            return TaskRecord.model_validate_json(row["data_json"])

    def list_tasks_for_run(self, workflow_run_id: str) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY task_key").format(
                    self._qualified("tasks")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [TaskRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord:
        record = attempt.model_copy(deep=True)
        last_error: psycopg.OperationalError | None = None
        for _ in range(2):
            try:
                with self._connect() as conn:
                    self._save_attempt(record, conn)
                    conn.commit()
                return record
            except psycopg.OperationalError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def update_attempt_state(self, attempt_id: str, state: AttemptState) -> TaskAttemptRecord:
        attempt = self.get_attempt(attempt_id)
        updated = attempt.transition(state)
        return self.save_attempt(updated)

    def list_active_attempts(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        active_states = (
            AttemptState.QUEUED.value,
            AttemptState.DISPATCHING.value,
            AttemptState.RUNNING.value,
            AttemptState.PAUSED.value,
            AttemptState.NEEDS_INPUT.value,
        )
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL(
                    "SELECT data_json FROM {} WHERE workflow_run_id = %s AND state = ANY(%s) ORDER BY attempt_number"
                ).format(self._qualified("attempts")),
                (workflow_run_id, list(active_states)),
            ).fetchall()
        return [TaskAttemptRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_attempts_for_task(self, task_id: str) -> list[TaskAttemptRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE task_id = %s ORDER BY attempt_number").format(
                    self._qualified("attempts")
                ),
                (task_id,),
            ).fetchall()
        return [TaskAttemptRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_attempts_for_run(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY attempt_number, id").format(
                    self._qualified("attempts")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [TaskAttemptRecord.model_validate_json(row["data_json"]) for row in rows]

    def get_attempt(self, attempt_id: str) -> TaskAttemptRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("attempts")
                ),
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"attempt {attempt_id!r} is not registered")
            return TaskAttemptRecord.model_validate_json(row["data_json"])

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
        with self._connect() as conn:
            self._save_human_request(record, conn)
            conn.commit()
        return record

    def get_human_request(self, request_id: str) -> HumanRequestRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("human_requests")
                ),
                (request_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"human request {request_id!r} is not registered")
            return HumanRequestRecord.model_validate_json(row["data_json"])

    def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY id").format(
                    self._qualified("human_requests")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [HumanRequestRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_approval_request(self, request: ApprovalRequestRecord) -> ApprovalRequestRecord:
        record = request.model_copy(deep=True)
        with self._connect() as conn:
            self._save_approval_request(record, conn)
            conn.commit()
        return record

    def save_runtime_state(
        self,
        *,
        workflow_run: WorkflowRunRecord,
        tasks: list[TaskRecord],
        attempts: list[TaskAttemptRecord],
        human_requests: list[HumanRequestRecord] | tuple[HumanRequestRecord, ...] = (),
        approval_requests: list[ApprovalRequestRecord] | tuple[ApprovalRequestRecord, ...] = (),
        graph: WorkflowGraph | None = None,
    ) -> None:
        last_error: psycopg.OperationalError | None = None
        for _ in range(3):
            try:
                with self._connect() as conn:
                    if graph is not None:
                        self._save_graph(graph.model_copy(deep=True), conn)
                    else:
                        self._save_workflow_run(workflow_run, conn)
                        for task in tasks:
                            self._save_task(task, conn)
                    for attempt in attempts:
                        self._save_attempt(attempt, conn)
                    for request in human_requests:
                        self._save_human_request(request, conn)
                    for request in approval_requests:
                        self._save_approval_request(request, conn)
                    conn.commit()
                return
            except psycopg.OperationalError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def get_approval_request(self, request_id: str) -> ApprovalRequestRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("approval_requests")
                ),
                (request_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"approval request {request_id!r} is not registered")
            return ApprovalRequestRecord.model_validate_json(row["data_json"])

    def list_approval_requests_for_run(self, workflow_run_id: str) -> list[ApprovalRequestRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY id").format(
                    self._qualified("approval_requests")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [ApprovalRequestRecord.model_validate_json(row["data_json"]) for row in rows]

    def append_event(self, event: EventRecord) -> EventRecord:
        record = event.model_copy(deep=True)
        with self._connect() as conn:
            if record.sequence_no <= 0:
                row = conn.execute(
                    sql.SQL(
                        "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM {} WHERE workflow_run_id = %s"
                    ).format(self._qualified("events")),
                    (record.workflow_run_id,),
                ).fetchone()
                record = record.model_copy(update={"sequence_no": int(row["next_sequence"])})
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (id, workflow_run_id, sequence_no, data_json)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET workflow_run_id = EXCLUDED.workflow_run_id,
                        sequence_no = EXCLUDED.sequence_no,
                        data_json = EXCLUDED.data_json
                    """
                ).format(self._qualified("events")),
                (
                    record.id,
                    record.workflow_run_id,
                    record.sequence_no,
                    record.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def save_event(self, event: EventRecord) -> EventRecord:
        return self.append_event(event)

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY sequence_no, id").format(
                    self._qualified("events")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [EventRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        record = artifact.model_copy(deep=True)
        with self._connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (id, workflow_run_id, task_id, artifact_type, status, version, data_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET workflow_run_id = EXCLUDED.workflow_run_id,
                        task_id = EXCLUDED.task_id,
                        artifact_type = EXCLUDED.artifact_type,
                        status = EXCLUDED.status,
                        version = EXCLUDED.version,
                        data_json = EXCLUDED.data_json
                    """
                ).format(self._qualified("artifacts")),
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
            conn.commit()
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("artifacts")
                ),
                (artifact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"artifact {artifact_id!r} is not registered")
            return ArtifactRecord.model_validate_json(row["data_json"])

    def list_artifacts_for_task(self, task_id: str) -> list[ArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE task_id = %s ORDER BY version, id").format(
                    self._qualified("artifacts")
                ),
                (task_id,),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE workflow_run_id = %s ORDER BY task_id, version, id").format(
                    self._qualified("artifacts")
                ),
                (workflow_run_id,),
            ).fetchall()
        return [ArtifactRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_decision(self, decision: DecisionRecord) -> DecisionRecord:
        record = decision.model_copy(deep=True)
        with self._connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (id, workflow_run_id, task_id, data_json)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET workflow_run_id = EXCLUDED.workflow_run_id,
                        task_id = EXCLUDED.task_id,
                        data_json = EXCLUDED.data_json
                    """
                ).format(self._qualified("decisions")),
                (
                    record.id,
                    record.workflow_run_id,
                    record.task_id,
                    record.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def get_decision(self, decision_id: str) -> DecisionRecord:
        with self._connect() as conn:
            row = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE id = %s").format(
                    self._qualified("decisions")
                ),
                (decision_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"decision {decision_id!r} is not registered")
            return DecisionRecord.model_validate_json(row["data_json"])

    def list_decisions_for_task(self, task_id: str) -> list[DecisionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE task_id = %s ORDER BY id").format(
                    self._qualified("decisions")
                ),
                (task_id,),
            ).fetchall()
        return [DecisionRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_memory_entry(self, entry: MemoryEntryRecord) -> MemoryEntryRecord:
        record = entry.model_copy(deep=True)
        with self._connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (id, project_id, scope_type, scope_id, memory_layer, content, data_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET project_id = EXCLUDED.project_id,
                        scope_type = EXCLUDED.scope_type,
                        scope_id = EXCLUDED.scope_id,
                        memory_layer = EXCLUDED.memory_layer,
                        content = EXCLUDED.content,
                        data_json = EXCLUDED.data_json
                    """
                ).format(self._qualified("memory_entries")),
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
            conn.commit()
        return record

    def search_memory(self, query: str, scope: str, top_k: int) -> list[MemoryEntryRecord]:
        scope_type, _, scope_id = scope.partition(":")
        if not scope_type:
            scope_type, scope_id = "project", scope
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        where = sql.SQL(" AND ").join(
            sql.SQL("LOWER(content) LIKE %s") for _ in terms
        )
        params: list[object] = [scope_type, scope_id, *[f"%{term}%" for term in terms], top_k]
        query_sql = sql.SQL(
            "SELECT data_json FROM {} WHERE scope_type = %s AND scope_id = %s AND "
        ).format(self._qualified("memory_entries")) + where + sql.SQL(" ORDER BY id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(query_sql, params).fetchall()
        return [MemoryEntryRecord.model_validate_json(row["data_json"]) for row in rows]

    def list_memory_entries(self, scope_type: str, scope_id: str) -> list[MemoryEntryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                sql.SQL("SELECT data_json FROM {} WHERE scope_type = %s AND scope_id = %s ORDER BY id").format(
                    self._qualified("memory_entries")
                ),
                (scope_type, scope_id),
            ).fetchall()
        return [MemoryEntryRecord.model_validate_json(row["data_json"]) for row in rows]

    def _graph_revision_for_run(self, conn: psycopg.Connection, workflow_run_id: str) -> int:
        row = conn.execute(
            sql.SQL("SELECT graph_revision FROM {} WHERE id = %s").format(
                self._qualified("workflow_runs")
            ),
            (workflow_run_id,),
        ).fetchone()
        return int(row["graph_revision"]) if row is not None else 1

    def _task_workflow_run_id(self, conn: psycopg.Connection, task_id: str) -> str:
        row = conn.execute(
            sql.SQL("SELECT workflow_run_id FROM {} WHERE id = %s").format(
                self._qualified("tasks")
            ),
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"task {task_id!r} is not registered")
        return str(row["workflow_run_id"])

    def _save_graph(self, graph: WorkflowGraph, conn: psycopg.Connection) -> None:
        self._save_workflow_run(graph.workflow_run, conn)
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DELETE FROM {} WHERE workflow_run_id = %s").format(
                    self._qualified("tasks")
                ),
                (graph.workflow_run.id,),
            )
            for task in graph.tasks:
                self._save_task(task, conn)
            cursor.execute(
                sql.SQL("DELETE FROM {} WHERE workflow_run_id = %s").format(
                    self._qualified("edges")
                ),
                (graph.workflow_run.id,),
            )
            for edge in graph.edges:
                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (id, workflow_run_id, graph_revision, data_json)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE
                        SET workflow_run_id = EXCLUDED.workflow_run_id,
                            graph_revision = EXCLUDED.graph_revision,
                            data_json = EXCLUDED.data_json
                        """
                    ).format(self._qualified("edges")),
                    (
                        edge.id,
                        edge.workflow_run_id,
                        graph.workflow_run.graph_revision,
                        edge.model_dump_json(),
                    ),
                )

    def _save_attempt(self, attempt: TaskAttemptRecord, conn: psycopg.Connection) -> None:
        record = attempt.model_copy(deep=True)
        workflow_run_id = self._task_workflow_run_id(conn, record.task_id)
        graph_revision = self._graph_revision_for_run(conn, workflow_run_id)
        conn.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, workflow_run_id, graph_revision, task_id, attempt_number, state, data_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET workflow_run_id = EXCLUDED.workflow_run_id,
                    graph_revision = EXCLUDED.graph_revision,
                    task_id = EXCLUDED.task_id,
                    attempt_number = EXCLUDED.attempt_number,
                    state = EXCLUDED.state,
                    data_json = EXCLUDED.data_json
                """
            ).format(self._qualified("attempts")),
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

    def _save_human_request(self, request: HumanRequestRecord, conn: psycopg.Connection) -> None:
        record = request.model_copy(deep=True)
        conn.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, workflow_run_id, task_id, status, data_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET workflow_run_id = EXCLUDED.workflow_run_id,
                    task_id = EXCLUDED.task_id,
                    status = EXCLUDED.status,
                    data_json = EXCLUDED.data_json
                """
            ).format(self._qualified("human_requests")),
            (
                record.id,
                record.workflow_run_id,
                record.task_id,
                record.status.value,
                record.model_dump_json(),
            ),
        )

    def _save_approval_request(self, request: ApprovalRequestRecord, conn: psycopg.Connection) -> None:
        record = request.model_copy(deep=True)
        conn.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, workflow_run_id, task_id, status, data_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET workflow_run_id = EXCLUDED.workflow_run_id,
                    task_id = EXCLUDED.task_id,
                    status = EXCLUDED.status,
                    data_json = EXCLUDED.data_json
                """
            ).format(self._qualified("approval_requests")),
            (
                record.id,
                record.workflow_run_id,
                record.task_id,
                record.status.value,
                record.model_dump_json(),
            ),
        )


from autoweave.storage.durable import SQLiteWorkflowRepository
