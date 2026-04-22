from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autoweave.celery_queue import (
    CeleryWorkflowDispatcher,
    create_autoweave_celery_app,
    recover_workflows,
    recovery_environ,
    write_recovery_metadata,
)
from autoweave.config_models import RuntimeConfig
from autoweave.models import ApprovalStatus, HumanRequestStatus, WorkflowRunRecord
from autoweave.settings import LocalEnvironmentSettings


class _FakeInspect:
    def ping(self):
        return {}

    def stats(self):
        return {"worker@example": {"pool": {"implementation": "solo"}}}

    def active_queues(self):
        return {"worker@example": [{"name": "dispatch"}]}


class _FakeControl:
    def inspect(self, timeout: float = 0.0):
        assert timeout >= 2.5
        return _FakeInspect()


class _FakeApp:
    control = _FakeControl()


def test_worker_health_falls_back_to_stats_when_ping_is_empty() -> None:
    settings = LocalEnvironmentSettings.model_construct(
        project_root=Path("/tmp/autoweave"),
        loaded_env_files=(),
        vertexai_project="demo",
        vertexai_location="global",
        vertex_service_account_file=Path("/tmp/vertex.json"),
        google_application_credentials=Path("/tmp/vertex.json"),
        postgres_url="postgresql://demo/demo",
        redis_url="redis://127.0.0.1:6379/0",
        neo4j_url="neo4j://127.0.0.1:7687",
        neo4j_username=None,
        neo4j_password=None,
        artifact_store_url="file:///tmp/autoweave/artifacts",
        openhands_agent_server_base_url="http://127.0.0.1:8000",
        openhands_agent_server_api_key=None,
        openhands_worker_timeout_seconds=1800,
        autoweave_default_workflow=Path("configs/workflows/team.workflow.yaml"),
        autoweave_runtime_config=Path("configs/runtime/runtime.yaml"),
        autoweave_storage_config=Path("configs/runtime/storage.yaml"),
        autoweave_vertex_config=Path("configs/runtime/vertex.yaml"),
        autoweave_observability_config=Path("configs/runtime/observability.yaml"),
        autoweave_vertex_profile_override=None,
        autoweave_canonical_backend="sqlite",
        autoweave_graph_backend="sqlite",
        autoweave_postgres_schema="autoweave",
        autoweave_state_dir=Path("var/state"),
        autoweave_autonomy_level="medium",
        autoweave_max_active_attempts=4,
        autoweave_heartbeat_interval_seconds=15,
        autoweave_lease_ttl_seconds=60,
        autoweave_openhands_poll_timeout_seconds=120,
        autoweave_openhands_poll_interval_seconds=1,
    )
    dispatcher = CeleryWorkflowDispatcher(
        settings=settings,
        runtime_config=RuntimeConfig(execution_backend="celery", celery_queue_names=["dispatch"]),
        app=_FakeApp(),
    )

    health = dispatcher.worker_health()

    assert health == "ok (workers=1; queues=dispatch; subscribed_workers=1; probe=stats)"


def test_celery_app_uses_late_acknowledgement_for_workflow_recovery() -> None:
    settings = LocalEnvironmentSettings.model_construct(
        project_root=Path("/tmp/autoweave"),
        loaded_env_files=(),
        vertexai_project="demo",
        vertexai_location="global",
        vertex_service_account_file=Path("/tmp/vertex.json"),
        google_application_credentials=Path("/tmp/vertex.json"),
        postgres_url="postgresql://demo/demo",
        redis_url="redis://127.0.0.1:6379/0",
        neo4j_url="neo4j://127.0.0.1:7687",
        neo4j_username=None,
        neo4j_password=None,
        artifact_store_url="file:///tmp/autoweave/artifacts",
        openhands_agent_server_base_url="http://127.0.0.1:8000",
        openhands_agent_server_api_key=None,
        openhands_worker_timeout_seconds=1800,
        autoweave_default_workflow=Path("configs/workflows/team.workflow.yaml"),
        autoweave_runtime_config=Path("configs/runtime/runtime.yaml"),
        autoweave_storage_config=Path("configs/runtime/storage.yaml"),
        autoweave_vertex_config=Path("configs/runtime/vertex.yaml"),
        autoweave_observability_config=Path("configs/runtime/observability.yaml"),
        autoweave_vertex_profile_override=None,
        autoweave_canonical_backend="sqlite",
        autoweave_graph_backend="sqlite",
        autoweave_postgres_schema="autoweave",
        autoweave_state_dir=Path("var/state"),
        autoweave_autonomy_level="medium",
        autoweave_max_active_attempts=4,
        autoweave_heartbeat_interval_seconds=15,
        autoweave_lease_ttl_seconds=60,
        autoweave_openhands_poll_timeout_seconds=120,
        autoweave_openhands_poll_interval_seconds=1,
    )

    app = create_autoweave_celery_app(
        settings=settings,
        runtime_config=RuntimeConfig(execution_backend="celery", celery_queue_names=["dispatch"]),
    )

    assert app.conf.task_acks_late is True
    assert app.conf.task_acks_on_failure_or_timeout is False
    assert app.conf.task_reject_on_worker_lost is True


