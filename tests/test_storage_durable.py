from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("psycopg")
import psycopg
pytest.importorskip("neo4j")

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOWEAVE_RUN_LIVE_BACKEND_TESTS") != "1",
    reason="live backend tests are disabled by default",
)

from autoweave.artifacts import FilesystemArtifactStore, InMemoryArtifactRegistry
from autoweave.context import InMemoryContextService
from autoweave.graph import Neo4jGraphProjectionBackend
from autoweave.memory import InMemoryMemoryStore
from autoweave.models import (
    ApprovalRequestRecord,
    ArtifactRecord,
    ArtifactStatus,
    AttemptState,
    DecisionRecord,
    EventRecord,
    HumanRequestRecord,
    HumanRequestType,
    MemoryEntryRecord,
    MemoryLayer,
    MissingContextReason,
    WorkflowDefinitionRecord,
    TaskAttemptRecord,
    TaskEdgeRecord,
    TaskRecord,
    TaskState,
    WorkflowGraph,
    WorkflowRunRecord,
)
from autoweave.settings import LocalEnvironmentSettings
from autoweave.storage import PostgresWorkflowRepository, RedisIdempotencyStore, RedisLeaseManager


@dataclass
class MutableClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class FakeRedisClient:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.store: dict[str, tuple[str, datetime | None]] = {}

    def _purge(self) -> None:
        expired = [key for key, (_, expires_at) in self.store.items() if expires_at is not None and expires_at <= self.clock.now()]
        for key in expired:
            self.store.pop(key, None)

    def set(self, key: str, value: str, *, nx: bool = False, xx: bool = False, ex: int | None = None, px: int | None = None) -> bool:
        self._purge()
        exists = key in self.store
        if nx and exists:
            return False
        if xx and not exists:
            return False
        ttl = ex if ex is not None else (px / 1000 if px is not None else None)
        expires_at = self.clock.now() + timedelta(seconds=float(ttl)) if ttl is not None else None
        self.store[key] = (value, expires_at)
        return True

    def get(self, key: str) -> str | None:
        self._purge()
        record = self.store.get(key)
        return None if record is None else record[0]

    def expire(self, key: str, ttl_seconds: int) -> bool:
        self._purge()
        record = self.store.get(key)
        if record is None:
            return False
        self.store[key] = (record[0], self.clock.now() + timedelta(seconds=ttl_seconds))
        return True

    def delete(self, key: str) -> int:
        self._purge()
        return int(self.store.pop(key, None) is not None)


@pytest.fixture(scope="module")
def live_settings() -> LocalEnvironmentSettings:
    return LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)


@pytest.fixture
def postgres_repo(live_settings: LocalEnvironmentSettings):
    schema = f"aw_test_{uuid4().hex}"
    repo = PostgresWorkflowRepository(live_settings.postgres_url, schema=schema)
    try:
        yield repo
    finally:
        with psycopg.connect(live_settings.postgres_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture
def neo4j_backend(live_settings: LocalEnvironmentSettings):
    backend = Neo4jGraphProjectionBackend(live_settings.neo4j_target(), namespace=f"aw_test_{uuid4().hex}")
    try:
        yield backend
    finally:
        backend.clear_namespace()
        backend.close()


def _graph(run_id: str = "run-1") -> WorkflowGraph:
    workflow_run = WorkflowRunRecord(
        id=run_id,
        project_id="proj-1",
        team_id="team-1",
        workflow_definition_id="workflow-1",
        graph_revision=1,
    )
    manager = TaskRecord(
        id=f"{run_id}-manager",
        workflow_run_id=run_id,
        task_key="manager_plan",
        title="Manager plan",
        description="Plan work",
        assigned_role="manager",
        state=TaskState.READY,
    )
    backend_contract = TaskRecord(
        id=f"{run_id}-backend-contract",
        workflow_run_id=run_id,
        task_key="backend_contract",
        title="Backend contract",
        description="Define backend contract",
        assigned_role="backend",
        state=TaskState.READY,
    )
    backend_impl = TaskRecord(
        id=f"{run_id}-backend-impl",
        workflow_run_id=run_id,
        task_key="backend_impl",
        title="Backend impl",
        description="Implement backend",
        assigned_role="backend",
        state=TaskState.READY,
    )
    frontend_ui = TaskRecord(
        id=f"{run_id}-frontend-ui",
        workflow_run_id=run_id,
        task_key="frontend_ui",
        title="Frontend UI",
        description="Build UI",
        assigned_role="frontend",
        state=TaskState.READY,
    )
    integration = TaskRecord(
        id=f"{run_id}-integration",
        workflow_run_id=run_id,
        task_key="integration",
        title="Integration",
        description="Integrate backend and frontend",
        assigned_role="integration",
        state=TaskState.WAITING_FOR_DEPENDENCY,
    )
    review = TaskRecord(
        id=f"{run_id}-review",
        workflow_run_id=run_id,
        task_key="review",
        title="Review",
        description="Review the result",
        assigned_role="reviewer",
        state=TaskState.WAITING_FOR_DEPENDENCY,
    )
    return WorkflowGraph(
        workflow_run=workflow_run,
        tasks=[manager, backend_contract, backend_impl, frontend_ui, integration, review],
        edges=[
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=manager.id, to_task_id=backend_contract.id),
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=backend_contract.id, to_task_id=backend_impl.id),
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=manager.id, to_task_id=frontend_ui.id),
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=backend_impl.id, to_task_id=integration.id),
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=frontend_ui.id, to_task_id=integration.id),
            TaskEdgeRecord(workflow_run_id=run_id, from_task_id=integration.id, to_task_id=review.id),
        ],
    )


