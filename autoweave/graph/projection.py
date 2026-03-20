"""Graph projection and query abstractions downstream of canonical truth."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from autoweave.models import EventRecord


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@dataclass(frozen=True)
class ProjectedRelation:
    source_id: str
    relation: str
    target_id: str
    event_id: str


@dataclass
class ProjectedNode:
    node_id: str
    labels: set[str] = field(default_factory=set)
    properties: dict[str, str] = field(default_factory=dict)


class InMemoryGraphProjectionBackend:
    """Asynchronous projection surrogate used for deterministic tests."""

    def __init__(self) -> None:
        self._events: list[EventRecord] = []
        self._nodes: dict[str, ProjectedNode] = {}
        self._relations: list[ProjectedRelation] = []

    def project_event(self, event: EventRecord) -> None:
        self._events.append(event.model_copy(deep=True))
        payload = event.payload_json
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str):
            return
        node = self._nodes.setdefault(entity_id, ProjectedNode(node_id=entity_id))
        node.labels.add(payload.get("entity_type", "Entity"))
        for key, value in payload.items():
            if isinstance(value, str):
                node.properties[key] = value
        relation = payload.get("relation")
        target_id = payload.get("target_id")
        if isinstance(relation, str) and isinstance(target_id, str):
            self._relations.append(
                ProjectedRelation(
                    source_id=entity_id,
                    relation=relation,
                    target_id=target_id,
                    event_id=event.id,
                )
            )

    def query_related_entities(self, entity_id: str, depth: int = 1) -> list[dict[str, str]]:
        matches = [relation for relation in self._relations if relation.source_id == entity_id or relation.target_id == entity_id]
        return [
            {
                "source_id": relation.source_id,
                "relation": relation.relation,
                "target_id": relation.target_id,
                "event_id": relation.event_id,
            }
            for relation in matches[: max(depth, 1)]
        ]

    def list_events(self) -> list[EventRecord]:
        return [event.model_copy(deep=True) for event in self._events]


class SQLiteGraphProjectionBackend:
    """Durable graph projection that persists projected entities locally."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    def _initialize(self) -> None:
        with _connect(self.database_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    labels_json TEXT NOT NULL,
                    properties_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relations (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_id TEXT NOT NULL
                );
                """
            )

    def project_event(self, event: EventRecord) -> None:
        payload = dict(event.payload_json)
        with _connect(self.database_path) as conn:
            conn.execute(
                "INSERT INTO events (event_id, workflow_run_id, data_json) VALUES (?, ?, ?) "
                "ON CONFLICT(event_id) DO UPDATE SET workflow_run_id=excluded.workflow_run_id, data_json=excluded.data_json",
                (event.id, event.workflow_run_id, event.model_dump_json()),
            )
            entity_id = payload.get("entity_id")
            if isinstance(entity_id, str):
                labels = {str(payload.get("entity_type", "Entity"))}
                existing = conn.execute(
                    "SELECT labels_json, properties_json FROM nodes WHERE node_id = ?",
                    (entity_id,),
                ).fetchone()
                if existing is not None:
                    labels.update(json.loads(existing["labels_json"]))
                    properties = dict(json.loads(existing["properties_json"]))
                else:
                    properties = {}
                for key, value in payload.items():
                    if isinstance(value, str):
                        properties[key] = value
                conn.execute(
                    "INSERT INTO nodes (node_id, labels_json, properties_json) VALUES (?, ?, ?) "
                    "ON CONFLICT(node_id) DO UPDATE SET labels_json=excluded.labels_json, properties_json=excluded.properties_json",
                    (entity_id, json.dumps(sorted(labels)), json.dumps(properties, sort_keys=True)),
                )
            relation = payload.get("relation")
            target_id = payload.get("target_id")
            if isinstance(entity_id, str) and isinstance(relation, str) and isinstance(target_id, str):
                conn.execute(
                    "INSERT INTO relations (event_id, source_id, relation, target_id) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(event_id) DO UPDATE SET source_id=excluded.source_id, relation=excluded.relation, target_id=excluded.target_id",
                    (event.id, entity_id, relation, target_id),
                )

    def query_related_entities(self, entity_id: str, depth: int = 1) -> list[dict[str, str]]:
        with _connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT source_id, relation, target_id, event_id FROM relations "
                "WHERE source_id = ? OR target_id = ? ORDER BY rowid LIMIT ?",
                (entity_id, entity_id, max(depth, 1)),
            ).fetchall()
        return [
            {
                "source_id": row["source_id"],
                "relation": row["relation"],
                "target_id": row["target_id"],
                "event_id": row["event_id"],
            }
            for row in rows
        ]

    def list_events(self) -> list[EventRecord]:
        with _connect(self.database_path) as conn:
            rows = conn.execute("SELECT data_json FROM events ORDER BY rowid").fetchall()
        return [EventRecord.model_validate_json(row["data_json"]) for row in rows]

    def clear_namespace(self) -> None:
        with _connect(self.database_path) as conn:
            conn.execute("DELETE FROM relations")
            conn.execute("DELETE FROM nodes")
            conn.execute("DELETE FROM events")

    def close(self) -> None:
        """Compatibility no-op for graph fixtures."""
