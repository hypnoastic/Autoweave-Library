"""Artifact payload handle types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InlineArtifactPayload:
    artifact_id: str
    content: str
    size_bytes: int
    content_type: str = "text/plain"


@dataclass(frozen=True)
class ArtifactHandle:
    artifact_id: str
    storage_uri: str
    checksum: str
    size_bytes: int
    content_type: str = "application/octet-stream"

