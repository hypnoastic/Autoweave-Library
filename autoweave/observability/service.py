"""High-level observability orchestration helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autoweave.events.schema import EventCorrelationContext
from autoweave.events.service import EventService
from autoweave.models import EventRecord
from autoweave.observability.debug import DebugArtifactRecord, InMemoryDebugArtifactStore
from autoweave.observability.metrics import InMemoryMetricsSink
from autoweave.observability.tracing import InMemoryTracer


class ObservabilityService:
    """Convenience composition layer for events, metrics, traces, and debug artifacts."""

    def __init__(
        self,
        *,
        event_service: EventService | None = None,
        metrics: InMemoryMetricsSink | None = None,
        tracer: InMemoryTracer | None = None,
        debug_store: InMemoryDebugArtifactStore | None = None,
    ) -> None:
        self.metrics = metrics or InMemoryMetricsSink()
        self.tracer = tracer or InMemoryTracer()
        self.debug_store = debug_store or InMemoryDebugArtifactStore()
        self.event_service = event_service or EventService(
            metrics=self.metrics,
            tracer=self.tracer,
            debug_store=self.debug_store,
        )

    def publish(
        self,
        event: EventRecord | Mapping[str, Any],
        *,
        correlation: EventCorrelationContext | Mapping[str, Any] | None = None,
        redact: bool = True,
    ) -> EventRecord:
        return self.event_service.publish(event, correlation=correlation, redact=redact)

    def record_debug_artifact(
        self,
        *,
        workflow_run_id: str,
        name: str,
        payload_json: dict[str, Any] | None = None,
        task_id: str | None = None,
        task_attempt_id: str | None = None,
    ) -> DebugArtifactRecord:
        artifact = DebugArtifactRecord(
            workflow_run_id=workflow_run_id,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            name=name,
            payload_json=payload_json or {},
        )
        return self.debug_store.put(artifact)
