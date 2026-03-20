from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from autoweave.artifacts import ArtifactHandle, InMemoryArtifactRegistry
from autoweave.context import InMemoryContextService
from autoweave.graph import InMemoryGraphProjectionBackend
from autoweave.memory import InMemoryMemoryStore
from autoweave.models import (
    ArtifactRecord,
    ArtifactStatus,
    EventRecord,
    MemoryEntryRecord,
    MemoryLayer,
    MissingContextReason,
    TaskAttemptRecord,
    TaskEdgeRecord,
    TaskRecord,
    TaskState,
    WorkflowGraph,
    WorkflowRunRecord,
)
from autoweave.storage import InMemoryIdempotencyStore, InMemoryLeaseManager, InMemoryWorkflowRepository


@dataclass
class MutableClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def build_example_graph(run_id: str, project_id: str) -> WorkflowGraph:
    workflow_run = WorkflowRunRecord(
        id=run_id,
        project_id=project_id,
        team_id=f"team-{project_id}",
        workflow_definition_id=f"workflow-{project_id}",
    )

    tasks = {
        "manager_plan": TaskRecord(
            id=f"{run_id}-manager_plan",
            workflow_run_id=run_id,
            task_key="manager_plan",
            title="Manager plan",
            description="Create task graph",
            assigned_role="manager",
            state=TaskState.READY,
        ),
        "backend_contract": TaskRecord(
            id=f"{run_id}-backend_contract",
            workflow_run_id=run_id,
            task_key="backend_contract",
            title="Backend contract",
            description="Define backend contract",
            assigned_role="backend",
            state=TaskState.COMPLETED,
        ),
        "backend_impl": TaskRecord(
            id=f"{run_id}-backend_impl",
            workflow_run_id=run_id,
            task_key="backend_impl",
            title="Backend impl",
            description="Implement backend",
            assigned_role="backend",
            state=TaskState.READY,
        ),
        "frontend_ui": TaskRecord(
            id=f"{run_id}-frontend_ui",
            workflow_run_id=run_id,
            task_key="frontend_ui",
            title="Frontend UI",
            description="Build UI",
            assigned_role="frontend",
            state=TaskState.COMPLETED,
        ),
        "integration": TaskRecord(
            id=f"{run_id}-integration",
            workflow_run_id=run_id,
            task_key="integration",
            title="Integration",
            description="Integrate backend and frontend",
            assigned_role="integration",
            state=TaskState.READY,
        ),
        "review": TaskRecord(
            id=f"{run_id}-review",
            workflow_run_id=run_id,
            task_key="review",
            title="Review",
            description="Review the implementation",
            assigned_role="reviewer",
            state=TaskState.WAITING_FOR_DEPENDENCY,
        ),
    }

    edges = [
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["manager_plan"].id,
            to_task_id=tasks["backend_contract"].id,
        ),
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["backend_contract"].id,
            to_task_id=tasks["backend_impl"].id,
        ),
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["manager_plan"].id,
            to_task_id=tasks["frontend_ui"].id,
        ),
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["backend_impl"].id,
            to_task_id=tasks["integration"].id,
        ),
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["frontend_ui"].id,
            to_task_id=tasks["integration"].id,
        ),
        TaskEdgeRecord(
            workflow_run_id=run_id,
            from_task_id=tasks["integration"].id,
            to_task_id=tasks["review"].id,
        ),
    ]
    return WorkflowGraph(workflow_run=workflow_run, tasks=list(tasks.values()), edges=edges)


def make_artifact(
    *,
    workflow_run_id: str,
    task_id: str,
    task_attempt_id: str,
    produced_by_role: str,
    artifact_type: str,
    title: str,
    status: ArtifactStatus,
    summary: str,
    storage_uri: str,
    checksum: str,
    metadata_json: dict[str, object] | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        produced_by_role=produced_by_role,
        artifact_type=artifact_type,
        title=title,
        summary=summary,
        status=status,
        storage_uri=storage_uri,
        checksum=checksum,
        metadata_json=metadata_json or {},
    )


