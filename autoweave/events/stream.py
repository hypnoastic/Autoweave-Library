"""In-memory event log and cursor-based replay support."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from autoweave.events.schema import EventCursor
from autoweave.models import EventRecord


class EventStore(Protocol):
    def append(self, event: EventRecord) -> EventRecord: ...

    def list_events(self, workflow_run_id: str) -> list[EventRecord]: ...

    def replay_from(
        self, workflow_run_id: str, cursor: EventCursor | None = None
    ) -> list[EventRecord]: ...

    def latest_cursor(self, workflow_run_id: str) -> EventCursor | None: ...


class InMemoryEventStore:
    """Deterministic event store for tests and local development."""

    def __init__(self) -> None:
        self._events: dict[str, list[EventRecord]] = defaultdict(list)

    def append(self, event: EventRecord) -> EventRecord:
        run_events = self._events[event.workflow_run_id]
        sequence_no = event.sequence_no or len(run_events) + 1
        stored = event.model_copy(update={"sequence_no": sequence_no})
        run_events.append(stored)
        return stored

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        return list(self._events.get(workflow_run_id, []))

    def replay_from(
        self, workflow_run_id: str, cursor: EventCursor | None = None
    ) -> list[EventRecord]:
        events = self.list_events(workflow_run_id)
        if cursor is None:
            return events
        if cursor.workflow_run_id != workflow_run_id:
            raise ValueError("cursor workflow_run_id does not match requested workflow run")
        return [event for event in events if event.sequence_no > cursor.sequence_no]

    def latest_cursor(self, workflow_run_id: str) -> EventCursor | None:
        events = self._events.get(workflow_run_id, [])
        if not events:
            return None
        last_event = events[-1]
        return EventCursor(
            workflow_run_id=last_event.workflow_run_id,
            sequence_no=last_event.sequence_no,
            event_id=last_event.id,
            created_at=last_event.created_at,
        )


class EventStreamSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str
    cursor: EventCursor | None = None
    events: list[EventRecord] = Field(default_factory=list)


class LiveEventStream:
    """Cursor-based stream abstraction.

    The implementation is intentionally synchronous and replay-oriented so that
    tests can cover stream recovery deterministically without external broker
    dependencies.
    """

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def snapshot(
        self, workflow_run_id: str, *, cursor: EventCursor | None = None
    ) -> EventStreamSnapshot:
        events = self._store.replay_from(workflow_run_id, cursor)
        latest_cursor = self._store.latest_cursor(workflow_run_id)
        return EventStreamSnapshot(
            workflow_run_id=workflow_run_id,
            cursor=latest_cursor,
            events=events,
        )

    def replay(
        self, workflow_run_id: str, *, cursor: EventCursor | None = None
    ) -> list[EventRecord]:
        return self._store.replay_from(workflow_run_id, cursor)

    def iter_from(
        self, workflow_run_id: str, *, cursor: EventCursor | None = None
    ) -> Iterable[EventRecord]:
        return iter(self._store.replay_from(workflow_run_id, cursor))

