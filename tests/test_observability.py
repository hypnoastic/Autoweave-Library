from __future__ import annotations

from autoweave.events import EventCursor, EventService, make_event, normalize_event
from autoweave.observability import (
    InMemoryDebugArtifactStore,
    InMemoryMetricsSink,
    InMemoryTracer,
    ObservabilityService,
)


def test_normalize_event_preserves_explicit_null_correlation_fields() -> None:
    event = normalize_event(
        {
            "workflow_run_id": "run_1",
            "event_type": "workflow.created",
            "source": "orchestrator",
            "payload_json": {"ok": True},
        }
    )

    assert event.workflow_run_id == "run_1"
    assert event.task_id is None
    assert event.task_attempt_id is None
    assert event.agent_id is None
    assert event.agent_role is None
    assert event.sandbox_id is None
    assert event.provider_name is None
    assert event.model_name is None
    assert event.route_reason is None


def test_event_service_redacts_secret_payloads_before_persistence() -> None:
    service = EventService()

    stored = service.publish(
        make_event(
            workflow_run_id="run_1",
            event_type="artifact.published",
            source="worker",
            payload_json={
                "plain_text": "keep-me",
                "service_account": {
                    "client_email": "autoweave@example.com",
                    "private_key": "super-secret-key",
                },
                "api_token": "token-123",
                "nested": [{"password": "pw-123"}],
            },
        )
    )

    assert stored.payload_json["plain_text"] == "keep-me"
    assert stored.payload_json["service_account"]["private_key"] == "[REDACTED]"
    assert stored.payload_json["api_token"] == "[REDACTED]"
    assert stored.payload_json["nested"][0]["password"] == "[REDACTED]"
    assert service.store.list_events("run_1")[0].payload_json["api_token"] == "[REDACTED]"


def test_live_event_stream_recovers_from_cursor() -> None:
    service = EventService()
    service.publish(
        make_event(workflow_run_id="run_1", event_type="task.ready", source="scheduler", sequence_no=1)
    )
    service.publish(
        make_event(workflow_run_id="run_1", event_type="task.started", source="scheduler", sequence_no=2)
    )
    service.publish(
        make_event(workflow_run_id="run_1", event_type="task.completed", source="worker", sequence_no=3)
    )

    cursor = EventCursor(workflow_run_id="run_1", sequence_no=2, event_id="event_2")
    snapshot = service.stream.snapshot("run_1", cursor=cursor)

    assert [event.sequence_no for event in snapshot.events] == [3]
    assert snapshot.cursor is not None
    assert snapshot.cursor.workflow_run_id == "run_1"
    assert snapshot.cursor.sequence_no == 3


def test_observability_service_records_metrics_traces_and_separate_debug_artifacts() -> None:
    metrics = InMemoryMetricsSink()
    tracer = InMemoryTracer()
    debug_store = InMemoryDebugArtifactStore()
    observability = ObservabilityService(metrics=metrics, tracer=tracer, debug_store=debug_store)

    observability.publish(
        make_event(
            workflow_run_id="run_1",
            event_type="route.selected",
            source="routing",
            payload_json={"route": "vertex_ai/gemini-2.5"},
        )
    )
    debug_artifact = observability.record_debug_artifact(
        workflow_run_id="run_1",
        task_id="task_1",
        task_attempt_id="attempt_1",
        name="worker-dump",
        payload_json={
            "api_key": "should-not-leak",
            "context": "debug only",
        },
    )

    assert len(metrics.samples) == 1
    assert metrics.samples[0].name == "autoweave.event.published"
    assert metrics.samples[0].labels["event_type"] == "route.selected"
    assert len(tracer.spans) == 1
    assert tracer.spans[0].name == "autoweave.event.publish"
    assert tracer.spans[0].attributes["workflow_run_id"] == "run_1"
    assert len(observability.event_service.store.list_events("run_1")) == 1
    assert len(debug_store.list_for_run("run_1")) == 1
    assert debug_artifact.payload_json["api_key"] == "[REDACTED]"
    assert debug_store.list_for_run("run_1")[0].payload_json["api_key"] == "[REDACTED]"