def make_attempt(task_id: str, agent_definition_id: str = "agent-backend") -> TaskAttemptRecord:
    return TaskAttemptRecord(task_id=task_id, attempt_number=1, agent_definition_id=agent_definition_id)


def test_artifact_visibility_scopes_to_dependency_chain_and_final_rules() -> None:
    repo = InMemoryWorkflowRepository()
    graph = build_example_graph("run-1", "proj-1")
    repo.save_graph(graph)
    registry = InMemoryArtifactRegistry(repo)

    backend_contract = graph.tasks[1]
    backend_impl = graph.tasks[2]
    frontend_ui = graph.tasks[3]
    integration = graph.tasks[4]

    contract_final = registry.put_artifact(
        make_artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=backend_contract.id,
            task_attempt_id=make_attempt(backend_contract.id).id,
            produced_by_role="backend",
            artifact_type="contract",
            title="Backend contract",
            status=ArtifactStatus.FINAL,
            summary="final contract",
            storage_uri="blob://run-1/contract-final",
            checksum="sha-final-1",
        )
    )
    registry.put_artifact(
        make_artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=backend_contract.id,
            task_attempt_id=make_attempt(backend_contract.id).id,
            produced_by_role="backend",
            artifact_type="contract",
            title="Backend contract draft",
            status=ArtifactStatus.DRAFT,
            summary="draft contract",
            storage_uri="blob://run-1/contract-draft",
            checksum="sha-draft-1",
            metadata_json={"allow_draft_visibility": True},
        )
    )
    backend_impl_final = registry.put_artifact(
        make_artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=backend_impl.id,
            task_attempt_id=make_attempt(backend_impl.id).id,
            produced_by_role="backend",
            artifact_type="implementation",
            title="Backend impl",
            status=ArtifactStatus.FINAL,
            summary="backend implementation",
            storage_uri="blob://run-1/backend-impl",
            checksum="sha-impl-1",
        )
    )
    frontend_final = registry.put_artifact(
        make_artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=frontend_ui.id,
            task_attempt_id=make_attempt(frontend_ui.id, agent_definition_id="agent-frontend").id,
            produced_by_role="frontend",
            artifact_type="ui_spec",
            title="Frontend spec",
            status=ArtifactStatus.FINAL,
            summary="frontend spec",
            storage_uri="blob://run-1/frontend-spec",
            checksum="sha-ui-1",
        )
    )
    registry.put_artifact(
        make_artifact(
            workflow_run_id="run-2",
            task_id="run-2-foreign-task",
            task_attempt_id="run-2-attempt",
            produced_by_role="backend",
            artifact_type="contract",
            title="Foreign contract",
            status=ArtifactStatus.FINAL,
            summary="foreign",
            storage_uri="blob://run-2/foreign-contract",
            checksum="sha-foreign",
        )
    )

    visible = registry.get_upstream_artifacts(task_id=integration.id)
    assert {artifact.id for artifact in visible} == {contract_final.id, backend_impl_final.id, frontend_final.id}
    assert all(artifact.status == ArtifactStatus.FINAL for artifact in visible)

    draft_visible = registry.get_upstream_artifacts(task_id=integration.id, status="draft", artifact_type="contract")
    assert {artifact.summary for artifact in draft_visible} == {"draft contract"}

    wrong_type = registry.get_upstream_artifacts(task_id=integration.id, artifact_type="review_note")
    assert wrong_type == []


def test_repository_save_attempt_is_idempotent_for_same_attempt_id() -> None:
    repo = InMemoryWorkflowRepository()
    graph = build_example_graph("run-1", "proj-1")
    repo.save_graph(graph)
    backend_impl = graph.tasks[2]
    attempt = make_attempt(backend_impl.id)

    repo.save_attempt(attempt)
    repo.save_attempt(attempt)

    active = repo.list_active_attempts(graph.workflow_run.id)
    assert [item.id for item in active] == [attempt.id]

