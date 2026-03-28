from __future__ import annotations

from pathlib import Path

from autoweave.celery_queue import CeleryWorkflowDispatcher
from autoweave.config_models import RuntimeConfig
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
