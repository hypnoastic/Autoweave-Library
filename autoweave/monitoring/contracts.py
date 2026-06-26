"""Typed monitoring contracts used by the operator console and product surfaces."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from typing import Any

from autoweave.exceptions import RuntimeFailure


class MonitoringSnapshotStatus(StrEnum):
    OK = "ok"
    LOADING = "loading"
    DEGRADED = "degraded"


class MonitoringJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


def _empty_workflow_blueprint() -> dict[str, Any]:
    return {"name": None, "version": None, "entrypoint": None, "roles": [], "templates": []}


@dataclass(slots=True, frozen=True)
class MonitoringSnapshot:
    project_root: str
    agents: list[dict[str, Any]] = field(default_factory=list)
    workflow_blueprint: dict[str, Any] = field(default_factory=_empty_workflow_blueprint)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    selected_run_id: str | None = None
    selected_run: dict[str, Any] | None = None
    status: MonitoringSnapshotStatus = MonitoringSnapshotStatus.OK
    load_error: str | None = None
    load_failures: tuple[RuntimeFailure, ...] = ()
    refreshing: bool = False
    stale: bool = False

    def to_payload(self) -> dict[str, Any]:
        load_error = self.load_error
        if load_error is None and self.load_failures:
            load_error = "\n".join(failure.message for failure in self.load_failures if failure.message)
        payload = {
            "status": self.status.value,
            "load_error": load_error,
            "load_failures": [failure.to_payload() for failure in self.load_failures],
            "degraded_reasons": [failure.code.value for failure in self.load_failures],
            "project_root": self.project_root,
            "agents": list(self.agents),
            "workflow_blueprint": dict(self.workflow_blueprint),
            "jobs": list(self.jobs),
            "runs": list(self.runs),
            "selected_run_id": self.selected_run_id,
            "selected_run": self.selected_run,
            "refreshing": self.refreshing,
        }
        if self.stale:
            payload["stale"] = True
        return payload


@dataclass(slots=True, frozen=True)
class MonitoringActionReceipt:
    id: str
    action: str
    request: str
    dispatch: bool
    max_steps: int
    status: str
    workflow_run_id: str | None = None
    human_request_id: str | None = None
    approval_request_id: str | None = None
    approved: bool | None = None
    celery_task_id: str | None = None
    queue_backend: str | None = None
    queue: str | None = None
    error: str | None = None
    failure: RuntimeFailure | None = None
    summary_lines: tuple[str, ...] = ()
    step_reports: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        failure_payload = self.failure.to_payload() if self.failure is not None else None
        payload: dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "request": self.request,
            "dispatch": self.dispatch,
            "max_steps": self.max_steps,
            "status": self.status,
            "workflow_run_id": self.workflow_run_id,
            "human_request_id": self.human_request_id,
            "approval_request_id": self.approval_request_id,
            "approved": self.approved,
            "celery_task_id": self.celery_task_id,
            "queue_backend": self.queue_backend,
            "queue": self.queue,
            "error": self.error,
            "failure": failure_payload,
        }
        if self.summary_lines:
            payload["summary_lines"] = list(self.summary_lines)
        if self.step_reports:
            payload["step_reports"] = list(self.step_reports)
        return payload
