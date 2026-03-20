"""File-backed event storage for local development."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from autoweave.events.schema import EventCursor
from autoweave.models import EventRecord


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str))
        handle.write("\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


class JsonlEventStore:
    """Append-only local event store that persists normalized events to JSONL."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._events_by_run: dict[str, list[EventRecord]] = defaultdict(list)
        self._load_existing()

    def _load_existing(self) -> None:
        for payload in _load_jsonl(self.path):
            event = EventRecord.model_validate(payload)
            self._events_by_run[event.workflow_run_id].append(event)

    def append(self, event: EventRecord) -> EventRecord:
        run_events = self._events_by_run[event.workflow_run_id]
        sequence_no = event.sequence_no or len(run_events) + 1
        stored = event.model_copy(update={"sequence_no": sequence_no})
        run_events.append(stored)
        _append_jsonl(self.path, stored.model_dump(mode="json"))
        return stored

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        return [event.model_copy() for event in self._events_by_run.get(workflow_run_id, [])]

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
        events = self._events_by_run.get(workflow_run_id, [])
        if not events:
            return None
        last_event = events[-1]
        return EventCursor(
            workflow_run_id=last_event.workflow_run_id,
            sequence_no=last_event.sequence_no,
            event_id=last_event.id,
            created_at=last_event.created_at,
        )