def _artifact(
    *,
    workflow_run_id: str,
    task_id: str,
    task_attempt_id: str,
    artifact_type: str,
    title: str,
    summary: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        produced_by_role="backend",
        artifact_type=artifact_type,
        title=title,
        summary=summary,
        status=ArtifactStatus.FINAL,
        storage_uri="",
        checksum="sha-1",
    )


def test_postgres_repository_persists_canonical_state_across_reopen(
    postgres_repo: PostgresWorkflowRepository, live_settings: LocalEnvironmentSettings
) -> None:
    repo = postgres_repo
    workflow_definition = repo.save_workflow_definition(
        WorkflowDefinitionRecord(
            project_id="proj-1",
            version="1.0.0",
            content_yaml="name: notifications",
            checksum="sha-workflow",
        )
    )
    graph = _graph()
    repo.save_graph(graph)

    attempt = TaskAttemptRecord(task_id=graph.tasks[2].id, attempt_number=1, agent_definition_id="agent-backend")
    repo.save_attempt(attempt)
    repo.update_attempt_state(attempt.id, AttemptState.DISPATCHING)
    repo.update_attempt_state(attempt.id, AttemptState.RUNNING)

    human_request = HumanRequestRecord(
        workflow_run_id=graph.workflow_run.id,
        task_id=graph.tasks[4].id,
        task_attempt_id=attempt.id,
        request_type=HumanRequestType.CLARIFICATION,
        question="Need approval on the API contract?",
        context_summary="Blocked on contract ambiguity",
    )
    repo.save_human_request(human_request)

    approval_request = ApprovalRequestRecord(
        workflow_run_id=graph.workflow_run.id,
        task_id=graph.tasks[5].id,
        task_attempt_id=attempt.id,
        approval_type="merge",
        reason="Need approval for the review step",
    )
    repo.save_approval_request(approval_request)

    event = repo.append_event(
        EventRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[2].id,
            task_attempt_id=attempt.id,
            event_type="attempt.running",
            source="orchestrator",
            payload_json={"status": "running"},
        )
    )

    artifact = repo.save_artifact(
        _artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[1].id,
            task_attempt_id=attempt.id,
            artifact_type="contract",
            title="Backend contract",
            summary="initial contract",
        )
    )

    decision = repo.save_decision(
        DecisionRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[2].id,
            task_attempt_id=attempt.id,
            title="Route selection",
            decision_text="Use vertex_ai/gemini-2.5-pro",
            rationale="balanced route",
        )
    )

    memory_entry = repo.save_memory_entry(
        MemoryEntryRecord(
            project_id="proj-1",
            scope_type="project",
            scope_id="proj-1",
            memory_layer=MemoryLayer.SEMANTIC,
            content="backend contract includes notifications settings endpoints",
            metadata_json={"source": "tests"},
        )
    )

    graph_v2 = graph.model_copy(
        update={
            "workflow_run": graph.workflow_run.model_copy(update={"graph_revision": 2}),
            "tasks": [
                task.model_copy(update={"title": "Backend contract updated"}) if task.task_key == "backend_contract" else task
                for task in graph.tasks
            ],
        }
    )
    repo.save_graph(graph_v2)

    reopened = PostgresWorkflowRepository(live_settings.postgres_url, schema=repo.schema)
    assert reopened.get_workflow_definition(workflow_definition.id).checksum == workflow_definition.checksum
    loaded_graph = reopened.get_graph(graph.workflow_run.id)
    assert loaded_graph.workflow_run.graph_revision == 2
    assert reopened.get_task_by_key(graph.workflow_run.id, "backend_contract").title == "Backend contract updated"
    assert reopened.get_attempt(attempt.id).state == AttemptState.RUNNING
    assert reopened.list_active_attempts(graph.workflow_run.id)[0].id == attempt.id
    assert reopened.get_human_request(human_request.id).question == human_request.question
    assert reopened.get_approval_request(approval_request.id).reason == approval_request.reason
    assert reopened.list_events(graph.workflow_run.id)[0].sequence_no == event.sequence_no
    assert reopened.get_artifact(artifact.id).summary == artifact.summary
    assert reopened.get_decision(decision.id).decision_text == decision.decision_text
    assert reopened.search_memory("backend contract", "project:proj-1", 5)[0].content == memory_entry.content
    assert graph.tasks[5].id in reopened.dependent_task_ids(graph.tasks[0].id)
    assert graph.tasks[0].id in reopened.upstream_task_ids(graph.tasks[5].id)
    if hasattr(reopened, "close"):
        reopened.close()


