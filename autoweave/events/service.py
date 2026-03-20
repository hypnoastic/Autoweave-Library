"""Event publication and normalization service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from autoweave.events.redaction import redact_payload
from autoweave.events.schema import EventCorrelationContext, make_event, normalize_event
from autoweave.events.stream import EventStore, InMemoryEventStore, LiveEventStream
from autoweave.models import EventRecord, ModelRouteRecord


class MetricsSink(Protocol):
    def increment(self, name: str, value: float = 1.0, *, labels: dict[str, str] | None = None) -> None: ...

    def gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None: ...

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None: ...


class Tracer(Protocol):
    def span(self, name: str, *, attributes: dict[str, Any] | None = None): ...


class DebugArtifactStore(Protocol):
    def put(self, artifact: Any) -> Any: ...

    def list_for_run(self, workflow_run_id: str) -> list[Any]: ...


class EventService:
    """Normalizes, redacts, stores, and exports AutoWeave events."""

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        metrics: MetricsSink | None = None,
        tracer: Tracer | None = None,
        debug_store: DebugArtifactStore | None = None,
    ) -> None:
        self.store = store or InMemoryEventStore()
        self.metrics = metrics
        self.tracer = tracer
        self.debug_store = debug_store
        self.stream = LiveEventStream(self.store)

    def publish(
        self,
        event: EventRecord | Mapping[str, Any],
        *,
        correlation: EventCorrelationContext | Mapping[str, Any] | None = None,
        redact: bool = True,
    ) -> EventRecord:
        normalized = normalize_event(event, correlation=correlation)
        if redact:
            normalized = normalized.model_copy(
                update={"payload_json": redact_payload(normalized.payload_json)}
            )

        span = self.tracer.span(
            "autoweave.event.publish",
            attributes={
                "event_type": normalized.event_type,
                "source": normalized.source,
                "workflow_run_id": normalized.workflow_run_id,
            },
        ) if self.tracer is not None else None

        if span is not None:
            with span:
                stored = self.store.append(normalized)
        else:
            stored = self.store.append(normalized)

        if self.metrics is not None:
            self.metrics.increment(
                "autoweave.event.published",
                labels={
                    "event_type": stored.event_type,
                    "source": stored.source,
                },
            )

        return stored

    def publish_route(self, route: ModelRouteRecord) -> EventRecord:
        event = make_event(
            workflow_run_id=route.workflow_run_id,
            task_id=route.task_id,
            task_attempt_id=route.task_attempt_id,
            provider_name=route.provider_name,
            model_name=route.model_name,
            route_reason=route.route_reason,
            event_type="route.selected",
            source="routing",
            payload_json={
                "fallback_from": route.fallback_from,
                "estimated_cost_class": route.estimated_cost_class,
            },
        )
        return self.publish(event)

    def record_debug_artifact(self, artifact: Any) -> Any:
        if self.debug_store is None:
            raise RuntimeError("debug artifact store is not configured")
        return self.debug_store.put(artifact)

    def replay(self, workflow_run_id: str, *, cursor: Any | None = None) -> list[EventRecord]:
        return self.stream.replay(workflow_run_id, cursor=cursor)

