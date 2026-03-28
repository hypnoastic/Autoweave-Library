from __future__ import annotations

from pathlib import Path

from autoweave.artifacts import FilesystemArtifactStore, InMemoryArtifactRegistry
from autoweave.graph import SQLiteGraphProjectionBackend
from autoweave.models import ArtifactRecord, ArtifactStatus, EventRecord, MemoryEntryRecord, MemoryLayer
from autoweave.settings import CANONICAL_VERTEX_CREDENTIALS, LocalEnvironmentSettings
from autoweave.storage import SQLiteWorkflowRepository, build_local_storage_wiring
from autoweave.storage.wiring import resolve_artifact_root


def _seed_repo(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "autoweave_high_level_architecture.md").write_text("# arch\n", encoding="utf-8")
    (root / "docs" / "autoweave_implementation_spec.md").write_text("# spec\n", encoding="utf-8")
    (root / "docs" / "autoweave_diagrams_source.md").write_text("# diagrams\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='autoweave'\nversion='0.0.0'\n", encoding="utf-8")


def _write_env(root: Path) -> None:
    (root / ".env").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=base-project",
                "VERTEXAI_LOCATION=us-east1",
                "VERTEXAI_SERVICE_ACCOUNT_FILE=./vertex-source.json",
                "POSTGRES_URL=postgresql://user@ep-round-wildflower-am4ugjfn-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require",
                "REDIS_URL=redis://127.0.0.1:6380/2",
                "NEO4J_URL=neo4j+s://demo.databases.neo4j.io",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=local-project",
                "VERTEXAI_LOCATION=global",
                "VERTEXAI_SERVICE_ACCOUNT_FILE=./config/secrets/vertex_service_account.json",
                "GOOGLE_APPLICATION_CREDENTIALS=./config/secrets/vertex_service_account.json",
                "ARTIFACT_STORE_URL=file://./var/artifacts",
                "OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "vertex-source.json").write_text("{}", encoding="utf-8")


def _artifact(
    *,
    workflow_run_id: str,
    task_id: str,
    task_attempt_id: str,
    title: str,
    summary: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        produced_by_role="backend",
        artifact_type="contract",
        title=title,
        summary=summary,
        status=ArtifactStatus.FINAL,
        storage_uri="",
        checksum="sha-1",
    )


