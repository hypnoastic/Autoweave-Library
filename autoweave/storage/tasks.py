"""Celery task-shape scaffolding used by the storage layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CeleryTaskEnvelope:
    task_name: str
    queue: str
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class DispatchWorkflowTask(CeleryTaskEnvelope):
    task_name: str = "autoweave.dispatch.workflow"
    queue: str = "dispatch"


@dataclass(frozen=True)
class ProjectGraphTask(CeleryTaskEnvelope):
    task_name: str = "autoweave.project.graph"
    queue: str = "graph"


@dataclass(frozen=True)
class CleanupWorkspaceTask(CeleryTaskEnvelope):
    task_name: str = "autoweave.cleanup.workspace"
    queue: str = "cleanup"
