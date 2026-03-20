"""Normalized event schema and correlation helpers.

This module keeps the product-facing event shape aligned with the architecture
docs while remaining lightweight enough for in-memory testing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from autoweave.models import EventRecord, EventSeverity, utc_now


class EventCorrelationContext(BaseModel):
    """Correlation metadata that can be attached to an event."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str
    task_id: str | None = None
    task_attempt_id: str | None = None
    agent_id: str | None = None
    agent_role: str | None = None
    sandbox_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    route_reason: str | None = None


class EventCursor(BaseModel):
    """Cursor for replaying or resuming a live event stream."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str
    sequence_no: int = 0
    event_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    def advance(self, event: EventRecord) -> "EventCursor":
        return self.model_copy(
            update={
                "workflow_run_id": event.workflow_run_id,
                "sequence_no": event.sequence_no,
                "event_id": event.id,
                "created_at": utc_now(),
            }
        )


def _merge_context(
    data: Mapping[str, Any],
    correlation: EventCorrelationContext | Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(data)
    if correlation is None:
        return payload

    correlation_data = (
        correlation.model_dump()
        if isinstance(correlation, EventCorrelationContext)
        else dict(correlation)
    )
    for key, value in correlation_data.items():
        payload.setdefault(key, value)
    return payload


def normalize_event(
    data: EventRecord | Mapping[str, Any],
    *,
    correlation: EventCorrelationContext | Mapping[str, Any] | None = None,
    event_type: str | None = None,
    source: str | None = None,
) -> EventRecord:
    """Return an EventRecord with explicit correlation nulls and defaults.

    The model already defaults the optional correlation fields to `None`, but
    callers can still pass partial dictionaries here and get a normalized event
    back for persistence/export.
    """

    if isinstance(data, EventRecord):
        normalized = data.model_copy()
    else:
        normalized = EventRecord.model_validate(
            _merge_context(data, correlation)
        )

    if event_type is not None:
        normalized = normalized.model_copy(update={"event_type": event_type})
    if source is not None:
        normalized = normalized.model_copy(update={"source": source})
    return normalized


def make_event(
    *,
    workflow_run_id: str,
    event_type: str,
    source: str,
    payload_json: dict[str, Any] | None = None,
    task_id: str | None = None,
    task_attempt_id: str | None = None,
    agent_id: str | None = None,
    agent_role: str | None = None,
    sandbox_id: str | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
    route_reason: str | None = None,
    severity: EventSeverity = EventSeverity.INFO,
    sequence_no: int = 0,
    created_at: datetime | None = None,
) -> EventRecord:
    """Create a normalized event with explicit correlation nulls."""

    return EventRecord(
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        agent_id=agent_id,
        agent_role=agent_role,
        sandbox_id=sandbox_id,
        provider_name=provider_name,
        model_name=model_name,
        route_reason=route_reason,
        event_type=event_type,
        source=source,
        severity=severity,
        sequence_no=sequence_no,
        payload_json=payload_json or {},
        created_at=created_at or utc_now(),
    )

