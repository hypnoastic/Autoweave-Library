"""Canonical workflow inspection and launch helpers for the local monitor UI."""

from __future__ import annotations

import copy
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import yaml

from autoweave.celery_queue import CeleryTaskSnapshot, CeleryWorkflowDispatcher, celery_execution_enabled
from autoweave.compiler.loader import CanonicalConfigLoader
from autoweave.exceptions import ConfigurationError, RuntimeErrorCode, RuntimeFailure, RuntimeOperationError
from autoweave.local_runtime import LocalWorkflowRunReport, build_local_runtime
from autoweave.models import (
    ApprovalRequestRecord,
    ArtifactRecord,
    EventRecord,
    HumanRequestRecord,
    TaskAttemptRecord,
    TaskRecord,
    WorkflowRunRecord,
    generate_id,
)
from autoweave.monitoring.contracts import (
    MonitoringActionReceipt,
    MonitoringJobStatus,
    MonitoringSnapshot,
    MonitoringSnapshotStatus,
)
from autoweave.settings import LocalEnvironmentSettings

_ACTIVE_WORKER_ATTEMPT_STATES = {"dispatching", "running", "paused", "needs_input"}


def _iso(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _short_json(value: object, *, max_length: int = 360) -> str:
    if value is None:
        return "none"
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            import json

            text = json.dumps(value, indent=2, sort_keys=True, default=str)
        except TypeError:
            text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _format_exception_message(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()


def _runtime_failure(
    exc: BaseException,
    *,
    code: RuntimeErrorCode,
    recoverable: bool = False,
    details_json: Mapping[str, Any] | None = None,
) -> RuntimeFailure:
    if isinstance(exc, RuntimeOperationError):
        return exc.failure
    if isinstance(exc, ConfigurationError):
        return RuntimeFailure(
            code=RuntimeErrorCode.CONFIGURATION_INVALID,
            message=_format_exception_message(exc),
            recoverable=False,
            details_json=dict(details_json or {}),
        )
    return RuntimeFailure(
        code=code,
        message=_format_exception_message(exc),
        recoverable=recoverable,
        details_json=dict(details_json or {}),
    )


@dataclass(slots=True)
class MonitoringJob:
    id: str
    action: str
    request: str
    dispatch: bool
    max_steps: int
    status: str = "queued"
    workflow_run_id: str | None = None
    human_request_id: str | None = None
    approval_request_id: str | None = None
    approved: bool | None = None
    celery_task_id: str | None = None
    queue_backend: str | None = None
    queue: str | None = None
    report_payload: dict[str, Any] | None = None
    error: str | None = None
    failure: RuntimeFailure | None = None
    report: LocalWorkflowRunReport | None = None

    def to_payload(self) -> dict[str, Any]:
        summary_lines: tuple[str, ...] = ()
        step_reports: tuple[dict[str, Any], ...] = ()
        if self.report is not None:
            summary_lines = tuple(self.report.summary_lines())
            step_reports = tuple(
                {
                    "task_key": step.task_key,
                    "task_state": step.task_state,
                    "attempt_state": step.attempt_state,
                    "route_model_name": step.route_model_name,
                    "failure_reason": step.failure_reason,
                }
                for step in self.report.step_reports
            )
        elif self.report_payload is not None:
            summary_lines = tuple(str(line) for line in self.report_payload.get("summary_lines", ()))
            step_reports = tuple(
                dict(step) for step in self.report_payload.get("step_reports", ()) if isinstance(step, Mapping)
            )
        receipt = MonitoringActionReceipt(
            id=self.id,
            action=self.action,
            request=self.request,
            dispatch=self.dispatch,
            max_steps=self.max_steps,
            status=self.status,
            workflow_run_id=self.workflow_run_id,
            human_request_id=self.human_request_id,
            approval_request_id=self.approval_request_id,
            approved=self.approved,
            celery_task_id=self.celery_task_id,
            queue_backend=self.queue_backend,
            queue=self.queue,
            error=self.error,
            failure=self.failure,
            summary_lines=summary_lines,
            step_reports=step_reports,
        )
        return receipt.to_payload()


class MonitoringService:
    """Read canonical run state and launch workflows for the local monitor UI."""

    def __init__(
        self,
        *,
        root: Path,
        environ: Mapping[str, str] | None = None,
        runtime_factory: Callable[..., Any] = build_local_runtime,
    ) -> None:
        self.root = root.resolve()
        self.environ = dict(environ or {})
        self._runtime_factory = runtime_factory
        self._can_short_circuit_clean_sqlite = runtime_factory is build_local_runtime or bool(
            getattr(runtime_factory, "autoweave_skip_clean_sqlite", False)
        )
        self._jobs: dict[str, MonitoringJob] = {}
        self._lock = Lock()
        self._snapshot_cache: dict[tuple[int, bool], dict[str, Any]] = {}
        self._snapshot_refreshing: set[tuple[int, bool]] = set()

    def _runtime(self, *, workflow_run_id: str | None = None):
        kwargs: dict[str, Any] = {
            "root": self.root,
            "environ": self.environ,
        }
        if workflow_run_id is not None:
            kwargs["workflow_run_id"] = workflow_run_id
        try:
            return self._runtime_factory(**kwargs)
        except TypeError:
            kwargs.pop("workflow_run_id", None)
            return self._runtime_factory(**kwargs)

    def _loader(self) -> CanonicalConfigLoader:
        return CanonicalConfigLoader(root_dir=self.root)

    def workflow_blueprint(self) -> dict[str, Any]:
        settings = LocalEnvironmentSettings.load(root=self.root, environ=self.environ)
        loader = self._loader()
        workflow_definition = loader.load_workflow_definition(settings.autoweave_default_workflow)
        templates = []
        for template in workflow_definition.task_templates:
            templates.append(
                {
                    "key": template.key,
                    "title": template.title,
                    "assigned_role": template.assigned_role,
                    "description_template": getattr(template, "description_template", ""),
                    "hard_dependencies": list(template.hard_dependencies),
                    "soft_dependencies": list(template.soft_dependencies),
                    "produced_artifacts": list(template.produced_artifacts),
                    "required_artifacts": list(template.required_artifacts),
                    "route_hints": list(getattr(template, "route_hints", [])),
                    "approval_requirements": list(getattr(template, "approval_requirements", [])),
                }
            )
        return {
            "name": workflow_definition.name,
            "version": workflow_definition.version,
            "entrypoint": workflow_definition.entrypoint,
            "roles": list(workflow_definition.roles),
            "templates": templates,
        }

    def agent_catalog(self) -> list[dict[str, Any]]:
        agents_root = self.root / "agents"
        if not agents_root.exists():
            return []
        agents: list[dict[str, Any]] = []
        for role_dir in sorted(path for path in agents_root.iterdir() if path.is_dir()):
            metadata = _load_yaml_mapping(role_dir / "autoweave.yaml")
            playbook = _load_yaml_mapping(role_dir / "playbook.yaml")
            soul_text = _read_text(role_dir / "soul.md")
            skill_files = sorted(
                path.name for path in (role_dir / "skills").glob("*.md") if path.is_file() and path.name != "README.md"
            )
            agents.append(
                {
                    "role": role_dir.name,
                    "name": metadata.get("name", f"{role_dir.name}-agent"),
                    "description": metadata.get("description", ""),
                    "specialization": metadata.get("specialization", ""),
                    "primary_skills": list(metadata.get("primary_skills", [])),
                    "model_profile_hints": list(metadata.get("model_profile_hints", [])),
                    "allowed_tool_groups": list(metadata.get("allowed_tool_groups", [])),
                    "allowed_workflow_stages": list(metadata.get("allowed_workflow_stages", [])),
                    "approval_policy": metadata.get("approval_policy", ""),
                    "human_interaction_policy": metadata.get("human_interaction_policy", ""),
                    "route_priority": metadata.get("route_priority", ""),
                    "playbook_goals": list(playbook.get("goals", [])),
                    "skill_files": skill_files,
                    "soul_excerpt": soul_text.splitlines()[2]
                    if len(soul_text.splitlines()) >= 3
                    else soul_text.strip(),
                }
            )
        return agents

    def snapshot(
        self,
        *,
        limit: int = 5,
        wait_for_refresh: bool = False,
        include_jobs: bool = True,
    ) -> dict[str, Any]:
        request_key = self._snapshot_request_key(limit=limit, include_jobs=include_jobs)
        if wait_for_refresh:
            payload = self._compute_snapshot(limit=limit, include_jobs=include_jobs)
            with self._lock:
                self._snapshot_cache[request_key] = copy.deepcopy(payload)
                self._snapshot_refreshing.discard(request_key)
            refreshed = dict(payload)
            refreshed["refreshing"] = False
            return refreshed
        refresh_thread = self._ensure_snapshot_refresh(limit=limit, include_jobs=include_jobs)
        if refresh_thread is not None:
            refresh_thread.join(timeout=0.25)
        with self._lock:
            cached = copy.deepcopy(self._snapshot_cache.get(request_key))
            refreshing = request_key in self._snapshot_refreshing
        if cached is not None:
            cached["refreshing"] = refreshing
            return cached
        return MonitoringSnapshot(
            project_root=str(self.root),
            jobs=self.jobs() if include_jobs else [],
            status=MonitoringSnapshotStatus.LOADING,
            load_error="Loading live workflow state…",
            refreshing=refreshing,
        ).to_payload()

    def _build_snapshot_payload(
        self,
        *,
        project_root: str,
        agents: list[dict[str, Any]],
        workflow_blueprint: dict[str, Any],
        jobs: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        selected_run_id: str | None,
        selected_run: dict[str, Any] | None,
        status: MonitoringSnapshotStatus,
        load_failures: Iterable[RuntimeFailure] = (),
        load_error: str | None = None,
        refreshing: bool = False,
        stale: bool = False,
    ) -> dict[str, Any]:
        return MonitoringSnapshot(
            project_root=project_root,
            agents=agents,
            workflow_blueprint=workflow_blueprint,
            jobs=jobs,
            runs=runs,
            selected_run_id=selected_run_id,
            selected_run=selected_run,
            status=status,
            load_error=load_error,
            load_failures=tuple(load_failures),
            refreshing=refreshing,
            stale=stale,
        ).to_payload()

    def _snapshot_defaults(self, *, include_jobs: bool) -> dict[str, Any]:
        return {
            "project_root": str(self.root),
            "agents": [],
            "workflow_blueprint": {"name": None, "version": None, "entrypoint": None, "roles": [], "templates": []},
            "jobs": self.jobs() if include_jobs else [],
            "runs": [],
            "selected_run_id": None,
            "selected_run": None,
        }

    def _snapshot_request_key(self, *, limit: int, include_jobs: bool) -> tuple[int, bool]:
        return (limit, include_jobs)

    def _ensure_snapshot_refresh(self, *, limit: int, include_jobs: bool) -> Thread | None:
        request_key = self._snapshot_request_key(limit=limit, include_jobs=include_jobs)
        with self._lock:
            if request_key in self._snapshot_refreshing:
                return None
            self._snapshot_refreshing.add(request_key)
        thread = Thread(
            target=self._refresh_snapshot, kwargs={"limit": limit, "include_jobs": include_jobs}, daemon=True
        )
        thread.start()
        return thread

    def _refresh_snapshot(self, *, limit: int, include_jobs: bool) -> None:
        request_key = self._snapshot_request_key(limit=limit, include_jobs=include_jobs)
        payload = self._compute_snapshot(limit=limit, include_jobs=include_jobs)
        with self._lock:
            self._snapshot_cache[request_key] = payload
            self._snapshot_refreshing.discard(request_key)

    def _compute_snapshot(self, *, limit: int = 5, include_jobs: bool = True) -> dict[str, Any]:
        snapshot_defaults = self._snapshot_defaults(include_jobs=include_jobs)
        base_failures: list[RuntimeFailure] = []
        settings = LocalEnvironmentSettings.load(root=self.root, environ=self.environ)
        runtime_payload: dict[str, Any] = {
            "project_root": str(settings.project_root),
            "runs": [],
            "selected_run_id": None,
            "selected_run": None,
        }
        try:
            snapshot_defaults["agents"] = self.agent_catalog()
        except Exception as exc:
            base_failures.append(
                _runtime_failure(
                    exc,
                    code=RuntimeErrorCode.AGENT_CATALOG_UNAVAILABLE,
                    recoverable=True,
                    details_json={"phase": "agent_catalog"},
                )
            )
        try:
            snapshot_defaults["workflow_blueprint"] = self.workflow_blueprint()
        except Exception as exc:
            base_failures.append(
                _runtime_failure(
                    exc,
                    code=RuntimeErrorCode.WORKFLOW_BLUEPRINT_UNAVAILABLE,
                    recoverable=True,
                    details_json={"phase": "workflow_blueprint"},
                )
            )
        if (
            self._can_short_circuit_clean_sqlite
            and self.root == settings.project_root
            and settings.autoweave_canonical_backend == "sqlite"
            and not (settings.state_dir() / "autoweave.sqlite3").exists()
        ):
            return self._build_snapshot_payload(
                project_root=str(runtime_payload["project_root"]),
                agents=list(snapshot_defaults["agents"]),
                workflow_blueprint=dict(snapshot_defaults["workflow_blueprint"]),
                jobs=list(snapshot_defaults["jobs"]),
                runs=[],
                selected_run_id=None,
                selected_run=None,
                status=MonitoringSnapshotStatus.DEGRADED if base_failures else MonitoringSnapshotStatus.OK,
                load_failures=base_failures,
            )
        try:
            with self._runtime() as runtime:
                repository = runtime.storage.workflow_repository
                runs = repository.list_workflow_runs()[:limit]
                run_payloads = [
                    self._run_payload(
                        runtime=runtime,
                        workflow_run=workflow_run,
                        tasks=repository.list_tasks_for_run(workflow_run.id),
                        attempts=repository.list_attempts_for_run(workflow_run.id),
                        human_requests=repository.list_human_requests_for_run(workflow_run.id),
                        approval_requests=repository.list_approval_requests_for_run(workflow_run.id),
                        artifacts=repository.list_artifacts_for_run(workflow_run.id),
                        events=repository.list_events(workflow_run.id),
                    )
                    for workflow_run in runs
                ]
                run_payloads.sort(key=self._run_sort_key)
                selected_run = run_payloads[0] if run_payloads else None
                runtime_payload.update(
                    {
                        "project_root": str(runtime.settings.project_root),
                        "runs": run_payloads,
                        "selected_run_id": selected_run["id"] if selected_run is not None else None,
                        "selected_run": selected_run,
                    }
                )
        except Exception as exc:
            combined_failures = [
                *base_failures,
                _runtime_failure(
                    exc,
                    code=RuntimeErrorCode.RUNTIME_UNAVAILABLE,
                    recoverable=True,
                    details_json={"phase": "snapshot_runtime"},
                ),
            ]
            return self._build_snapshot_payload(
                project_root=str(runtime_payload["project_root"]),
                agents=list(snapshot_defaults["agents"]),
                workflow_blueprint=dict(snapshot_defaults["workflow_blueprint"]),
                jobs=list(snapshot_defaults["jobs"]),
                runs=list(runtime_payload["runs"]),
                selected_run_id=runtime_payload["selected_run_id"],
                selected_run=runtime_payload["selected_run"],
                status=MonitoringSnapshotStatus.DEGRADED,
                load_failures=combined_failures,
            )
        return self._build_snapshot_payload(
            project_root=str(runtime_payload["project_root"]),
            agents=list(snapshot_defaults["agents"]),
            workflow_blueprint=dict(snapshot_defaults["workflow_blueprint"]),
            jobs=list(snapshot_defaults["jobs"]),
            runs=list(runtime_payload["runs"]),
            selected_run_id=runtime_payload["selected_run_id"],
            selected_run=runtime_payload["selected_run"],
            status=MonitoringSnapshotStatus.DEGRADED if base_failures else MonitoringSnapshotStatus.OK,
            load_failures=base_failures,
        )

    def jobs(self) -> list[dict[str, Any]]:
        self._refresh_queue_jobs()
        with self._lock:
            jobs = [job.to_payload() for job in self._jobs.values()]
        jobs.sort(key=lambda item: item["id"], reverse=True)
        return jobs

    def launch_workflow(self, *, request: str, dispatch: bool = True, max_steps: int = 8) -> dict[str, Any]:
        return self._enqueue_job(action="start", request=request, dispatch=dispatch, max_steps=max_steps)

    def answer_human_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        answer_text: str,
        dispatch: bool = True,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        return self._enqueue_job(
            action="answer_human",
            request=answer_text,
            workflow_run_id=workflow_run_id,
            human_request_id=request_id,
            dispatch=dispatch,
            max_steps=max_steps,
        )

    def resolve_approval_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        approved: bool,
        dispatch: bool = True,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        return self._enqueue_job(
            action="resolve_approval",
            request="approve" if approved else "reject",
            workflow_run_id=workflow_run_id,
            approval_request_id=request_id,
            approved=approved,
            dispatch=dispatch,
            max_steps=max_steps,
        )

    def _enqueue_job(
        self,
        *,
        action: str,
        request: str,
        dispatch: bool,
        max_steps: int,
        workflow_run_id: str | None = None,
        human_request_id: str | None = None,
        approval_request_id: str | None = None,
        approved: bool | None = None,
    ) -> dict[str, Any]:
        job = MonitoringJob(
            id=generate_id("job"),
            action=action,
            request=request,
            dispatch=dispatch,
            max_steps=max_steps,
            workflow_run_id=workflow_run_id,
            human_request_id=human_request_id,
            approval_request_id=approval_request_id,
            approved=approved,
        )
        dispatcher = self._queue_dispatcher() if dispatch else None
        if dispatcher is not None:
            receipt = self._enqueue_celery_job(dispatcher=dispatcher, job=job)
            with self._lock:
                self._jobs[job.id] = job
            return receipt
        with self._lock:
            self._jobs[job.id] = job
        thread = Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job.to_payload()

    def _queue_dispatcher(self) -> CeleryWorkflowDispatcher | None:
        if self._runtime_factory is not build_local_runtime:
            return None
        try:
            dispatcher = CeleryWorkflowDispatcher(root=self.root, environ=self.environ)
        except Exception:
            return None
        if not celery_execution_enabled(dispatcher.runtime_config):
            return None
        if not dispatcher.worker_health().startswith("ok"):
            return None
        return dispatcher

    def _enqueue_celery_job(self, *, dispatcher: CeleryWorkflowDispatcher, job: MonitoringJob) -> dict[str, Any]:
        if job.action == "start":
            receipt = dispatcher.enqueue_new_workflow(
                request=job.request,
                dispatch=job.dispatch,
                max_steps=job.max_steps,
            )
        elif job.action == "answer_human":
            receipt = dispatcher.enqueue_workflow_action(
                action="answer_human",
                workflow_run_id=job.workflow_run_id or "",
                request=job.request,
                dispatch=job.dispatch,
                max_steps=job.max_steps,
                human_request_id=job.human_request_id,
            )
        elif job.action == "resolve_approval":
            receipt = dispatcher.enqueue_workflow_action(
                action="resolve_approval",
                workflow_run_id=job.workflow_run_id or "",
                request=job.request,
                dispatch=job.dispatch,
                max_steps=job.max_steps,
                approval_request_id=job.approval_request_id,
                approved=job.approved,
            )
        else:  # pragma: no cover - defensive guard
            raise ValueError(f"unknown monitoring action {job.action!r}")

        job.status = receipt.status
        job.workflow_run_id = receipt.workflow_run_id
        job.celery_task_id = receipt.celery_task_id
        job.queue_backend = receipt.backend
        job.queue = receipt.queue
        return job.to_payload()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            action = job.action
            request = job.request
            dispatch = job.dispatch
            max_steps = job.max_steps
            workflow_run_id = job.workflow_run_id
            human_request_id = job.human_request_id
            approval_request_id = job.approval_request_id
            approved = job.approved

        try:
            with self._runtime(workflow_run_id=workflow_run_id) as runtime:
                if action == "start":
                    report = runtime.run_workflow(request=request, dispatch=dispatch, max_steps=max_steps)
                elif action == "answer_human":
                    report = runtime.answer_human_request(
                        workflow_run_id=workflow_run_id or "",
                        request_id=human_request_id or "",
                        answer_text=request,
                        answered_by="operator",
                        dispatch=dispatch,
                        max_steps=max_steps,
                    )
                elif action == "resolve_approval":
                    report = runtime.resolve_approval_request(
                        workflow_run_id=workflow_run_id or "",
                        request_id=approval_request_id or "",
                        approved=bool(approved),
                        resolved_by="operator",
                        dispatch=dispatch,
                        max_steps=max_steps,
                    )
                else:  # pragma: no cover - defensive guard
                    raise RuntimeOperationError(
                        code=RuntimeErrorCode.INVALID_ACTION,
                        message=f"unknown monitoring action {action!r}",
                        details_json={"action": action},
                    )
            with self._lock:
                job = self._jobs[job_id]
                job.report = report
                job.workflow_run_id = report.workflow_run_id
                if report.open_human_questions:
                    job.status = "waiting_for_human"
                elif report.open_approval_reasons:
                    job.status = "waiting_for_approval"
                elif report.workflow_status == "failed":
                    job.status = "failed"
                else:
                    job.status = "completed"
        except Exception as exc:  # pragma: no cover - defensive live-path protection
            with self._lock:
                job = self._jobs[job_id]
                job.status = MonitoringJobStatus.ERROR.value
                job.failure = _runtime_failure(
                    exc,
                    code=RuntimeErrorCode.JOB_EXECUTION_FAILED,
                    recoverable=True,
                    details_json={
                        "action": action,
                        "workflow_run_id": workflow_run_id,
                        "human_request_id": human_request_id,
                        "approval_request_id": approval_request_id,
                    },
                )
                job.error = job.failure.message

    def _refresh_queue_jobs(self) -> None:
        dispatcher = self._queue_dispatcher()
        if dispatcher is None:
            return
        with self._lock:
            queued_jobs = [job for job in self._jobs.values() if job.celery_task_id]
        for job in queued_jobs:
            snapshot = dispatcher.inspect_task(job.celery_task_id or "")
            self._apply_celery_snapshot(job.id, snapshot)

    def _apply_celery_snapshot(self, job_id: str, snapshot: CeleryTaskSnapshot) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if snapshot.workflow_run_id and not job.workflow_run_id:
                job.workflow_run_id = snapshot.workflow_run_id
            if snapshot.report_payload is not None:
                job.report_payload = snapshot.report_payload
            if snapshot.error:
                job.error = snapshot.error
                job.failure = RuntimeFailure(
                    code=RuntimeErrorCode.JOB_EXECUTION_FAILED,
                    message=snapshot.error,
                    recoverable=True,
                    details_json={"backend": "celery", "task_id": snapshot.task_id},
                )
            state = snapshot.state.upper()
            if state in {"PENDING", "RECEIVED", "RETRY"}:
                job.status = MonitoringJobStatus.QUEUED.value
                return
            if state == "STARTED":
                job.status = MonitoringJobStatus.RUNNING.value
                return
            if state == "FAILURE":
                job.status = MonitoringJobStatus.FAILED.value
                return
            if state != "SUCCESS":
                job.status = state.lower()
                return

            report_payload = snapshot.report_payload or {}
            open_human = tuple(report_payload.get("open_human_questions", ()))
            open_approval = tuple(report_payload.get("open_approval_reasons", ()))
            workflow_status = str(report_payload.get("workflow_status", "running"))
            if open_human:
                job.status = MonitoringJobStatus.WAITING_FOR_HUMAN.value
            elif open_approval:
                job.status = MonitoringJobStatus.WAITING_FOR_APPROVAL.value
            elif workflow_status == "failed":
                job.status = MonitoringJobStatus.FAILED.value
            else:
                job.status = MonitoringJobStatus.COMPLETED.value

    def _run_payload(
        self,
        *,
        runtime: Any,
        workflow_run: WorkflowRunRecord,
        tasks: list[TaskRecord],
        attempts: list[TaskAttemptRecord],
        human_requests: list[HumanRequestRecord],
        approval_requests: list[ApprovalRequestRecord],
        artifacts: list[ArtifactRecord],
        events: list[EventRecord],
    ) -> dict[str, Any]:
        tasks_by_id = {task.id: task for task in tasks}
        task_templates_by_key = {template.key: template for template in runtime.workflow_definition.task_templates}
        latest_attempt_by_task_id: dict[str, TaskAttemptRecord] = {}
        for attempt in attempts:
            current = latest_attempt_by_task_id.get(attempt.task_id)
            if current is None or attempt.attempt_number >= current.attempt_number:
                latest_attempt_by_task_id[attempt.task_id] = attempt

        manager_task = self._manager_task(tasks=tasks)
        manager_latest_attempt = latest_attempt_by_task_id.get(manager_task.id) if manager_task is not None else None
        manager_plan = self._manager_plan(runtime=runtime, tasks=tasks, artifacts=artifacts)
        manager_summary = self._manager_summary(runtime=runtime, tasks=tasks, artifacts=artifacts)
        manager_outcome = self._manager_outcome(
            manager_task=manager_task,
            latest_attempt=manager_latest_attempt,
            summary=manager_summary,
        )

        grouped_artifacts: dict[str, list[ArtifactRecord]] = {}
        for artifact in artifacts:
            grouped_artifacts.setdefault(artifact.task_id, []).append(artifact)

        task_payloads = []
        for task in tasks:
            latest_attempt = latest_attempt_by_task_id.get(task.id)
            template = task_templates_by_key.get(task.task_key)
            worker_status, worker_summary, attempt_display_state, has_active_worker = self._task_execution_projection(
                task=task,
                latest_attempt=latest_attempt,
            )
            task_payloads.append(
                {
                    "id": task.id,
                    "task_key": task.task_key,
                    "title": task.title,
                    "assigned_role": task.assigned_role,
                    "state": task.state.value,
                    "block_reason": task.block_reason,
                    "input_json": task.input_json,
                    "output_json": task.output_json,
                    "description": task.description,
                    "required_artifact_types": list(task.required_artifact_types_json),
                    "produced_artifact_types": list(task.produced_artifact_types_json),
                    "hard_dependencies": list(getattr(template, "hard_dependencies", []))
                    if template is not None
                    else [],
                    "soft_dependencies": list(getattr(template, "soft_dependencies", []))
                    if template is not None
                    else [],
                    "route_hints": list(getattr(template, "route_hints", [])) if template is not None else [],
                    "latest_attempt_id": latest_attempt.id if latest_attempt else None,
                    "latest_attempt_state": latest_attempt.state.value if latest_attempt else None,
                    "attempt_display_state": attempt_display_state,
                    "workspace_id": latest_attempt.workspace_id if latest_attempt else None,
                    "workspace_path": (
                        latest_attempt.compiled_worker_config_json.get("workspace_path")
                        if latest_attempt is not None
                        else None
                    ),
                    "model_name": (
                        latest_attempt.compiled_worker_config_json.get("model_name")
                        if latest_attempt is not None
                        else None
                    ),
                    "worker_status": worker_status,
                    "worker_summary": worker_summary,
                    "has_active_worker": has_active_worker,
                    "artifact_types": [artifact.artifact_type for artifact in grouped_artifacts.get(task.id, [])],
                }
            )

        run_steps = [
            {
                "index": index + 1,
                "task_key": task.task_key,
                "title": task.title,
                "role": task.assigned_role,
                "state": task.state.value,
                "attempt_state": (
                    latest_attempt_by_task_id[task.id].state.value if task.id in latest_attempt_by_task_id else None
                ),
                "block_reason": task.block_reason,
                "input_json": task.input_json,
                "output_json": task.output_json,
                "produced_artifacts": [artifact.artifact_type for artifact in grouped_artifacts.get(task.id, [])],
            }
            for index, task in enumerate(tasks)
        ]

        attempts_payload = [
            {
                "id": attempt.id,
                "task_id": attempt.task_id,
                "task_key": tasks_by_id.get(attempt.task_id).task_key if attempt.task_id in tasks_by_id else None,
                "attempt_number": attempt.attempt_number,
                "state": attempt.state.value,
                "workspace_id": attempt.workspace_id,
                "workspace_path": attempt.compiled_worker_config_json.get("workspace_path"),
                "model_name": attempt.compiled_worker_config_json.get("model_name"),
            }
            for attempt in attempts
        ]

        artifact_payloads = [
            {
                "id": artifact.id,
                "task_id": artifact.task_id,
                "task_key": tasks_by_id.get(artifact.task_id).task_key if artifact.task_id in tasks_by_id else None,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "summary": artifact.summary,
                "status": artifact.status.value,
                "storage_uri": artifact.storage_uri,
            }
            for artifact in artifacts
        ]

        human_payloads = [
            {
                "id": request.id,
                "task_id": request.task_id,
                "task_key": tasks_by_id.get(request.task_id).task_key if request.task_id in tasks_by_id else None,
                "status": request.status.value,
                "question": request.question,
                "answer_text": request.answer_text,
            }
            for request in human_requests
        ]
        approval_payloads = [
            {
                "id": request.id,
                "task_id": request.task_id,
                "task_key": tasks_by_id.get(request.task_id).task_key if request.task_id in tasks_by_id else None,
                "status": request.status.value,
                "reason": request.reason,
            }
            for request in approval_requests
        ]
        event_payloads = [
            {
                "id": event.id,
                "sequence_no": event.sequence_no,
                "event_type": event.event_type,
                "source": event.source,
                "agent_role": event.agent_role,
                "model_name": event.model_name,
                "task_attempt_id": event.task_attempt_id,
                "message": str(event.payload_json.get("message", "")),
            }
            for event in events[-15:]
        ]
        task_state_counts = _count_states(task["state"] for task in task_payloads)
        attempt_state_counts = _count_states(attempt["state"] for attempt in attempts_payload)
        ready_task_keys = tuple(task["task_key"] for task in task_payloads if task["state"] == "ready")
        blocked_task_keys = tuple(task["task_key"] for task in task_payloads if task["state"] == "blocked")
        failed_task_keys = tuple(task["task_key"] for task in task_payloads if task["state"] == "failed")
        operator_status, operator_summary = self._derive_operator_status(
            workflow_status=workflow_run.status.value,
            task_payloads=task_payloads,
            human_requests=human_payloads,
            approval_requests=approval_payloads,
            attempts_payload=attempts_payload,
        )
        execution_status, execution_summary, active_attempt_task_keys = self._derive_execution_status(
            workflow_status=workflow_run.status.value,
            task_payloads=task_payloads,
            human_requests=human_payloads,
            approval_requests=approval_payloads,
            attempts_payload=attempts_payload,
        )
        run_title = str(workflow_run.root_input_json.get("user_request", "")).strip() or workflow_run.id

        return {
            "id": workflow_run.id,
            "title": run_title,
            "status": workflow_run.status.value,
            "operator_status": operator_status,
            "operator_summary": operator_summary,
            "execution_status": execution_status,
            "execution_summary": execution_summary,
            "graph_revision": workflow_run.graph_revision,
            "started_at": _iso(workflow_run.started_at),
            "ended_at": _iso(workflow_run.ended_at),
            "root_input_json": workflow_run.root_input_json,
            "workflow_request": workflow_run.root_input_json.get("user_request"),
            "ready_task_keys": ready_task_keys,
            "blocked_task_keys": blocked_task_keys,
            "failed_task_keys": failed_task_keys,
            "active_attempt_task_keys": active_attempt_task_keys,
            "active_attempt_count": len(active_attempt_task_keys),
            "task_state_counts": task_state_counts,
            "attempt_state_counts": attempt_state_counts,
            "manager_plan": manager_plan,
            "manager_summary": manager_summary,
            "manager_outcome": manager_outcome,
            "manager_task_state": manager_task.state.value if manager_task is not None else None,
            "manager_attempt_state": (
                manager_latest_attempt.state.value if manager_latest_attempt is not None else None
            ),
            "run_steps": run_steps,
            "tasks": task_payloads,
            "attempts": attempts_payload,
            "artifacts": artifact_payloads,
            "human_requests": human_payloads,
            "approval_requests": approval_payloads,
            "events": event_payloads,
            "chat_messages": self._chat_messages(
                workflow_run=workflow_run,
                manager_plan=manager_plan,
                manager_summary=manager_summary,
                manager_outcome=manager_outcome,
                human_requests=human_payloads,
                approval_requests=approval_payloads,
                run_steps=run_steps,
            ),
        }

    def _chat_messages(
        self,
        *,
        workflow_run: WorkflowRunRecord,
        manager_plan: str | None,
        manager_summary: str | None,
        manager_outcome: str | None,
        human_requests: list[dict[str, Any]],
        approval_requests: list[dict[str, Any]],
        run_steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        user_request = str(workflow_run.root_input_json.get("user_request", "")).strip()
        if user_request:
            messages.append({"id": f"{workflow_run.id}:user", "role": "user", "kind": "request", "text": user_request})
        if manager_plan:
            messages.append({"id": f"{workflow_run.id}:plan", "role": "manager", "kind": "plan", "text": manager_plan})
        elif manager_outcome:
            messages.append(
                {
                    "id": f"{workflow_run.id}:manager_outcome",
                    "role": "manager",
                    "kind": "execution_note",
                    "text": manager_outcome,
                    "status": "warning",
                }
            )
        if manager_summary and manager_summary != manager_plan and manager_summary != manager_outcome:
            messages.append(
                {"id": f"{workflow_run.id}:summary", "role": "manager", "kind": "summary", "text": manager_summary}
            )
        for request in human_requests:
            messages.append(
                {
                    "id": request["id"],
                    "role": "manager",
                    "kind": "human_request",
                    "text": request["question"],
                    "status": request["status"],
                    "answer_text": request["answer_text"],
                }
            )
            if request["answer_text"]:
                messages.append(
                    {
                        "id": f"{request['id']}:answer",
                        "role": "user",
                        "kind": "human_answer",
                        "text": request["answer_text"],
                        "status": request["status"],
                    }
                )
        for request in approval_requests:
            messages.append(
                {
                    "id": request["id"],
                    "role": "system",
                    "kind": "approval_request",
                    "text": request["reason"],
                    "status": request["status"],
                }
            )
        for step in run_steps:
            if step["state"] in {"waiting_for_dependency", "ready"}:
                continue
            messages.append(
                {
                    "id": f"{workflow_run.id}:step:{step['index']}",
                    "role": "system",
                    "kind": "state_update",
                    "text": f"{step['task_key']} -> {step['state']}",
                    "status": step["state"],
                    "task_key": step["task_key"],
                }
            )
        return messages

    def _manager_task(self, *, tasks: list[TaskRecord]) -> TaskRecord | None:
        manager_tasks = [task for task in tasks if task.assigned_role == "manager" or task.task_key == "manager_plan"]
        if not manager_tasks:
            return None
        manager_tasks.sort(key=lambda item: (item.task_key != "manager_plan", item.id))
        return manager_tasks[0]

    def _manager_plan(
        self,
        *,
        runtime: Any,
        tasks: list[TaskRecord],
        artifacts: list[ArtifactRecord],
    ) -> str | None:
        manager_task_ids = {
            task.id for task in tasks if task.assigned_role == "manager" or task.task_key == "manager_plan"
        }
        manager_tasks = [task for task in tasks if task.id in manager_task_ids]
        for task in manager_tasks:
            if task.state.value != "completed":
                continue
            if task.output_json:
                plan_text = _short_json(task.output_json)
                if plan_text != "none":
                    return plan_text

        manager_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.task_id in manager_task_ids and artifact.artifact_type == "workflow_plan"
        ]
        if not manager_artifacts:
            return None
        manager_artifacts.sort(key=lambda item: (_iso(item.created_at) or "", item.id), reverse=True)
        artifact = manager_artifacts[0]
        if artifact.artifact_type == "workflow_plan":
            try:
                manifest = runtime.storage.artifact_store.read_manifest(artifact.id)
            except KeyError:
                return artifact.summary
            payload = manifest.get("payload", {})
            if isinstance(payload, dict):
                return _short_json(payload)
            return str(payload)
        return None

    def _manager_summary(
        self,
        *,
        runtime: Any,
        tasks: list[TaskRecord],
        artifacts: list[ArtifactRecord],
    ) -> str | None:
        manager_task_ids = {
            task.id for task in tasks if task.assigned_role == "manager" or task.task_key == "manager_plan"
        }
        manager_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.task_id in manager_task_ids and artifact.artifact_type == "openhands_replay"
        ]
        if not manager_artifacts:
            return None
        manager_artifacts.sort(key=lambda item: (_iso(item.created_at) or "", item.id), reverse=True)
        artifact = manager_artifacts[0]
        try:
            manifest = runtime.storage.artifact_store.read_manifest(artifact.id)
        except KeyError:
            return artifact.summary
        payload = manifest.get("payload", {})
        if not isinstance(payload, dict):
            return artifact.summary
        events = payload.get("events", [])
        if isinstance(events, list):
            messages: list[str] = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                if event.get("kind") != "MessageEvent" or event.get("source") != "agent":
                    continue
                llm_message = event.get("llm_message") or {}
                content = llm_message.get("content") or []
                text_parts = [
                    part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
                ]
                if text_parts:
                    messages.append("\n".join(text_parts).strip())
            if messages:
                return messages[-1]
        return artifact.summary

    def _manager_outcome(
        self,
        *,
        manager_task: TaskRecord | None,
        latest_attempt: TaskAttemptRecord | None,
        summary: str | None,
    ) -> str | None:
        if manager_task is None:
            return None
        if manager_task.state.value == "completed":
            return summary
        if manager_task.block_reason:
            return manager_task.block_reason
        if manager_task.output_json:
            output_text = _short_json(manager_task.output_json)
            if output_text != "none":
                return output_text
        if summary:
            return summary
        if latest_attempt is not None:
            return f"latest attempt ended as {latest_attempt.state.value}"
        return None

    def _derive_operator_status(
        self,
        *,
        workflow_status: str,
        task_payloads: list[dict[str, Any]],
        human_requests: list[dict[str, Any]],
        approval_requests: list[dict[str, Any]],
        attempts_payload: list[dict[str, Any]],
    ) -> tuple[str, str]:
        open_human = [item for item in human_requests if item["status"] == "open"]
        open_approval = [item for item in approval_requests if item["status"] == "requested"]
        active_attempts = [
            attempt
            for attempt in attempts_payload
            if attempt["state"] in {"queued", "dispatching", "running", "paused", "needs_input"}
        ]
        blocked_tasks = [task for task in task_payloads if task["state"] == "blocked"]
        failed_tasks = [task for task in task_payloads if task["state"] == "failed"]
        ready_tasks = [task for task in task_payloads if task["state"] == "ready"]
        waiting_dependency = [task for task in task_payloads if task["state"] == "waiting_for_dependency"]

        if workflow_status in {"completed", "failed"}:
            if workflow_status == "failed" and failed_tasks:
                return "failed", f"{len(failed_tasks)} task(s) failed"
            return workflow_status, f"workflow is {workflow_status}"
        if open_human:
            return "waiting_for_human", f"waiting on {len(open_human)} human answer(s)"
        if open_approval:
            return "waiting_for_approval", f"waiting on {len(open_approval)} approval request(s)"
        if active_attempts:
            return "active", f"{len(active_attempts)} active attempt(s)"
        if failed_tasks:
            return "failed", f"{len(failed_tasks)} failed task(s)"
        if blocked_tasks:
            blocked = ", ".join(task["task_key"] for task in blocked_tasks[:3])
            suffix = "..." if len(blocked_tasks) > 3 else ""
            return "blocked", f"blocked by {blocked}{suffix}"
        if ready_tasks:
            ready = ", ".join(task["task_key"] for task in ready_tasks[:3])
            suffix = "..." if len(ready_tasks) > 3 else ""
            return "ready", f"ready to dispatch: {ready}{suffix}"
        if waiting_dependency:
            return "waiting_for_dependency", f"{len(waiting_dependency)} task(s) waiting on dependencies"
        return "stalled", "no active attempts and no runnable tasks"

    def _derive_execution_status(
        self,
        *,
        workflow_status: str,
        task_payloads: list[dict[str, Any]],
        human_requests: list[dict[str, Any]],
        approval_requests: list[dict[str, Any]],
        attempts_payload: list[dict[str, Any]],
    ) -> tuple[str, str, tuple[str, ...]]:
        open_human = [item for item in human_requests if item["status"] == "open"]
        open_approval = [item for item in approval_requests if item["status"] == "requested"]
        active_attempts = [attempt for attempt in attempts_payload if attempt["state"] in _ACTIVE_WORKER_ATTEMPT_STATES]
        active_task_keys = tuple(
            attempt["task_key"]
            for attempt in active_attempts
            if isinstance(attempt.get("task_key"), str) and attempt["task_key"]
        )
        ready_tasks = [task for task in task_payloads if task["state"] == "ready"]
        blocked_tasks = [task for task in task_payloads if task["state"] == "blocked"]
        failed_tasks = [task for task in task_payloads if task["state"] == "failed"]
        waiting_dependency = [task for task in task_payloads if task["state"] == "waiting_for_dependency"]

        if workflow_status == "completed":
            return "completed", "no active worker; workflow execution is complete", ()
        if workflow_status == "failed":
            return "failed", "no active worker; workflow ended in a failed state", ()
        if active_task_keys:
            joined = ", ".join(active_task_keys[:3])
            suffix = "..." if len(active_task_keys) > 3 else ""
            return "active", f"{len(active_task_keys)} active worker(s): {joined}{suffix}", active_task_keys
        if open_human:
            return "waiting_for_human", f"no active worker; waiting on {len(open_human)} human answer(s)", ()
        if open_approval:
            return "waiting_for_approval", f"no active worker; waiting on {len(open_approval)} approval request(s)", ()
        if ready_tasks:
            joined = ", ".join(task["task_key"] for task in ready_tasks[:3])
            suffix = "..." if len(ready_tasks) > 3 else ""
            return "ready", f"no active worker; ready to dispatch: {joined}{suffix}", ()
        if blocked_tasks:
            joined = ", ".join(task["task_key"] for task in blocked_tasks[:3])
            suffix = "..." if len(blocked_tasks) > 3 else ""
            return "blocked", f"no active worker; blocked by {joined}{suffix}", ()
        if failed_tasks:
            return "failed", f"no active worker; {len(failed_tasks)} task(s) failed", ()
        if waiting_dependency:
            return (
                "waiting_for_dependency",
                f"no active worker; {len(waiting_dependency)} task(s) waiting on dependencies",
                (),
            )
        return "idle", "no active worker", ()

    def _task_execution_projection(
        self,
        *,
        task: TaskRecord,
        latest_attempt: TaskAttemptRecord | None,
    ) -> tuple[str, str, str | None, bool]:
        task_state = task.state.value
        if latest_attempt is None:
            if task_state == "ready":
                return "ready", "Ready to dispatch. No worker is running yet.", None, False
            if task_state == "waiting_for_dependency":
                return "waiting_for_dependency", "No worker is running. Waiting on upstream dependencies.", None, False
            if task_state == "waiting_for_human":
                return "waiting_for_human", "No worker is running. Waiting on a human answer.", None, False
            if task_state == "waiting_for_approval":
                return "waiting_for_approval", "No worker is running. Waiting on approval before dispatch.", None, False
            if task_state == "completed":
                return "completed", "Execution finished successfully.", None, False
            if task_state == "failed":
                return "failed", "Execution finished with a failure.", None, False
            if task_state == "blocked":
                return "blocked", f"Execution is blocked: {task.block_reason or 'blocked'}", None, False
            return task_state, "No worker is running.", None, False

        attempt_state = latest_attempt.state.value
        has_active_worker = attempt_state in _ACTIVE_WORKER_ATTEMPT_STATES
        if has_active_worker:
            return "active", f"Worker is active in attempt {latest_attempt.attempt_number}.", attempt_state, True
        if task_state == "waiting_for_approval":
            return (
                "waiting_for_approval",
                "No worker is running. Dispatch is paused until approval is granted.",
                "approval_gate",
                False,
            )
        if task_state == "waiting_for_human":
            return (
                "waiting_for_human",
                "No worker is running. The task is waiting on human input.",
                "awaiting_human",
                False,
            )
        if task_state == "waiting_for_dependency":
            return (
                "waiting_for_dependency",
                "No worker is running. The task is waiting on dependencies.",
                "dependency_wait",
                False,
            )
        if task_state == "ready":
            return "ready", "No worker is running. The task is ready to dispatch.", "ready_to_dispatch", False
        if task_state == "completed":
            return "completed", "Execution finished successfully.", "completed", False
        if task_state == "failed":
            return "failed", "Execution finished with a failure.", attempt_state, False
        if task_state == "blocked":
            return "blocked", f"Execution is blocked: {task.block_reason or attempt_state}", attempt_state, False
        return task_state, f"No worker is running. Latest attempt is {attempt_state}.", attempt_state, False

    def _run_sort_key(self, payload: Mapping[str, Any]) -> tuple[int, str]:
        execution_status = str(payload.get("execution_status", "") or "")
        operator_status = str(payload.get("operator_status", "") or "")
        priority_map = {
            "active": 0,
            "ready": 1,
            "waiting_for_human": 2,
            "waiting_for_approval": 3,
            "blocked": 4,
            "waiting_for_dependency": 5,
            "idle": 6,
            "completed": 7,
            "failed": 8,
        }
        priority = priority_map.get(execution_status, priority_map.get(operator_status, 9))
        started_at = str(payload.get("started_at") or "")
        try:
            started_timestamp = datetime.fromisoformat(started_at).timestamp() if started_at else 0.0
        except ValueError:
            started_timestamp = 0.0
        return (priority, f"{-started_timestamp:020.3f}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _count_states(values: Iterable[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts
