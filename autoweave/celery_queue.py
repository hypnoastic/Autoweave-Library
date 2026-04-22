"""Celery-backed workflow dispatch helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from celery import Celery
    from celery.result import AsyncResult
    from kombu import Queue
except ModuleNotFoundError as exc:  # pragma: no cover - import-safe fallback for no-deps wheel smoke installs
    Celery = None  # type: ignore[assignment]
    AsyncResult = None  # type: ignore[assignment]
    Queue = None  # type: ignore[assignment]
    _CELERY_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _CELERY_IMPORT_ERROR = None

from autoweave.compiler.loader import CanonicalConfigLoader
from autoweave.config_models import RuntimeConfig
from autoweave.local_runtime import LocalWorkflowRunReport, build_local_runtime
from autoweave.settings import LocalEnvironmentSettings, find_project_root

DEFAULT_CELERY_QUEUE = "dispatch"
WORKFLOW_TASK_NAME = "autoweave.dispatch.workflow"
RECOVERY_METADATA_PATH = Path("var/state/project_scope.json")


def _queue_names(runtime_config: RuntimeConfig) -> tuple[str, ...]:
    names = tuple(name.strip() for name in runtime_config.celery_queue_names if str(name).strip())
    return names or (DEFAULT_CELERY_QUEUE,)


def execution_backend(runtime_config: RuntimeConfig) -> str:
    backend = str(runtime_config.execution_backend).strip().lower()
    if backend not in {"inline", "celery"}:
        return "inline"
    return backend


def celery_execution_enabled(runtime_config: RuntimeConfig) -> bool:
    return execution_backend(runtime_config) == "celery"


def _project_root_from_env() -> Path | None:
    value = os.environ.get("AUTOWEAVE_PROJECT_ROOT", "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def recovery_metadata_file(root: Path) -> Path:
    return root / RECOVERY_METADATA_PATH


def write_recovery_metadata(*, root: Path, project_id: str) -> Path:
    path = recovery_metadata_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"project_id": project_id}, sort_keys=True), encoding="utf-8")
    return path


def load_recovery_project_id(*, root: Path) -> str | None:
    path = recovery_metadata_file(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    project_id = str(payload.get("project_id") or "").strip()
    return project_id or None


def recovery_environ(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    resolved = {key: value for key, value in os.environ.items() if value is not None}
    if environ is not None:
        resolved.update({key: value for key, value in environ.items() if value is not None})

    runtime_overrides = {
        "POSTGRES_URL": "RUNTIME_POSTGRES_URL",
        "REDIS_URL": "RUNTIME_REDIS_URL",
        "NEO4J_URL": "RUNTIME_NEO4J_URL",
        "NEO4J_USERNAME": "RUNTIME_NEO4J_USERNAME",
        "NEO4J_PASSWORD": "RUNTIME_NEO4J_PASSWORD",
        "ARTIFACT_STORE_URL": "RUNTIME_ARTIFACT_STORE_URL",
        "VERTEXAI_PROJECT": "RUNTIME_VERTEX_PROJECT",
        "VERTEXAI_LOCATION": "RUNTIME_VERTEX_LOCATION",
        "VERTEXAI_SERVICE_ACCOUNT_FILE": "RUNTIME_VERTEX_SERVICE_ACCOUNT_FILE",
        "GOOGLE_APPLICATION_CREDENTIALS": "RUNTIME_VERTEX_SERVICE_ACCOUNT_FILE",
        "OPENHANDS_AGENT_SERVER_BASE_URL": "RUNTIME_OPENHANDS_BASE_URL",
        "OPENHANDS_AGENT_SERVER_API_KEY": "RUNTIME_OPENHANDS_API_KEY",
        "AUTOWEAVE_POSTGRES_SCHEMA": "RUNTIME_POSTGRES_SCHEMA",
        "AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS": "RUNTIME_AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS",
    }
    for target_key, source_key in runtime_overrides.items():
        if source_key in resolved:
            resolved[target_key] = str(resolved.get(source_key) or "")

    if "RUNTIME_POSTGRES_URL" in resolved or not str(resolved.get("AUTOWEAVE_CANONICAL_BACKEND") or "").strip():
        resolved["AUTOWEAVE_CANONICAL_BACKEND"] = "postgres" if str(resolved.get("POSTGRES_URL") or "").strip() else "sqlite"
    if "RUNTIME_NEO4J_URL" in resolved or not str(resolved.get("AUTOWEAVE_GRAPH_BACKEND") or "").strip():
        resolved["AUTOWEAVE_GRAPH_BACKEND"] = "neo4j" if str(resolved.get("NEO4J_URL") or "").strip() else "sqlite"
    return resolved


def load_runtime_bundle(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[LocalEnvironmentSettings, RuntimeConfig]:
    settings = LocalEnvironmentSettings.load(root=root, environ=environ)
    loader = CanonicalConfigLoader(root_dir=settings.project_root)
    runtime_config = loader.load_runtime_config(settings.autoweave_runtime_config)
    return settings, runtime_config


def create_autoweave_celery_app(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    settings: LocalEnvironmentSettings | None = None,
    runtime_config: RuntimeConfig | None = None,
) -> Celery:
    if _CELERY_IMPORT_ERROR is not None or Celery is None or Queue is None:
        raise RuntimeError("Celery is not installed. Install project dependencies to use queue-backed dispatch.") from _CELERY_IMPORT_ERROR
    if settings is None or runtime_config is None:
        loaded_settings, loaded_runtime_config = load_runtime_bundle(root=root, environ=environ)
        settings = settings or loaded_settings
        runtime_config = runtime_config or loaded_runtime_config

    queues = _queue_names(runtime_config)
    app = Celery(
        "autoweave",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["autoweave.celery_tasks"],
    )
    app.conf.update(
        task_default_queue=queues[0],
        task_queues=tuple(Queue(name) for name in queues),
        task_routes={
            WORKFLOW_TASK_NAME: {"queue": queues[0]},
        },
        task_track_started=True,
        # Keep long-running workflow dispatches on the broker until the worker
        # actually finishes them so a worker restart can redeliver the task and
        # let LocalRuntime recover the persisted run/attempt state.
        task_acks_late=True,
        task_acks_on_failure_or_timeout=False,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=int(runtime_config.celery_result_expires_seconds),
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )
    return app


@dataclass(slots=True, frozen=True)
class CeleryWorkflowDispatchReceipt:
    workflow_run_id: str
    celery_task_id: str
    action: str
    queue: str
    dispatch: bool
    max_steps: int
    status: str = "queued"
    backend: str = "celery"

    def summary_lines(self) -> list[str]:
        return [
            f"workflow_run_id={self.workflow_run_id}",
            f"dispatch_backend={self.backend}",
            f"celery_task_id={self.celery_task_id}",
            f"celery_queue={self.queue}",
            f"action={self.action}",
            f"dispatch={'yes' if self.dispatch else 'no'}",
            f"max_steps={self.max_steps}",
            f"queue_status={self.status}",
        ]

    def to_payload(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "celery_task_id": self.celery_task_id,
            "action": self.action,
            "queue": self.queue,
            "dispatch": self.dispatch,
            "max_steps": self.max_steps,
            "status": self.status,
            "backend": self.backend,
            "summary_lines": self.summary_lines(),
        }


@dataclass(slots=True, frozen=True)
class CeleryTaskSnapshot:
    task_id: str
    state: str
    workflow_run_id: str | None = None
    report_payload: dict[str, Any] | None = None
    error: str | None = None


def workflow_report_to_payload(report: LocalWorkflowRunReport) -> dict[str, Any]:
    return {
        "workflow_run_id": report.workflow_run_id,
        "request": report.request,
        "workflow_status": report.workflow_status,
        "dispatched_task_keys": list(report.dispatched_task_keys),
        "ready_task_keys": list(report.ready_task_keys),
        "open_human_questions": list(report.open_human_questions),
        "open_approval_reasons": list(report.open_approval_reasons),
        "summary_lines": report.summary_lines(),
        "step_reports": [
            {
                "task_key": step.task_key,
                "task_state": step.task_state,
                "attempt_state": step.attempt_state,
                "route_model_name": step.route_model_name,
                "failure_reason": step.failure_reason,
            }
            for step in report.step_reports
        ],
    }


def should_requeue_report(report: LocalWorkflowRunReport, *, dispatch: bool) -> bool:
    return bool(
        dispatch
        and report.workflow_status == "running"
        and report.ready_task_keys
        and not report.open_human_questions
        and not report.open_approval_reasons
    )


class CeleryWorkflowDispatcher:
    """Queue workflow actions onto a real Celery broker/backend."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        settings: LocalEnvironmentSettings | None = None,
        runtime_config: RuntimeConfig | None = None,
        app: Celery | None = None,
    ) -> None:
        if settings is None or runtime_config is None:
            loaded_settings, loaded_runtime_config = load_runtime_bundle(root=root, environ=environ)
            settings = settings or loaded_settings
            runtime_config = runtime_config or loaded_runtime_config
        self.settings = settings
        self.runtime_config = runtime_config
        self.root = settings.project_root
        self.environ = dict(environ or {})
        self.app = app or create_autoweave_celery_app(settings=settings, runtime_config=runtime_config)
        self.queue_names = _queue_names(runtime_config)

    @classmethod
    def from_runtime(cls, runtime: Any) -> "CeleryWorkflowDispatcher":
        return cls(
            root=runtime.settings.project_root,
            settings=runtime.settings,
            runtime_config=runtime.runtime_config,
        )

    def worker_health(self, *, timeout_seconds: float = 2.5) -> str:
        if not celery_execution_enabled(self.runtime_config):
            return "disabled (execution_backend=inline)"
        try:
            inspect = self.app.control.inspect(timeout=timeout_seconds)
            ping_response = inspect.ping() or {}
            stats_response = inspect.stats() or {}
            response = ping_response or stats_response
            if response:
                active_queues = inspect.active_queues() or {}
                subscribed_workers = 0
                for worker_name, queues in active_queues.items():
                    queue_names = {
                        str(queue.get("name") or "").strip()
                        for queue in queues
                        if isinstance(queue, dict)
                    }
                    if queue_names & set(self.queue_names):
                        subscribed_workers += 1
                if active_queues and subscribed_workers == 0:
                    return (
                        f"degraded (workers={len(response)}; subscribed_workers=0; "
                        f"queues={', '.join(self.queue_names)})"
                    )
                probe = "ping" if ping_response else "stats"
                return (
                    f"ok (workers={len(response)}; queues={', '.join(self.queue_names)}; "
                    f"subscribed_workers={subscribed_workers or len(response)}; probe={probe})"
                )
            return "error (no active celery workers responded)"
        except Exception as exc:
            return f"error ({exc})"

    def enqueue_new_workflow(
        self,
        *,
        request: str,
        dispatch: bool,
        max_steps: int,
        project_id: str | None = None,
    ) -> CeleryWorkflowDispatchReceipt:
        with build_local_runtime(root=self.root, environ=self.environ, project_id=project_id) as runtime:
            workflow_run_id = runtime.initialize_workflow_run(request=request, project_id=project_id)
        return self.enqueue_workflow_action(
            action="continue_workflow",
            workflow_run_id=workflow_run_id,
            request=request,
            dispatch=dispatch,
            max_steps=max_steps,
        )

    def enqueue_workflow_action(
        self,
        *,
        action: str,
        workflow_run_id: str,
        request: str,
        dispatch: bool,
        max_steps: int,
        human_request_id: str | None = None,
        approval_request_id: str | None = None,
        approved: bool | None = None,
    ) -> CeleryWorkflowDispatchReceipt:
        queue_name = self.queue_names[0]
        payload = {
            "action": action,
            "root": str(self.root),
            "environ": dict(self.environ),
            "workflow_run_id": workflow_run_id,
            "request": request,
            "dispatch": bool(dispatch),
            "max_steps": max(1, int(max_steps)),
            "human_request_id": human_request_id,
            "approval_request_id": approval_request_id,
            "approved": approved,
        }
        async_result = self.app.send_task(WORKFLOW_TASK_NAME, kwargs={"payload": payload}, queue=queue_name)
        return CeleryWorkflowDispatchReceipt(
            workflow_run_id=workflow_run_id,
            celery_task_id=async_result.id,
            action=action,
            queue=queue_name,
            dispatch=bool(dispatch),
            max_steps=max(1, int(max_steps)),
        )

    def inspect_task(self, task_id: str) -> CeleryTaskSnapshot:
        if AsyncResult is None:
            raise RuntimeError("Celery is not installed. Install project dependencies to inspect queued workflow tasks.")
        result = AsyncResult(task_id, app=self.app)
        state = str(result.state or "PENDING")
        payload = result.result if state == "SUCCESS" else None
        error = None
        if state == "FAILURE":
            error = str(result.result)
        workflow_run_id = None
        report_payload = None
        if isinstance(payload, dict):
            workflow_run_id = str(payload.get("workflow_run_id") or "") or None
            report_payload = payload
        return CeleryTaskSnapshot(
            task_id=task_id,
            state=state,
            workflow_run_id=workflow_run_id,
            report_payload=report_payload,
            error=error,
        )


