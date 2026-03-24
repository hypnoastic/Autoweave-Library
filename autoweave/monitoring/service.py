"""Canonical workflow inspection and launch helpers for the local monitor UI."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Mapping
import yaml

from autoweave.local_runtime import LocalWorkflowRunReport, build_local_runtime
from autoweave.models import ArtifactRecord, ApprovalRequestRecord, EventRecord, HumanRequestRecord, TaskAttemptRecord, TaskRecord, WorkflowRunRecord, generate_id


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


@dataclass(slots=True)
class MonitoringJob:
    id: str
    request: str
    dispatch: bool
    max_steps: int
    status: str = "queued"
    workflow_run_id: str | None = None
    error: str | None = None
    report: LocalWorkflowRunReport | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "request": self.request,
            "dispatch": self.dispatch,
            "max_steps": self.max_steps,
            "status": self.status,
            "workflow_run_id": self.workflow_run_id,
            "error": self.error,
        }
        if self.report is not None:
            payload["summary_lines"] = self.report.summary_lines()
            payload["step_reports"] = [
                {
                    "task_key": step.task_key,
                    "task_state": step.task_state,
                    "attempt_state": step.attempt_state,
                    "route_model_name": step.route_model_name,
                    "failure_reason": step.failure_reason,
                }
                for step in self.report.step_reports
            ]
        return payload


class MonitoringService:
    """Read canonical run state and launch workflows for the local monitor UI."""

    def __init__(
        self,
        *,
        root: Path,
        environ: Mapping[str, str] | None = None,
        runtime_factory: Callable[..., Any] = build_local_runtime,
    ) -> None:
        self.root = root
        self.environ = dict(environ or {})
        self._runtime_factory = runtime_factory
        self._jobs: dict[str, MonitoringJob] = {}
        self._lock = Lock()

    def workflow_blueprint(self) -> dict[str, Any]:
        with self._runtime_factory(root=self.root, environ=self.environ) as runtime:
            templates = []
            for template in runtime.workflow_definition.task_templates:
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
                    }
                )
            return {
                "name": runtime.workflow_definition.name,
                "version": runtime.workflow_definition.version,
                "entrypoint": runtime.workflow_definition.entrypoint,
                "roles": list(runtime.workflow_definition.roles),
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
                path.name
                for path in (role_dir / "skills").glob("*.md")
                if path.is_file() and path.name != "README.md"
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
                    "playbook_goals": list(playbook.get("goals", [])),
                    "skill_files": skill_files,
                    "soul_excerpt": soul_text.splitlines()[2] if len(soul_text.splitlines()) >= 3 else soul_text.strip(),
                }
            )
        return agents

    def snapshot(self, *, limit: int = 5) -> dict[str, Any]:
        with self._runtime_factory(root=self.root, environ=self.environ) as runtime:
            repository = runtime.storage.workflow_repository
            runs = repository.list_workflow_runs()[:limit]
            return {
                "project_root": str(runtime.settings.project_root),
                "agents": self.agent_catalog(),
                "workflow_blueprint": self.workflow_blueprint(),
                "jobs": self.jobs(),
                "runs": [
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
                ],
            }

    def jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [job.to_payload() for job in self._jobs.values()]
        jobs.sort(key=lambda item: item["id"], reverse=True)
        return jobs

    def launch_workflow(self, *, request: str, dispatch: bool = True, max_steps: int = 8) -> dict[str, Any]:
        job = MonitoringJob(
            id=generate_id("job"),
            request=request,
            dispatch=dispatch,
            max_steps=max_steps,
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job.to_payload()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            request = job.request
            dispatch = job.dispatch
            max_steps = job.max_steps

        try:
            with self._runtime_factory(root=self.root, environ=self.environ) as runtime:
                report = runtime.run_workflow(request=request, dispatch=dispatch, max_steps=max_steps)
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
                job.status = "error"
                job.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()

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
        task_templates_by_key = {
            template.key: template
            for template in runtime.workflow_definition.task_templates
        }
        latest_attempt_by_task_id: dict[str, TaskAttemptRecord] = {}
        for attempt in attempts:
            current = latest_attempt_by_task_id.get(attempt.task_id)
            if current is None or attempt.attempt_number >= current.attempt_number:
                latest_attempt_by_task_id[attempt.task_id] = attempt

        grouped_artifacts: dict[str, list[ArtifactRecord]] = {}
        for artifact in artifacts:
            grouped_artifacts.setdefault(artifact.task_id, []).append(artifact)

        task_payloads = []
        for task in tasks:
            latest_attempt = latest_attempt_by_task_id.get(task.id)
            template = task_templates_by_key.get(task.task_key)
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
                    "route_hints": list(getattr(template, "route_hints", [])) if template is not None else [],
                    "latest_attempt_id": latest_attempt.id if latest_attempt else None,
                    "latest_attempt_state": latest_attempt.state.value if latest_attempt else None,
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
                    "artifact_types": [
                        artifact.artifact_type for artifact in grouped_artifacts.get(task.id, [])
                    ],
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
                    latest_attempt_by_task_id[task.id].state.value
                    if task.id in latest_attempt_by_task_id
                    else None
                ),
                "block_reason": task.block_reason,
                "input_json": task.input_json,
                "output_json": task.output_json,
                "produced_artifacts": [
                    artifact.artifact_type
                    for artifact in grouped_artifacts.get(task.id, [])
                ],
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

        return {
            "id": workflow_run.id,
            "status": workflow_run.status.value,
            "graph_revision": workflow_run.graph_revision,
            "started_at": _iso(workflow_run.started_at),
            "ended_at": _iso(workflow_run.ended_at),
            "root_input_json": workflow_run.root_input_json,
            "workflow_request": workflow_run.root_input_json.get("user_request"),
            "manager_plan": self._manager_plan(runtime=runtime, tasks=tasks, artifacts=artifacts),
            "manager_summary": self._manager_summary(runtime=runtime, tasks=tasks, artifacts=artifacts),
            "run_steps": run_steps,
            "tasks": task_payloads,
            "attempts": attempts_payload,
            "artifacts": artifact_payloads,
            "human_requests": human_payloads,
            "approval_requests": approval_payloads,
            "events": event_payloads,
        }

    def _manager_plan(
        self,
        *,
        runtime: Any,
        tasks: list[TaskRecord],
        artifacts: list[ArtifactRecord],
    ) -> str | None:
        manager_task_ids = {task.id for task in tasks if task.assigned_role == "manager" or task.task_key == "manager_plan"}
        manager_tasks = [task for task in tasks if task.id in manager_task_ids]
        for task in manager_tasks:
            if task.output_json:
                plan_text = _short_json(task.output_json)
                if plan_text != "none":
                    return plan_text
            if task.input_json:
                prompt_text = _short_json(task.input_json)
                if prompt_text != "none":
                    return prompt_text

        manager_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.task_id in manager_task_ids and artifact.artifact_type in {"workflow_plan", "openhands_replay"}
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
        return self._manager_summary(runtime=runtime, tasks=tasks, artifacts=artifacts)

    def _manager_summary(
        self,
        *,
        runtime: Any,
        tasks: list[TaskRecord],
        artifacts: list[ArtifactRecord],
    ) -> str | None:
        manager_task_ids = {task.id for task in tasks if task.assigned_role == "manager" or task.task_key == "manager_plan"}
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
                text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
                if text_parts:
                    messages.append("\n".join(text_parts).strip())
            if messages:
                return messages[-1]
        return artifact.summary


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
