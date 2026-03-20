"""Artifact registry with orchestrator-defined visibility rules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from autoweave.artifacts.handles import ArtifactHandle, InlineArtifactPayload
from autoweave.artifacts.filesystem import ArtifactPayloadStore
from autoweave.models import ArtifactRecord, ArtifactStatus

@dataclass(frozen=True)
class ArtifactVisibilityDecision:
    artifact_id: str
    visible: bool
    reason: str


class InMemoryArtifactRegistry:
    """Registry that scopes visibility to orchestrator-approved upstream tasks."""

    def __init__(
        self,
        workflow_repository: Any,
        *,
        payload_store: ArtifactPayloadStore | None = None,
    ) -> None:
        self._workflow_repository = workflow_repository
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._artifacts_by_task: dict[str, list[str]] = defaultdict(list)
        self._artifact_versions: dict[tuple[str, str, str], int] = defaultdict(int)
        self._payload_store = payload_store

    def put_artifact(self, artifact: ArtifactRecord, payload: Any | None = None) -> ArtifactRecord:
        record = artifact.model_copy(deep=True)
        version_key = (record.workflow_run_id, record.task_id, record.artifact_type)
        existing = self._list_task_artifacts(record.task_id, record.workflow_run_id)
        current_max_version = max(
            [self._artifact_versions[version_key], *[candidate.version for candidate in existing if candidate.artifact_type == record.artifact_type]],
            default=0,
        )
        next_version = current_max_version + 1
        if record.version <= 0 or record.version <= current_max_version:
            record = record.model_copy(update={"version": next_version})
        self._artifact_versions[version_key] = max(current_max_version, record.version)

        if self._payload_store is not None:
            stored = self._payload_store.write(record, payload=record.summary if payload is None else payload)
            record = record.model_copy(update={"storage_uri": stored.storage_uri, "checksum": stored.checksum})

        prior_records = [
            candidate
            for candidate in existing
            if candidate.artifact_type == record.artifact_type and candidate.id != record.id
        ]
        if record.status == ArtifactStatus.FINAL:
            for prior in prior_records:
                prior_id = prior.id
                if prior.status == ArtifactStatus.FINAL:
                    superseded = prior.model_copy(update={"status": ArtifactStatus.SUPERSEDED})
                    self._persist_artifact(superseded)

        self._persist_artifact(record)
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        if hasattr(self._workflow_repository, "get_artifact"):
            try:
                artifact = self._workflow_repository.get_artifact(artifact_id)  # type: ignore[attr-defined]
                return artifact.model_copy(deep=True)
            except KeyError:
                pass
        try:
            return self._artifacts[artifact_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"artifact {artifact_id!r} is not registered") from exc

    def visibility_decision(self, artifact_id: str, *, task_id: str) -> ArtifactVisibilityDecision:
        artifact = self.get_artifact(artifact_id)
        visible_ids = {candidate.id for candidate in self.get_upstream_artifacts(task_id=task_id)}
        if artifact.id in visible_ids:
            return ArtifactVisibilityDecision(artifact_id=artifact.id, visible=True, reason="dependency_scope")
        return ArtifactVisibilityDecision(artifact_id=artifact.id, visible=False, reason="outside_scope")

    def get_upstream_artifacts(
        self,
        *,
        task_id: str,
        artifact_type: str | None = None,
        from_role: str | None = None,
        status: str | None = None,
    ) -> list[ArtifactRecord]:
        graph = self._workflow_repository.graph_for_task(task_id)
        eligible_task_ids = set(self._workflow_repository.upstream_task_ids(task_id))

        artifacts: list[ArtifactRecord] = []
        candidates = self._list_run_artifacts(graph.workflow_run.id)
        for candidate in candidates:
            if candidate.workflow_run_id != graph.workflow_run.id:
                continue
            if candidate.task_id not in eligible_task_ids:
                continue
            if artifact_type is not None and candidate.artifact_type != artifact_type:
                continue
            if from_role is not None and candidate.produced_by_role != from_role:
                continue
            if status is None:
                if candidate.status != ArtifactStatus.FINAL:
                    continue
            else:
                if candidate.status.value != status:
                    continue
                if candidate.status == ArtifactStatus.DRAFT and not candidate.metadata_json.get("allow_draft_visibility", False):
                    continue
            artifacts.append(candidate.model_copy(deep=True))

        artifacts.sort(key=lambda item: (item.created_at, item.version, item.id))
        return artifacts

    def resolve_payload(self, artifact_id: str, *, max_inline_bytes: int = 256_000) -> InlineArtifactPayload | ArtifactHandle:
        artifact = self.get_artifact(artifact_id)
        size_bytes = int(artifact.metadata_json.get("size_bytes", len(artifact.summary.encode("utf-8"))))
        if size_bytes <= max_inline_bytes:
            return InlineArtifactPayload(
                artifact_id=artifact.id,
                content=artifact.summary,
                size_bytes=size_bytes,
                content_type=artifact.metadata_json.get("content_type", "text/plain"),
            )
        return ArtifactHandle(
            artifact_id=artifact.id,
            storage_uri=artifact.storage_uri,
            checksum=artifact.checksum,
            size_bytes=size_bytes,
            content_type=artifact.metadata_json.get("content_type", "application/octet-stream"),
        )

    def _persist_artifact(self, artifact: ArtifactRecord) -> None:
        record = artifact.model_copy(deep=True)
        self._artifacts[record.id] = record
        if record.id not in self._artifacts_by_task[record.task_id]:
            self._artifacts_by_task[record.task_id].append(record.id)
        if hasattr(self._workflow_repository, "save_artifact"):
            self._workflow_repository.save_artifact(record)  # type: ignore[attr-defined]

    def _list_task_artifacts(self, task_id: str, workflow_run_id: str) -> list[ArtifactRecord]:
        if hasattr(self._workflow_repository, "list_artifacts_for_task"):
            try:
                artifacts = self._workflow_repository.list_artifacts_for_task(task_id)  # type: ignore[attr-defined]
                return [artifact for artifact in artifacts if artifact.workflow_run_id == workflow_run_id]
            except KeyError:
                return []
        return [self._artifacts[artifact_id] for artifact_id in self._artifacts_by_task.get(task_id, [])]

    def _list_run_artifacts(self, workflow_run_id: str) -> list[ArtifactRecord]:
        if hasattr(self._workflow_repository, "list_artifacts_for_run"):
            try:
                artifacts = self._workflow_repository.list_artifacts_for_run(workflow_run_id)  # type: ignore[attr-defined]
                return [artifact.model_copy(deep=True) for artifact in artifacts]
            except KeyError:
                return []
        return [artifact.model_copy(deep=True) for artifact in self._artifacts.values() if artifact.workflow_run_id == workflow_run_id]