def recover_workflows(
    *,
    root: Path,
    environ: Mapping[str, str] | None = None,
    project_id: str | None = None,
    dispatch: bool = True,
    max_steps: int = 8,
) -> tuple[CeleryWorkflowDispatchReceipt, ...]:
    resolved_environ = recovery_environ(environ)
    resolved_project_id = str(project_id or load_recovery_project_id(root=root) or "").strip()
    if not resolved_project_id:
        return ()

    dispatcher = CeleryWorkflowDispatcher(root=root, environ=resolved_environ)
    recovered: list[CeleryWorkflowDispatchReceipt] = []
    with build_local_runtime(root=root, environ=resolved_environ, project_id=resolved_project_id) as runtime:
        repository = runtime.storage.workflow_repository
        for workflow_run in repository.list_workflow_runs():
            if workflow_run.project_id != resolved_project_id:
                continue
            if workflow_run.status in {"completed", "failed", "cancelled"}:
                continue
            open_human_requests = [
                item
                for item in repository.list_human_requests_for_run(workflow_run.id)
                if str(item.status.value) == "open"
            ]
            if open_human_requests:
                continue
            open_approval_requests = [
                item
                for item in repository.list_approval_requests_for_run(workflow_run.id)
                if str(item.status.value) == "requested"
            ]
            if open_approval_requests:
                continue
            request_text = str(workflow_run.root_input_json.get("user_request") or "").strip()
            if not request_text:
                continue
            recovered.append(
                dispatcher.enqueue_workflow_action(
                    action="continue_workflow",
                    workflow_run_id=workflow_run.id,
                    request=request_text,
                    dispatch=dispatch,
                    max_steps=max_steps,
                )
            )
    return tuple(recovered)


if Celery is None:
    celery_app = None
else:
    try:
        celery_app = create_autoweave_celery_app(root=_project_root_from_env() or find_project_root())
    except Exception:  # pragma: no cover - defensive import fallback for external Celery discovery
        celery_app = Celery("autoweave", include=["autoweave.celery_tasks"])