def test_local_environment_settings_and_targets_are_normalized(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    _write_env(tmp_path)

    settings = LocalEnvironmentSettings.load(root=tmp_path)

    assert settings.vertexai_project == "local-project"
    assert settings.vertexai_location == "global"
    assert settings.vertex_service_account_file == (tmp_path / CANONICAL_VERTEX_CREDENTIALS).resolve()
    assert settings.google_application_credentials == (tmp_path / CANONICAL_VERTEX_CREDENTIALS).resolve()
    assert settings.postgres_target().uses_neon is True
    assert settings.neo4j_target().uses_aura is True
    assert settings.openhands_target().health_url.endswith("/health")


def test_filesystem_artifact_store_persists_payloads_to_local_path(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    artifact = _artifact(
        workflow_run_id="run-1",
        task_id="task-1",
        task_attempt_id="attempt-1",
        title="Contract",
        summary="artifact payload",
    )

    handle = store.write(artifact)

    assert handle.storage_uri.startswith("file://")
    manifest = store.read_manifest(artifact.id)
    assert manifest["artifact"]["title"] == "Contract"
    assert manifest["payload"] == "artifact payload"
    assert Path(manifest["manifest_path"]).exists()
    assert Path(manifest["payload_path"]).exists()


def test_storage_bundle_wires_connection_targets_and_redis_keys(tmp_path: Path) -> None:
    settings = LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)
    settings = settings.model_copy(
        update={
            "artifact_store_url": (tmp_path / "artifacts").resolve().as_uri(),
            "autoweave_canonical_backend": "sqlite",
            "autoweave_graph_backend": "sqlite",
            "autoweave_state_dir": (tmp_path / "state").resolve(),
        }
    )

    bundle = build_local_storage_wiring(settings)

    assert isinstance(bundle.workflow_repository, SQLiteWorkflowRepository)
    assert isinstance(bundle.graph_projection, SQLiteGraphProjectionBackend)
    assert bundle.targets.postgres.uses_neon is True
    assert bundle.targets.neo4j.uses_aura is True
    assert bundle.targets.artifact_root == (tmp_path / "artifacts").resolve()
    assert bundle.redis_wire.lease_key("attempt-1") == "lease:attempt:attempt-1"
    assert bundle.redis_wire.dispatch_key("run-1") == "dispatch:workflow:run-1"
    assert bundle.settings.worker_environment()["GOOGLE_APPLICATION_CREDENTIALS"] == str(
        settings.vertex_service_account_file
    )
    if hasattr(bundle.workflow_repository, "close"):
        bundle.workflow_repository.close()
    if hasattr(bundle.graph_projection, "close"):
        bundle.graph_projection.close()


def test_artifact_root_resolution_handles_absolute_file_uris(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    _write_env(tmp_path)
    settings = LocalEnvironmentSettings.load(root=tmp_path)
    absolute_root = tmp_path / "absolute-artifacts"
    settings = settings.model_copy(update={"artifact_store_url": absolute_root.as_uri()})

    assert resolve_artifact_root(settings) == absolute_root.resolve()


def test_registry_uses_filesystem_storage_without_changing_canonical_truth(tmp_path: Path) -> None:
    settings = LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)
    settings = settings.model_copy(
        update={
            "artifact_store_url": (tmp_path / "artifacts").resolve().as_uri(),
            "autoweave_canonical_backend": "sqlite",
            "autoweave_graph_backend": "sqlite",
            "autoweave_state_dir": (tmp_path / "state").resolve(),
        }
    )
    bundle = build_local_storage_wiring(settings)

    repo = bundle.workflow_repository
    graph = _example_graph(repo)
    repo.save_graph(graph)

    artifact = bundle.artifact_registry.put_artifact(
        _artifact(
            workflow_run_id=graph.workflow_run.id,
            task_id=graph.tasks[1].id,
            task_attempt_id="attempt-1",
            title="Backend contract",
            summary="final backend contract",
        )
    )

    manifest = bundle.artifact_store.read_manifest(artifact.id)
    assert artifact.storage_uri.startswith("file://")
    assert manifest["payload"] == "final backend contract"

    bundle.graph_projection.project_event(
        EventRecord(
            workflow_run_id=graph.workflow_run.id,
            event_type="graph.disagreement",
            source="neo4j",
            payload_json={
                "entity_id": graph.tasks[1].id,
                "entity_type": "Task",
                "relation": "DEPENDS_ON",
                "target_id": "conflicting-task",
            },
        )
    )

    canonical_graph = repo.get_graph(graph.workflow_run.id)
    assert canonical_graph.workflow_run.id == graph.workflow_run.id
    assert repo.get_task_by_key(graph.workflow_run.id, "backend_contract").task_key == "backend_contract"
    bundle.graph_projection.clear_namespace()
    if hasattr(bundle.workflow_repository, "close"):
        bundle.workflow_repository.close()
    if hasattr(bundle.graph_projection, "close"):
        bundle.graph_projection.close()


def test_context_service_returns_typed_miss_when_task_missing(tmp_path: Path) -> None:
    settings = LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)
    settings = settings.model_copy(
        update={
            "artifact_store_url": (tmp_path / "artifacts").resolve().as_uri(),
            "autoweave_canonical_backend": "sqlite",
            "autoweave_graph_backend": "sqlite",
            "autoweave_state_dir": (tmp_path / "state").resolve(),
        }
    )
    bundle = build_local_storage_wiring(settings)

    lookup = bundle.context_service.lookup_task("missing-task")
    assert lookup.found is False
    assert lookup.miss is not None
    assert lookup.miss.reason.value == "not_found"
    if hasattr(bundle.workflow_repository, "close"):
        bundle.workflow_repository.close()
    if hasattr(bundle.graph_projection, "close"):
        bundle.graph_projection.close()