def test_postgres_repository_delete_workflow_run_removes_canonical_rows(
    postgres_repo: PostgresWorkflowRepository,
) -> None:
    repo = postgres_repo
    graph = _graph("run-delete")
    repo.save_graph(graph)
    attempt = repo.save_attempt(
        TaskAttemptRecord(task_id=graph.tasks[1].id, attempt_number=1, agent_definition_id="agent-backend")
    )
    repo.save_human_request(
        HumanRequestRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[4].id,
            task_attempt_id=attempt.id,
            request_type=HumanRequestType.CLARIFICATION,
            question="Need clarification?",
            context_summary="cleanup test",
        )
    )
    repo.save_approval_request(
        ApprovalRequestRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[5].id,
            task_attempt_id=attempt.id,
            approval_type="merge",
            reason="cleanup test",
        )
    )
    repo.append_event(
        EventRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[1].id,
            task_attempt_id=attempt.id,
            event_type="task.started",
            source="worker",
        )
    )
    repo.save_artifact(
        _artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[1].id,
            task_attempt_id=attempt.id,
            artifact_type="contract",
            title="Backend contract",
            summary="cleanup me",
        )
    )
    repo.save_decision(
        DecisionRecord(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[1].id,
            task_attempt_id=attempt.id,
            title="Cleanup",
            decision_text="delete run",
            rationale="exercise purge path",
        )
    )
    repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="workflow_run",
            scope_id=graph.workflow_run.id,
            memory_layer=MemoryLayer.EPISODIC,
            content="transient demo memory",
        )
    )
    repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="project",
            scope_id=graph.workflow_run.project_id,
            memory_layer=MemoryLayer.SEMANTIC,
            content="cleanup me too",
            metadata_json={
                "workflow_run_id": graph.workflow_run.id,
                "task_id": graph.tasks[1].id,
            },
        )
    )
    unrelated_memory = repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="project",
            scope_id=graph.workflow_run.project_id,
            memory_layer=MemoryLayer.SEMANTIC,
            content="keep me",
            metadata_json={
                "workflow_run_id": "run-unrelated",
                "task_id": "task-unrelated",
            },
        )
    )

    assert repo.delete_workflow_run(graph.workflow_run.id) is True
    assert repo.list_workflow_runs() == []
    assert repo.list_attempts_for_run(graph.workflow_run.id) == []
    assert repo.list_human_requests_for_run(graph.workflow_run.id) == []
    assert repo.list_approval_requests_for_run(graph.workflow_run.id) == []
    assert repo.list_events(graph.workflow_run.id) == []
    assert repo.list_artifacts_for_run(graph.workflow_run.id) == []
    assert repo.list_memory_entries("workflow_run", graph.workflow_run.id) == []
    assert [entry.id for entry in repo.list_memory_entries("project", graph.workflow_run.project_id)] == [unrelated_memory.id]
    assert repo.delete_workflow_run(graph.workflow_run.id) is False


def test_artifact_registry_persists_visibility_and_supersession(
    postgres_repo: PostgresWorkflowRepository, tmp_path: Path, live_settings: LocalEnvironmentSettings
) -> None:
    repo = postgres_repo
    graph = _graph("run-2")
    repo.save_graph(graph)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    registry = InMemoryArtifactRegistry(repo, payload_store=store)

    upstream_task = graph.tasks[1]
    downstream_task = graph.tasks[4]
    first = registry.put_artifact(
        _artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=upstream_task.id,
            task_attempt_id="attempt-1",
            artifact_type="contract",
            title="Backend contract",
            summary="first contract",
        )
    )
    second = registry.put_artifact(
        _artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=upstream_task.id,
            task_attempt_id="attempt-2",
            artifact_type="contract",
            title="Backend contract",
            summary="updated contract",
        )
    )

    reopened_repo = PostgresWorkflowRepository(live_settings.postgres_url, schema=repo.schema)
    reopened_registry = InMemoryArtifactRegistry(reopened_repo, payload_store=store)
    visible = reopened_registry.get_upstream_artifacts(task_id=downstream_task.id, artifact_type="contract")

    assert {artifact.id for artifact in visible} == {second.id}
    assert reopened_repo.get_artifact(first.id).status == ArtifactStatus.SUPERSEDED
    assert store.read_manifest(second.id)["payload"] == "updated contract"
    if hasattr(reopened_repo, "close"):
        reopened_repo.close()


