"""Memory layer scaffolding with simple deterministic retrieval."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from autoweave.models import MemoryEntryRecord, MemoryLayer


@dataclass(frozen=True)
class MemoryQueryResult:
    entry: MemoryEntryRecord
    score: int


class InMemoryMemoryStore:
    """Durable-memory scaffold for episodic, semantic, procedural, code, and graph memory."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntryRecord] = {}
        self._by_scope: dict[tuple[str, str], list[str]] = defaultdict(list)

    def write(self, entry: MemoryEntryRecord) -> MemoryEntryRecord:
        record = entry.model_copy(deep=True)
        self._entries[record.id] = record
        scope_key = (record.scope_type, record.scope_id)
        if record.id not in self._by_scope[scope_key]:
            self._by_scope[scope_key].append(record.id)
        return record

    def search(self, query: str, scope: str, top_k: int) -> list[MemoryQueryResult]:
        scope_type, _, scope_id = scope.partition(":")
        if not scope_type:
            scope_type = "project"
            scope_id = scope
        matches: list[MemoryQueryResult] = []
        query_terms = {term for term in query.lower().split() if term}
        for entry_id in self._by_scope.get((scope_type, scope_id), []):
            entry = self._entries[entry_id]
            haystack = " ".join([entry.content, str(entry.metadata_json)]).lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score > 0:
                matches.append(MemoryQueryResult(entry=entry.model_copy(deep=True), score=score))
        matches.sort(key=lambda item: (-item.score, item.entry.created_at, item.entry.id))
        return matches[:top_k]

    def list_scope(self, scope_type: str, scope_id: str) -> list[MemoryEntryRecord]:
        return [self._entries[entry_id].model_copy(deep=True) for entry_id in self._by_scope.get((scope_type, scope_id), [])]

    def delete_matching(self, predicate: Callable[[MemoryEntryRecord], bool]) -> tuple[str, ...]:
        deleted_ids: list[str] = []
        for entry_id, entry in list(self._entries.items()):
            if not predicate(entry):
                continue
            deleted_ids.append(entry_id)
            self._entries.pop(entry_id, None)
            scope_key = (entry.scope_type, entry.scope_id)
            self._by_scope[scope_key] = [
                existing_id for existing_id in self._by_scope.get(scope_key, []) if existing_id != entry_id
            ]
            if not self._by_scope[scope_key]:
                self._by_scope.pop(scope_key, None)
        return tuple(deleted_ids)

    def compact(self, scope_type: str, scope_id: str) -> MemoryEntryRecord | None:
        entries = self.list_scope(scope_type, scope_id)
        if not entries:
            return None
        combined_content = "\n".join(entry.content for entry in entries)
        return MemoryEntryRecord(
            project_id=entries[0].project_id,
            scope_type=scope_type,
            scope_id=scope_id,
            memory_layer=entries[0].memory_layer,
            content=combined_content,
            metadata_json={"compacted_from": [entry.id for entry in entries]},
        )
