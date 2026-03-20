"""Tracing helpers for AutoWeave observability."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    ended_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000.0


class InMemoryTracer:
    """Minimal tracer that records spans in memory."""

    def __init__(self) -> None:
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
            record = record.model_copy(update={"ended_at": datetime.now(tz=UTC)})
            self.spans.append(record)


def span_attributes(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}