def test_redis_backed_coordination_manages_leases_and_idempotency() -> None:
    clock = MutableClock(datetime.now(tz=UTC))
    client = FakeRedisClient(clock)
    leases = RedisLeaseManager(client=client)
    idempotency = RedisIdempotencyStore(client=client)

    assert leases.acquire("lease:attempt-1", 5) is True
    assert leases.acquire("lease:attempt-1", 5) is False
    current = leases.get("lease:attempt-1")
    assert current is not None

    clock.advance(2)
    leases.heartbeat("lease:attempt-1", 10)
    refreshed = leases.get("lease:attempt-1")
    assert refreshed is not None
    assert refreshed.expires_at > current.expires_at

    assert idempotency.claim("dispatch:attempt-1", 5, value={"attempt": "attempt-1"}) is True
    assert idempotency.claim("dispatch:attempt-1", 5, value={"attempt": "attempt-1"}) is False
    record = idempotency.get("dispatch:attempt-1")
    assert record is not None
    assert record.value == {"attempt": "attempt-1"}

    leases.release("lease:attempt-1")
    assert leases.get("lease:attempt-1") is None


def test_graph_projection_persists_projections_across_restart(
    postgres_repo: PostgresWorkflowRepository,
    neo4j_backend: Neo4jGraphProjectionBackend,
    live_settings: LocalEnvironmentSettings,
) -> None:
    projection = neo4j_backend
    repo = postgres_repo
    graph = _graph("run-3")
    repo.save_graph(graph)
    before = repo.snapshot(graph.workflow_run.id)
    event = EventRecord(
        workflow_run_id=graph.workflow_run.id,
        task_id=graph.tasks[1].id,
        task_attempt_id="attempt-1",
        event_type="graph.projected",
        source="orchestrator",
        payload_json={
            "entity_id": graph.tasks[1].id,
            "entity_type": "Task",
            "relation": "DEPENDS_ON",
            "target_id": graph.tasks[2].id,
            "label": graph.tasks[1].task_key,
        },
    )
    projection.project_event(event)
    after = repo.snapshot(graph.workflow_run.id)

    reopened = Neo4jGraphProjectionBackend(live_settings.neo4j_target(), namespace=projection.namespace)
    related = reopened.query_related_entities(graph.tasks[1].id)
    assert related == [
        {
            "source_id": graph.tasks[1].id,
            "relation": "DEPENDS_ON",
            "target_id": graph.tasks[2].id,
            "event_id": event.id,
        }
    ]
    assert reopened.list_events()[0].event_type == "graph.projected"
    assert after == before
    reopened.clear_namespace()
    if hasattr(reopened, "close"):
        reopened.close()


def test_context_service_uses_durable_memory_search_when_available(
    postgres_repo: PostgresWorkflowRepository, tmp_path: Path
) -> None:
    repo = postgres_repo
    repo.save_graph(_graph("run-4"))
    repo.save_memory_entry(
        MemoryEntryRecord(
            project_id="proj-1",
            scope_type="project",
            scope_id="proj-1",
            memory_layer=MemoryLayer.SEMANTIC,
            content="notifications settings page backend contract",
            metadata_json={"source": "repo"},
        )
    )

    context = InMemoryContextService(
        workflow_repository=repo,
        artifact_registry=InMemoryArtifactRegistry(repo, payload_store=FilesystemArtifactStore(tmp_path / "artifacts")),
        memory_store=InMemoryMemoryStore(),
    )

    assert context.search_memory("notifications backend", "project:proj-1", 5) == [
        "notifications settings page backend contract"
    ]


def test_context_service_returns_typed_miss_when_postgres_memory_absent(
    postgres_repo: PostgresWorkflowRepository, tmp_path: Path
) -> None:
    repo = postgres_repo
    repo.save_graph(_graph("run-5"))

    context = InMemoryContextService(
        workflow_repository=repo,
        artifact_registry=InMemoryArtifactRegistry(repo, payload_store=FilesystemArtifactStore(tmp_path / "artifacts")),
        memory_store=InMemoryMemoryStore(),
    )

    lookup = context.lookup_memory("missing context", "project:proj-1", 5)
    assert not lookup.found
    assert lookup.miss is not None
    assert lookup.miss.reason == MissingContextReason.NOT_INDEXED_YET