def test_recover_workflows_requeues_nonterminal_runs_without_open_human_loops(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "orbit"
    root.mkdir(parents=True, exist_ok=True)
    write_recovery_metadata(root=root, project_id="orbit_123")

    runnable_run = WorkflowRunRecord(
        id="run_requeue",
        project_id="orbit_123",
        team_id="local",
        workflow_definition_id="team:1.0",
        root_input_json={"user_request": "Resume the orbit workflow."},
        status="running",
    )
    waiting_for_human_run = WorkflowRunRecord(
        id="run_waiting_human",
        project_id="orbit_123",
        team_id="local",
        workflow_definition_id="team:1.0",
        root_input_json={"user_request": "Needs clarification first."},
        status="running",
    )
    completed_run = WorkflowRunRecord(
        id="run_done",
        project_id="orbit_123",
        team_id="local",
        workflow_definition_id="team:1.0",
        root_input_json={"user_request": "Already done."},
        status="completed",
    )

    repository = SimpleNamespace(
        list_workflow_runs=lambda: [runnable_run, waiting_for_human_run, completed_run],
        list_human_requests_for_run=lambda workflow_run_id: (
            [
                SimpleNamespace(status=HumanRequestStatus.OPEN)
            ]
            if workflow_run_id == "run_waiting_human"
            else []
        ),
        list_approval_requests_for_run=lambda workflow_run_id: (
            [
                SimpleNamespace(status=ApprovalStatus.REQUESTED)
            ]
            if workflow_run_id == "run_waiting_approval"
            else []
        ),
    )

    class _FakeRuntime:
        def __init__(self) -> None:
            self.storage = SimpleNamespace(workflow_repository=repository)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    receipts: list[dict[str, object]] = []

    def fake_build_local_runtime(*, root: Path | None = None, environ=None, project_id: str | None = None):
        assert root == tmp_path / "orbit"
        assert project_id == "orbit_123"
        assert environ["AUTOWEAVE_POSTGRES_SCHEMA"] == "autoweave_runtime"
        assert environ["AUTOWEAVE_CANONICAL_BACKEND"] == "postgres"
        assert environ["AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS"] == "300"
        assert environ["POSTGRES_URL"] == "postgresql://runtime/runtime"
        return _FakeRuntime()

    def fake_enqueue(
        self,
        *,
        action: str,
        workflow_run_id: str,
        request: str,
        dispatch: bool,
        max_steps: int,
        human_request_id=None,
        approval_request_id=None,
        approved=None,
    ):
        receipts.append(
            {
                "action": action,
                "workflow_run_id": workflow_run_id,
                "request": request,
                "dispatch": dispatch,
                "max_steps": max_steps,
            }
        )
        return SimpleNamespace(
            workflow_run_id=workflow_run_id,
            celery_task_id=f"celery-{workflow_run_id}",
            queue="dispatch",
        )

    monkeypatch.delenv("AUTOWEAVE_POSTGRES_SCHEMA", raising=False)
    monkeypatch.delenv("AUTOWEAVE_CANONICAL_BACKEND", raising=False)
    monkeypatch.setenv("RUNTIME_POSTGRES_SCHEMA", "autoweave_runtime")
    monkeypatch.setenv("RUNTIME_AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://demo/demo")
    monkeypatch.setenv("RUNTIME_POSTGRES_URL", "postgresql://runtime/runtime")
    monkeypatch.setattr("autoweave.celery_queue.build_local_runtime", fake_build_local_runtime)
    monkeypatch.setattr(CeleryWorkflowDispatcher, "enqueue_workflow_action", fake_enqueue)

    recovered = recover_workflows(root=root)

    assert [receipt["workflow_run_id"] for receipt in receipts] == ["run_requeue"]
    assert [item.workflow_run_id for item in recovered] == ["run_requeue"]


def test_recovery_environ_respects_explicit_blank_runtime_graph_env(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URL", "neo4j+s://hosted.example")
    monkeypatch.setenv("NEO4J_USERNAME", "hosted-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "hosted-pass")
    monkeypatch.setenv("RUNTIME_NEO4J_URL", "")
    monkeypatch.setenv("RUNTIME_NEO4J_USERNAME", "")
    monkeypatch.setenv("RUNTIME_NEO4J_PASSWORD", "")
    monkeypatch.delenv("AUTOWEAVE_GRAPH_BACKEND", raising=False)

    resolved = recovery_environ()

    assert resolved["NEO4J_URL"] == ""
    assert resolved["NEO4J_USERNAME"] == ""
    assert resolved["NEO4J_PASSWORD"] == ""
    assert resolved["AUTOWEAVE_GRAPH_BACKEND"] == "sqlite"


def test_recovery_environ_copies_runtime_poll_timeout_override(monkeypatch) -> None:
    monkeypatch.delenv("AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("RUNTIME_AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS", "300")

    resolved = recovery_environ()

    assert resolved["AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS"] == "300"
