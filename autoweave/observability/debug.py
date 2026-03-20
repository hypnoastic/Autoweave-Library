"""Debug artifact storage separated from product-facing events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autoweave.events.redaction import redact_payload


class DebugArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str
    task_id: str | None = None
    task_attempt_id: str | None = None
    name: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class InMemoryDebugArtifactStore:
    def __init__(self) -> None:
        self._artifacts: dict[str, list[DebugArtifactRecord]] = {}

    def put(self, artifact: DebugArtifactRecord) -> DebugArtifactRecord:
        stored = artifact.model_copy(update={"payload_json": redact_payload(artifact.payload_json)})
        self._artifacts.setdefault(stored.workflow_run_id, []).append(stored)
        return stored

    def list_for_run(self, workflow_run_id: str) -> list[DebugArtifactRecord]:
        return list(self._artifacts.get(workflow_run_id, []))
