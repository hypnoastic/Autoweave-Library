"""File-backed local observability sinks and convenience wiring."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from autoweave.events.local import JsonlEventStore, _append_jsonl
from autoweave.events.redaction import redact_payload
from autoweave.events.service import EventService
from autoweave.models import EventRecord
from autoweave.observability.debug import DebugArtifactRecord
from autoweave.observability.metrics import MetricSample, snapshot_metrics
from autoweave.observability.tracing import SpanRecord
from autoweave.settings import DEFAULT_OBSERVABILITY_DIR, LocalEnvironmentSettings


@dataclass(frozen=True)
class LocalObservabilityPaths:
    root_dir: Path
    events_path: Path
    metrics_path: Path
    traces_path: Path
    debug_path: Path

    @classmethod
    def from_root(cls, root_dir: Path) -> "LocalObservabilityPaths":
        base = root_dir / DEFAULT_OBSERVABILITY_DIR
        return cls(
            root_dir=base,
            events_path=base / "events.jsonl",
            metrics_path=base / "metrics.jsonl",
            traces_path=base / "traces.jsonl",
            debug_path=base / "debug_artifacts.jsonl",
        )

    @classmethod
    def from_settings(cls, settings: LocalEnvironmentSettings) -> "LocalObservabilityPaths":
        return cls.from_root(settings.project_root)


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    _append_jsonl(path, payload)


class JsonlMetricsSink:
    """File-backed metric sink for local development."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.samples: list[MetricSample] = []

    def _append(self, sample: MetricSample) -> None:
        self.samples.append(sample)
        _write_jsonl(self.path, sample.model_dump(mode="json"))

    def increment(self, name: str, value: float = 1.0, *, labels: dict[str, str] | None = None) -> None:
        self._append(MetricSample(name=name, kind="counter", value=value, labels=labels or {}))

    def gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self._append(MetricSample(name=name, kind="gauge", value=value, labels=labels or {}))

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self._append(MetricSample(name=name, kind="histogram", value=value, labels=labels or {}))


class JsonlTracer:
    """File-backed tracer that records completed spans to JSONL."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.spans: list[SpanRecord] = []

    @contextmanager
    def span(self, name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[SpanRecord]:
        record = SpanRecord(
            trace_id=uuid4().hex,
            span_id=uuid4().hex,
            name=name,
            attributes=attributes or {},
        )
        try:
            yield record
        finally:
            finished = record.model_copy(update={"ended_at": datetime.now(tz=UTC)})
            self.spans.append(finished)
            _write_jsonl(self.path, finished.model_dump(mode="json"))


class JsonlDebugArtifactStore:
    """File-backed debug artifact sink separated from product-facing events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._artifacts: dict[str, list[DebugArtifactRecord]] = {}

    def put(self, artifact: DebugArtifactRecord) -> DebugArtifactRecord:
        stored = artifact.model_copy(update={"payload_json": redact_payload(artifact.payload_json)})
        self._artifacts.setdefault(stored.workflow_run_id, []).append(stored)
        _write_jsonl(self.path, stored.model_dump(mode="json"))
        return stored

    def list_for_run(self, workflow_run_id: str) -> list[DebugArtifactRecord]:
        return list(self._artifacts.get(workflow_run_id, []))


class LocalObservabilityService:
    """Composition helper for local file-backed observability."""

    def __init__(
        self,
        *,
        settings: LocalEnvironmentSettings,
        event_service: EventService | None = None,
        metrics: JsonlMetricsSink | None = None,
        tracer: JsonlTracer | None = None,
        debug_store: JsonlDebugArtifactStore | None = None,
    ) -> None:
        self.settings = settings
        self.paths = LocalObservabilityPaths.from_settings(settings)
        self.paths.root_dir.mkdir(parents=True, exist_ok=True)
        self.metrics = metrics or JsonlMetricsSink(self.paths.metrics_path)
        self.tracer = tracer or JsonlTracer(self.paths.traces_path)
        self.debug_store = debug_store or JsonlDebugArtifactStore(self.paths.debug_path)
        self.event_store = JsonlEventStore(self.paths.events_path)
        self.event_service = event_service or EventService(
            store=self.event_store,
            metrics=self.metrics,
            tracer=self.tracer,
            debug_store=self.debug_store,
        )

    @classmethod
    def from_settings(
        cls,
        settings: LocalEnvironmentSettings,
        *,
        event_service: EventService | None = None,
    ) -> "LocalObservabilityService":
        return cls(settings=settings, event_service=event_service)

    def publish(
        self,
        event: EventRecord | dict[str, Any],
        *,
        correlation: Any | None = None,
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
        return self.event_service.record_debug_artifact(
            DebugArtifactRecord(
                workflow_run_id=workflow_run_id,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
                name=name,
                payload_json=payload_json or {},
            )
        )

    def metrics_snapshot(self) -> dict[str, float]:
        return snapshot_metrics(self.metrics.samples).counts
