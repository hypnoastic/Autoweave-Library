from __future__ import annotations

import json
from pathlib import Path

from autoweave.events import EventCursor, make_event
from autoweave.observability import LocalObservabilityService
from autoweave.settings import CANONICAL_VERTEX_CREDENTIALS, LocalEnvironmentSettings


def _seed_repo(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "autoweave_high_level_architecture.md").write_text("# arch\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='autoweave'\nversion='0.0.0'\n", encoding="utf-8")
    (root / "vertex-source.json").write_text("{}", encoding="utf-8")


def _settings(root: Path) -> LocalEnvironmentSettings:
    _seed_repo(root)
    (root / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=demo-project",
                "VERTEXAI_LOCATION=us-central1",
                "POSTGRES_URL=postgresql://user@host/db",
                "NEO4J_URL=neo4j+s://demo.databases.neo4j.io",
                "REDIS_URL=redis://127.0.0.1:6379/0",
                "ARTIFACT_STORE_URL=file://./var/artifacts",
                "OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = LocalEnvironmentSettings.load(root=root)
    assert settings.vertex_service_account_file == (root / CANONICAL_VERTEX_CREDENTIALS).resolve()
    return settings


def test_local_observability_persists_jsonl_events_metrics_traces_and_debug_artifacts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = LocalObservabilityService.from_settings(settings)

    event = service.publish(
        make_event(
            workflow_run_id="run_1",
            task_id="task_1",
            event_type="artifact.published",
            source="worker",
            payload_json={"secret_token": "should-redact", "summary": "visible"},
        )
    )
    debug_artifact = service.record_debug_artifact(
        workflow_run_id="run_1",
        task_id="task_1",
        task_attempt_id="attempt_1",
        name="local-debug",
        payload_json={"api_key": "secret", "note": "keep"},
    )

    with service.tracer.span("demo.span", attributes={"workflow_run_id": "run_1"}):
        service.metrics.increment("autoweave.local.test")

    events_path = settings.project_root / "var" / "observability" / "events.jsonl"
    metrics_path = settings.project_root / "var" / "observability" / "metrics.jsonl"
    traces_path = settings.project_root / "var" / "observability" / "traces.jsonl"
    debug_path = settings.project_root / "var" / "observability" / "debug_artifacts.jsonl"

    event_lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    metric_lines = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line]
    trace_lines = [json.loads(line) for line in traces_path.read_text(encoding="utf-8").splitlines() if line]
    debug_lines = [json.loads(line) for line in debug_path.read_text(encoding="utf-8").splitlines() if line]

    assert event.payload_json["secret_token"] == "[REDACTED]"
    assert event_lines[0]["payload_json"]["secret_token"] == "[REDACTED]"
    assert event_lines[0]["task_id"] == "task_1"
    assert metric_lines[0]["name"] == "autoweave.event.published"
    assert metric_lines[-1]["name"] == "autoweave.local.test"
    assert trace_lines[0]["name"] == "autoweave.event.publish"
    assert trace_lines[0]["attributes"]["workflow_run_id"] == "run_1"
    assert debug_lines[0]["payload_json"]["api_key"] == "[REDACTED]"
    assert debug_artifact.payload_json["api_key"] == "[REDACTED]"

    replay = service.event_store.replay_from("run_1", cursor=EventCursor(workflow_run_id="run_1", sequence_no=0))
    assert replay[0].id == event.id


def test_local_observability_replays_only_events_after_cursor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = LocalObservabilityService.from_settings(settings)

    first = service.publish(make_event(workflow_run_id="run_1", event_type="task.ready", source="scheduler"))
    second = service.publish(make_event(workflow_run_id="run_1", event_type="task.started", source="worker"))

    cursor = EventCursor(workflow_run_id="run_1", sequence_no=first.sequence_no)
    replay = service.event_store.replay_from("run_1", cursor=cursor)

    assert [event.id for event in replay] == [second.id]
    assert service.event_store.latest_cursor("run_1") is not None
