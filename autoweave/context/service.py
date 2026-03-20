"""Context service that resolves typed misses and scoped reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoweave.artifacts.registry import InMemoryArtifactRegistry
from autoweave.memory.store import InMemoryMemoryStore, MemoryQueryResult
from autoweave.models import MissingContextReason, TaskRecord, TypedMissResponse


@dataclass(frozen=True)
class ContextLookupResult:
    found: bool
    value: TaskRecord | list[MemoryQueryResult] | list[str] | None
    miss: TypedMissResponse | None = None


class InMemoryContextService:
    """Layered context service that never returns raw DB access."""

    def __init__(
        self,
        *,
        workflow_repository: Any,
        artifact_registry: InMemoryArtifactRegistry,
        memory_store: InMemoryMemoryStore,
    ) -> None:
        self._workflow_repository = workflow_repository
        self._artifact_registry = artifact_registry
        self._memory_store = memory_store

    def get_task(self, task_id: str) -> TaskRecord:
        return self._workflow_repository.get_task(task_id)

    def lookup_task(self, task_id: str) -> ContextLookupResult:
        try:
            task = self.get_task(task_id)
        except KeyError:
            return ContextLookupResult(
                found=False,
                value=None,
                miss=self.resolve_typed_miss(MissingContextReason.NOT_FOUND, next_action="retry_after_refresh"),
            )
        return ContextLookupResult(found=True, value=task)

    def get_upstream_artifacts(
        self,
        *,
        task_id: str,
        artifact_type: str | None = None,
        from_role: str | None = None,
        status: str | None = None,
    ) -> list:
        return self._artifact_registry.get_upstream_artifacts(
            task_id=task_id,
            artifact_type=artifact_type,
            from_role=from_role,
            status=status,
        )

    def get_artifact(self, artifact_id: str):
        return self._artifact_registry.get_artifact(artifact_id)

    def search_memory(self, query: str, scope: str, top_k: int) -> list[str]:
        if hasattr(self._workflow_repository, "search_memory"):
            results = self._workflow_repository.search_memory(query, scope, top_k)  # type: ignore[attr-defined]
            return [entry.content for entry in results]
        return [result.entry.content for result in self._memory_store.search(query, scope, top_k)]

    def lookup_memory(self, query: str, scope: str, top_k: int) -> ContextLookupResult:
        if hasattr(self._workflow_repository, "search_memory"):
            matches = self._workflow_repository.search_memory(query, scope, top_k)  # type: ignore[attr-defined]
        else:
            matches = self._memory_store.search(query, scope, top_k)
        if not matches:
            return ContextLookupResult(
                found=False,
                value=None,
                miss=self.resolve_typed_miss(MissingContextReason.NOT_INDEXED_YET, next_action="retry_later"),
            )
        return ContextLookupResult(found=True, value=matches)

    def get_related_code_context(self, query: str, file_filters: list[str] | None = None) -> list[str]:
        scope = "code:global"
        if hasattr(self._workflow_repository, "search_memory"):
            hits = self._workflow_repository.search_memory(query, scope, top_k=5)  # type: ignore[attr-defined]
        else:
            hits = self._memory_store.search(query, scope, top_k=5)
        if file_filters:
            filtered: list[str] = []
            for hit in hits:
                content = hit.content if hasattr(hit, "content") else hit.entry.content
                if any(file_filter in content for file_filter in file_filters):
                    filtered.append(content)
            return filtered
        return [hit.content if hasattr(hit, "content") else hit.entry.content for hit in hits]

    def resolve_typed_miss(self, reason: str | MissingContextReason, *, next_action: str) -> TypedMissResponse:
        miss_reason = reason if isinstance(reason, MissingContextReason) else MissingContextReason(reason)
        return TypedMissResponse(reason=miss_reason, next_action=next_action)

    def append_attempt_note(self, task_id: str, note: str) -> None:
        task = self._workflow_repository.get_task(task_id)
        notes = task.output_json.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)]
        task.output_json = {**task.output_json, "notes": [*notes, note]}
        self._workflow_repository.save_task(task)
