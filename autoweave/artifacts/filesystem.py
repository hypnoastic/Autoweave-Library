"""Filesystem-backed artifact storage for local development."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from autoweave.artifacts.handles import ArtifactHandle
from autoweave.models import ArtifactRecord


class ArtifactPayloadStore(Protocol):
    def write(self, artifact: ArtifactRecord, payload: Any | None = None) -> ArtifactHandle: ...

    def read_manifest(self, artifact_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StoredArtifactManifest:
    artifact_id: str
    manifest_path: Path
    payload_path: Path
    storage_uri: str
    checksum: str
    size_bytes: int
    content_type: str


class FilesystemArtifactStore:
    """Persist artifact manifests and payloads to a local filesystem path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def artifact_dir(self, artifact: ArtifactRecord) -> Path:
        return self.root / artifact.workflow_run_id / artifact.task_id / artifact.id

    def manifest_path(self, artifact: ArtifactRecord) -> Path:
        return self.artifact_dir(artifact) / "artifact.json"

    def payload_path(self, artifact: ArtifactRecord, suffix: str = "payload.txt") -> Path:
        return self.artifact_dir(artifact) / suffix

    def write(self, artifact: ArtifactRecord, payload: Any | None = None) -> ArtifactHandle:
        self.artifact_dir(artifact).mkdir(parents=True, exist_ok=True)
        manifest = self._build_manifest(artifact, payload)
        self._write_payload(manifest)
        self.manifest_path(artifact).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return ArtifactHandle(
            artifact_id=artifact.id,
            storage_uri=self.manifest_path(artifact).as_uri(),
            checksum=artifact.checksum,
            size_bytes=manifest["size_bytes"],
            content_type=manifest["content_type"],
        )

    def read_manifest(self, artifact_id: str) -> dict[str, Any]:
        matches = list(self.root.rglob(f"{artifact_id}/artifact.json"))
        if not matches:
            raise KeyError(f"artifact {artifact_id!r} is not stored on disk")
        return json.loads(matches[0].read_text(encoding="utf-8"))

    def read(self, artifact_id: str) -> StoredArtifactManifest:
        manifest = self.read_manifest(artifact_id)
        return StoredArtifactManifest(
            artifact_id=manifest["artifact"]["id"],
            manifest_path=Path(manifest["manifest_path"]),
            payload_path=Path(manifest["payload_path"]),
            storage_uri=manifest["storage_uri"],
            checksum=manifest["checksum"],
            size_bytes=int(manifest["size_bytes"]),
            content_type=manifest["content_type"],
        )

    def _build_manifest(self, artifact: ArtifactRecord, payload: Any | None) -> dict[str, Any]:
        if payload is None:
            payload = artifact.summary
        if isinstance(payload, bytes):
            payload_encoding = "base64"
            payload_blob = base64.b64encode(payload).decode("ascii")
            size_bytes = len(payload)
            content_type = artifact.metadata_json.get("content_type", "application/octet-stream")
        elif isinstance(payload, str):
            payload_encoding = "text"
            payload_blob = payload
            size_bytes = len(payload.encode("utf-8"))
            content_type = artifact.metadata_json.get("content_type", "text/plain")
        else:
            payload_encoding = "json"
            payload_blob = payload
            encoded = json.dumps(payload, sort_keys=True)
            size_bytes = len(encoded.encode("utf-8"))
            content_type = artifact.metadata_json.get("content_type", "application/json")
        return {
            "artifact": artifact.model_dump(mode="json"),
            "artifact_id": artifact.id,
            "manifest_path": str(self.manifest_path(artifact)),
            "payload_path": str(self.payload_path(artifact, suffix=self._payload_suffix(payload))),
            "payload_encoding": payload_encoding,
            "payload": payload_blob,
            "storage_uri": self.manifest_path(artifact).as_uri(),
            "checksum": artifact.checksum,
            "size_bytes": size_bytes,
            "content_type": content_type,
        }

    def _write_payload(self, manifest: dict[str, Any]) -> None:
        payload_path = Path(manifest["payload_path"])
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = manifest["payload_encoding"]
        payload = manifest["payload"]
        if encoding == "base64":
            payload_path.write_bytes(base64.b64decode(payload))
        elif encoding == "json":
            payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        else:
            payload_path.write_text(str(payload), encoding="utf-8")

    def _payload_suffix(self, payload: Any | None) -> str:
        if isinstance(payload, bytes):
            return "payload.bin"
        if isinstance(payload, str) or payload is None:
            return "payload.txt"
        return "payload.json"