def test_sqlite_repository_delete_workflow_run_cleans_memory_and_canonical_rows(tmp_path: Path) -> None:
    settings = LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)
    settings = settings.model_copy(
        update={
            "artifact_store_url": (tmp_path / "artifacts").resolve().as_uri(),
            "autoweave_canonical_backend": "sqlite",
            "autoweave_graph_backend": "sqlite",
            "autoweave_state_dir": (tmp_path / "state").resolve(),
        }
    )
    bundle = build_local_storage_wiring(settings)
    repo = bundle.workflow_repository
    graph = _example_graph(repo)
    repo.save_graph(graph)
    repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="workflow_run",
            scope_id=graph.workflow_run.id,
            memory_layer=MemoryLayer.EPISODIC,
            content="cleanup me",
        )
    )
    repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="project",
            scope_id=graph.workflow_run.project_id,
            memory_layer=MemoryLayer.SEMANTIC,
            content="cleanup project memory",
            metadata_json={
                "workflow_run_id": graph.workflow_run.id,
                "task_id": graph.tasks[0].id,
            },
        )
    )
    unrelated_memory = repo.save_memory_entry(
        MemoryEntryRecord(
            project_id=graph.workflow_run.project_id,
            scope_type="project",
            scope_id=graph.workflow_run.project_id,
            memory_layer=MemoryLayer.SEMANTIC,
            content="keep project memory",
            metadata_json={"workflow_run_id": "run-other", "task_id": "task-other"},
        )
    )

    assert repo.delete_workflow_run(graph.workflow_run.id) is True
    assert repo.list_workflow_runs() == []
    assert repo.list_memory_entries("workflow_run", graph.workflow_run.id) == []
    assert [entry.id for entry in repo.list_memory_entries("project", graph.workflow_run.project_id)] == [unrelated_memory.id]
    if hasattr(bundle.workflow_repository, "close"):
        bundle.workflow_repository.close()
    if hasattr(bundle.graph_projection, "close"):
        bundle.graph_projection.close()


def _example_graph(repo):
    from autoweave.models import TaskEdgeRecord, TaskRecord, TaskState, WorkflowGraph, WorkflowRunRecord

    workflow_run = WorkflowRunRecord(
        id="run-1",
        project_id="project-1",
        team_id="team-1",
        workflow_definition_id="workflow-1",
    )
    manager_plan = TaskRecord(
        id="task-manager",
        workflow_run_id=workflow_run.id,
        task_key="manager_plan",
        title="Manager plan",
        description="Plan work",
        assigned_role="manager",
        state=TaskState.READY,
    )
    backend_contract = TaskRecord(
        id="task-backend-contract",
        workflow_run_id=workflow_run.id,
        task_key="backend_contract",
        title="Backend contract",
        description="Define backend contract",
        assigned_role="backend",
        state=TaskState.READY,
    )
    review = TaskRecord(
        id="task-review",
        workflow_run_id=workflow_run.id,
        task_key="review",
        title="Review",
        description="Review changes",
        assigned_role="reviewer",
        state=TaskState.WAITING_FOR_DEPENDENCY,
    )
    graph = WorkflowGraph(
        workflow_run=workflow_run,
        tasks=[manager_plan, backend_contract, review],
        edges=[
            TaskEdgeRecord(
                workflow_run_id=workflow_run.id,
                from_task_id=manager_plan.id,
                to_task_id=backend_contract.id,
            ),
            TaskEdgeRecord(
                workflow_run_id=workflow_run.id,
                from_task_id=backend_contract.id,
                to_task_id=review.id,
            ),
        ],
    )
    return graph