def test_large_artifact_returns_handle_and_unrelated_workflows_are_hidden() -> None:
    repo = InMemoryWorkflowRepository()
    graph = build_example_graph("run-1", "proj-1")
    repo.save_graph(graph)
    registry = InMemoryArtifactRegistry(repo)

    backend_contract = graph.tasks[1]
    registry.put_artifact(
        make_artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=backend_contract.id,
            task_attempt_id=make_attempt(backend_contract.id).id,
            produced_by_role="backend",
            artifact_type="contract",
            title="Large contract",
            status=ArtifactStatus.FINAL,
            summary="x" * 1024,
            storage_uri="blob://run-1/large-contract",
            checksum="sha-large",
            metadata_json={"size_bytes": 1024},
        )
    )

    payload = registry.resolve_payload(next(iter(registry.get_upstream_artifacts(task_id=graph.tasks[2].id))).id, max_inline_bytes=128)
    assert isinstance(payload, ArtifactHandle)
    assert payload.size_bytes == 1024
    assert payload.storage_uri == "blob://run-1/large-contract"

    hidden = registry.get_upstream_artifacts(task_id=graph.tasks[4].id, artifact_type="contract")
    assert len(hidden) == 1


def test_typed_miss_results_are_returned_for_missing_task_and_memory() -> None:
    repo = InMemoryWorkflowRepository()
    graph = build_example_graph("run-1", "proj-1")
    repo.save_graph(graph)
    registry = InMemoryArtifactRegistry(repo)
    memory = InMemoryMemoryStore()
    context = InMemoryContextService(
        workflow_repository=repo,
        artifact_registry=registry,
        memory_store=memory,
    )

    task_lookup = context.lookup_task("missing-task")
    assert not task_lookup.found
    assert task_lookup.miss is not None
    assert task_lookup.miss.reason == MissingContextReason.NOT_FOUND

    memory_lookup = context.lookup_memory("backend", "code:global", top_k=3)
    assert not memory_lookup.found
    assert memory_lookup.miss is not None
    assert memory_lookup.miss.reason == MissingContextReason.NOT_INDEXED_YET


def test_lease_recovery_and_idempotency_claims_after_expiry() -> None:
    clock = MutableClock(datetime(2026, 3, 19, tzinfo=UTC))
    leases = InMemoryLeaseManager(clock=clock.now)
    idempotency = InMemoryIdempotencyStore(clock=clock.now)

    assert leases.acquire("attempt:1", ttl_seconds=30) is True
    assert leases.acquire("attempt:1", ttl_seconds=30) is False

    assert idempotency.claim("dispatch:attempt:1", ttl_seconds=30) is True
    assert idempotency.claim("dispatch:attempt:1", ttl_seconds=30) is False

    clock.advance(31)
    assert leases.acquire("attempt:1", ttl_seconds=30) is True
    assert idempotency.claim("dispatch:attempt:1", ttl_seconds=30) is True
    assert leases.reap_expired() == []
    assert idempotency.reap_expired() == []


def test_graph_projection_stays_downstream_of_canonical_truth() -> None:
    repo = InMemoryWorkflowRepository()
    graph = build_example_graph("run-1", "proj-1")
    repo.save_graph(graph)
    before = repo.snapshot(graph.workflow_run.id)

    projection = InMemoryGraphProjectionBackend()
    event = EventRecord(
        workflow_run_id=graph.workflow_run.id,
        task_id=graph.tasks[2].id,
        task_attempt_id=make_attempt(graph.tasks[2].id).id,
        agent_role="backend",
        event_type="artifact.published",
        source="storage",
        sequence_no=1,
        payload_json={
            "entity_id": "artifact-1",
            "entity_type": "Artifact",
            "relation": "PRODUCED_BY",
            "target_id": graph.tasks[2].id,
            "title": "Backend implementation",
        },
    )
    projection.project_event(event)
    after = repo.snapshot(graph.workflow_run.id)

    assert before == after
    assert projection.query_related_entities("artifact-1") == [
        {
            "source_id": "artifact-1",
            "relation": "PRODUCED_BY",
            "target_id": graph.tasks[2].id,
            "event_id": event.id,
        }
    ]
