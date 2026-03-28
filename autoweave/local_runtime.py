"""Terminal-first local runtime composition for AutoWeave."""

from __future__ import annotations

import threading
import json
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from autoweave.compiler.loader import CanonicalConfigLoader
from autoweave.events.service import EventService
from autoweave.models import (
    ApprovalStatus,
    AttemptState,
    ArtifactRecord,
    ArtifactStatus,
    EdgeType,
    EventRecord,
    HumanRequestRecord,
    HumanRequestStatus,
    HumanRequestType,
    MemoryEntryRecord,
    MemoryLayer,
    TaskEdgeRecord,
    TaskAttemptRecord,
    TaskRecord,
    TaskState,
    generate_id,
)
from autoweave.observability import LocalObservabilityService
from autoweave.orchestration.service import OrchestrationService
from autoweave.orchestration.state import WorkflowRunState
from autoweave.routing.policy import VertexModelRouter
from autoweave.settings import LocalEnvironmentSettings
from autoweave.storage import LocalStorageWiring, build_local_storage_wiring
from autoweave.workers.runtime import (
    OpenHandsAgentServerClient,
    OpenHandsRemoteWorkerAdapter,
    OpenHandsServiceCall,
    OpenHandsStreamEvent,
    extract_semantic_clarification_questions,
    extract_openhands_stream_events,
    normalize_openhands_stream_event,
    stream_event_to_artifact,
    WorkspacePolicy,
)
from autoweave.workflows import build_workflow_graph
from autoweave.config_models import (
    AgentDefinitionConfig,
    ObservabilityConfig,
    RuntimeConfig,
    StorageConfig,
    TaskTemplateConfig,
    VertexConfig,
    WorkflowDefinitionConfig,
)
from autoweave.events.schema import EventCorrelationContext, make_event
from autoweave.types import JsonDict


@dataclass(slots=True, frozen=True)
class LocalRuntimeDoctorReport:
    project_root: Path
    loaded_env_files: tuple[Path, ...]
    config_paths: dict[str, Path]
    vertex_worker_env: dict[str, str]
    canonical_backend: str
    graph_backend: str
    execution_backend: str
    postgres_target: str
    neo4j_target: str
    redis_target: str
    artifact_store_path: Path
    postgres_health: str
    neo4j_health: str
    redis_health: str
    artifact_store_health: str
    celery_health: str
    openhands_target: str
    openhands_health: OpenHandsServiceCall
    openhands_worker_timeout_seconds: int
    openhands_poll_timeout_seconds: int
    ready_task_keys: tuple[str, ...]

    def summary_lines(self) -> list[str]:
        lines = [
            f"root={self.project_root}",
            f"env_files={', '.join(str(path) for path in self.loaded_env_files) or 'none'}",
            f"workflow={self.config_paths['workflow']}",
            f"vertex_credentials={self.vertex_worker_env['GOOGLE_APPLICATION_CREDENTIALS']}",
            f"canonical_backend={self.canonical_backend}",
            f"graph_backend={self.graph_backend}",
            f"execution_backend={self.execution_backend}",
            f"postgres={self.postgres_target}",
            f"postgres_health={self.postgres_health}",
            f"neo4j={self.neo4j_target}",
            f"neo4j_health={self.neo4j_health}",
            f"redis={self.redis_target}",
            f"redis_health={self.redis_health}",
            f"artifact_store={self.artifact_store_path}",
            f"artifact_store_health={self.artifact_store_health}",
            f"celery_health={self.celery_health}",
            f"openhands={self.openhands_target}",
            f"openhands_health={'ok' if self.openhands_health.ok else 'unreachable'}",
            f"openhands_worker_timeout_seconds={self.openhands_worker_timeout_seconds}",
            f"openhands_poll_timeout_seconds={self.openhands_poll_timeout_seconds}",
            f"ready_tasks={', '.join(self.ready_task_keys) or 'none'}",
        ]
        if self.openhands_health.error:
            lines.append(f"openhands_health_error={self.openhands_health.error}")
        return lines


@dataclass(slots=True, frozen=True)
class LocalExampleRunReport:
    workflow_run_id: str
    task_key: str
    ready_task_keys: tuple[str, ...]
    route_model_name: str
    launch_payload: JsonDict
    openhands_health: OpenHandsServiceCall
    bootstrap_call: OpenHandsServiceCall | None
    published_event: EventRecord
    task_state: str
    attempt_state: str
    workflow_status: str
    stream_event_types: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    failure_reason: str | None = None

    def summary_lines(self) -> list[str]:
        lines = [
            f"workflow_run_id={self.workflow_run_id}",
            f"task_key={self.task_key}",
            f"ready_tasks={', '.join(self.ready_task_keys) or 'none'}",
            f"route_model_name={self.route_model_name}",
            f"launch_provider={self.launch_payload.get('provider_name', 'unknown')}",
            f"launch_workspace={self.launch_payload.get('workspace_path', 'unknown')}",
            f"openhands_health={'ok' if self.openhands_health.ok else 'unreachable'}",
            f"task_state={self.task_state}",
            f"attempt_state={self.attempt_state}",
            f"workflow_status={self.workflow_status}",
        ]
        if self.bootstrap_call is not None:
            lines.append(f"bootstrap_call={'ok' if self.bootstrap_call.ok else 'failed'}")
        lines.append(f"event_type={self.published_event.event_type}")
        lines.append(f"stream_events={', '.join(self.stream_event_types) or 'none'}")
        lines.append(f"artifact_ids={', '.join(self.artifact_ids) or 'none'}")
        if self.failure_reason:
            lines.append(f"failure_reason={self.failure_reason}")
        return lines


@dataclass(slots=True, frozen=True)
class LocalTaskRunReport:
    workflow_run_id: str
    task_key: str
    route_model_name: str
    launch_payload: JsonDict
    openhands_health: OpenHandsServiceCall
    bootstrap_call: OpenHandsServiceCall | None
    published_event: EventRecord
    task_state: str
    attempt_state: str
    workflow_status: str
    stream_event_types: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    failure_reason: str | None = None


@dataclass(slots=True, frozen=True)
class LocalWorkflowRunReport:
    workflow_run_id: str
    request: str
    workflow_status: str
    dispatched_task_keys: tuple[str, ...]
    ready_task_keys: tuple[str, ...]
    open_human_questions: tuple[str, ...]
    open_approval_reasons: tuple[str, ...]
    step_reports: tuple[LocalTaskRunReport, ...]

    def summary_lines(self) -> list[str]:
        lines = [
            f"workflow_run_id={self.workflow_run_id}",
            f"request={self.request}",
            f"workflow_status={self.workflow_status}",
            f"dispatched_tasks={', '.join(self.dispatched_task_keys) or 'none'}",
            f"ready_tasks={', '.join(self.ready_task_keys) or 'none'}",
            f"open_human_questions={len(self.open_human_questions)}",
            f"open_approval_requests={len(self.open_approval_reasons)}",
        ]
        for index, step in enumerate(self.step_reports, start=1):
            lines.append(
                "step_"
                f"{index}={step.task_key}:{step.task_state}:{step.attempt_state}:{step.route_model_name}"
            )
            if step.failure_reason:
                lines.append(f"step_{index}_failure={step.failure_reason}")
        for index, question in enumerate(self.open_human_questions, start=1):
            lines.append(f"human_question_{index}={question}")
        for index, reason in enumerate(self.open_approval_reasons, start=1):
            lines.append(f"approval_reason_{index}={reason}")
        return lines


@dataclass(slots=True, frozen=True)
class LocalCleanupReport:
    selected_run_ids: tuple[str, ...]
    purged_run_ids: tuple[str, ...]
    missing_run_ids: tuple[str, ...]
    deleted_paths: tuple[Path, ...]
    projection_cleared: bool

    def summary_lines(self) -> list[str]:
        lines = [
            f"selected_runs={len(self.selected_run_ids)}",
            f"purged_runs={len(self.purged_run_ids)}",
            f"missing_runs={len(self.missing_run_ids)}",
            f"projection_cleared={'yes' if self.projection_cleared else 'no'}",
        ]
        if self.purged_run_ids:
            lines.append(f"purged_run_ids={', '.join(self.purged_run_ids)}")
        if self.missing_run_ids:
            lines.append(f"missing_run_ids={', '.join(self.missing_run_ids)}")
        for path in self.deleted_paths:
            lines.append(f"deleted_path={path}")
        return lines


@dataclass(slots=True)
class LocalRuntime:
    settings: LocalEnvironmentSettings
    runtime_config: RuntimeConfig
    storage_config: StorageConfig
    vertex_config: VertexConfig
    observability_config: ObservabilityConfig
    workflow_definition: WorkflowDefinitionConfig
    agent_definitions: dict[str, AgentDefinitionConfig]
    storage: LocalStorageWiring
    router: VertexModelRouter
    event_service: EventService
    observability: LocalObservabilityService
    worker_adapter: OpenHandsRemoteWorkerAdapter
    openhands_client: OpenHandsAgentServerClient
    orchestration: OrchestrationService
    _last_persisted_graph_signature: tuple[str, int, tuple[str, ...], tuple[str, ...]] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _runtime_lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )

    @classmethod
    def build(
        cls,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        transport: Any | None = None,
        bootstrap_path: str = "/api/conversations",
        workflow_run_id: str | None = None,
    ) -> "LocalRuntime":
        settings = LocalEnvironmentSettings.load(root=root, environ=environ)
        settings.ensure_local_layout()

        loader = CanonicalConfigLoader(root_dir=settings.project_root)
        runtime_config = loader.load_runtime_config(settings.autoweave_runtime_config)
        storage_config = loader.load_storage_config(settings.autoweave_storage_config)
        vertex_config = loader.load_vertex_config(settings.autoweave_vertex_config)
        observability_config = loader.load_observability_config(settings.autoweave_observability_config)
        workflow_definition = loader.load_workflow_definition(settings.autoweave_default_workflow)
        agent_definitions = {
            role: loader.load_agent_definition(Path("agents") / role / "autoweave.yaml")
            for role in workflow_definition.roles
        }

        workflow_graph = build_workflow_graph(
            workflow_definition,
            project_id="local",
            team_id="local",
            workflow_definition_id=f"{workflow_definition.name}:{workflow_definition.version}",
            workflow_run_id=workflow_run_id,
        )

        storage = build_local_storage_wiring(settings)
        loaded_from_repository = True
        if workflow_run_id is not None:
            canonical_graph = storage.workflow_repository.get_graph(workflow_run_id)
        else:
            try:
                canonical_graph = storage.workflow_repository.get_graph(workflow_graph.workflow_run.id)
            except KeyError:
                canonical_graph = workflow_graph
                loaded_from_repository = False
        router = VertexModelRouter(
            vertex_config,
            preferred_profile=settings.autoweave_vertex_profile_override,
        )
        observability = LocalObservabilityService.from_settings(settings)
        event_service = observability.event_service
        worker_adapter = OpenHandsRemoteWorkerAdapter(
            vertex_config=vertex_config,
            workspace_policy=WorkspacePolicy(root_dir=settings.project_root / "workspaces"),
            service_account_file=settings.vertex_service_account_file,
        )
        openhands_client = OpenHandsAgentServerClient(
            base_url=settings.openhands_target().base_url,
            api_key=settings.openhands_target().api_key,
            timeout_seconds=float(settings.openhands_worker_timeout_seconds),
            transport=transport,
            bootstrap_path=bootstrap_path,
        )
        orchestration = OrchestrationService(WorkflowRunState.from_graph(canonical_graph))
        runtime = cls(
            settings=settings,
            runtime_config=runtime_config,
            storage_config=storage_config,
            vertex_config=vertex_config,
            observability_config=observability_config,
            workflow_definition=workflow_definition,
            agent_definitions=agent_definitions,
            storage=storage,
            router=router,
            event_service=event_service,
            observability=observability,
            worker_adapter=worker_adapter,
            openhands_client=openhands_client,
            orchestration=orchestration,
        )
        runtime._last_persisted_graph_signature = (
            runtime._graph_structure_signature() if loaded_from_repository else None
        )
        return runtime

    def close(self) -> None:
        self.openhands_client.close()

    def __enter__(self) -> "LocalRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def runtime_policy(self) -> dict[str, Any]:
        return {
            "vertex_project": self.settings.vertexai_project,
            "vertex_location": self.settings.vertexai_location,
            "reasoning_effort": "none" if self.vertex_config.provider_name == "VertexAI" else "medium",
            "permission_mode": "workspace-write",
            "tool_groups": ["context", "artifacts", "approvals"],
            "mcp_servers": [self.settings.openhands_agent_server_base_url],
        }

    def agent_definition(self, role: str) -> AgentDefinitionConfig:
        return self.agent_definitions[role]

    def load_workflow_run(self, workflow_run_id: str) -> None:
        canonical_graph = self.storage.workflow_repository.get_graph(workflow_run_id)
        state = WorkflowRunState.from_graph(canonical_graph)
        repository = self.storage.workflow_repository
        for attempt in repository.list_attempts_for_run(workflow_run_id):
            state.record_attempt(attempt)
        for request in repository.list_human_requests_for_run(workflow_run_id):
            state.human_requests[request.id] = request.model_copy(deep=True)
        for request in repository.list_approval_requests_for_run(workflow_run_id):
            state.approval_requests[request.id] = request.model_copy(deep=True)
        self.orchestration = OrchestrationService(state)
        self._last_persisted_graph_signature = self._graph_structure_signature()

    def _workflow_request(self) -> str:
        with self._runtime_lock:
            return str(self.orchestration.state.graph.workflow_run.root_input_json.get("user_request", "")).strip()

    def _autonomy_level(self) -> str:
        level = self.settings.autoweave_autonomy_level.strip().lower()
        if level not in {"low", "medium", "high"}:
            return "medium"
        return level

    def _operator_policy(self, task: TaskRecord) -> dict[str, str]:
        autonomy_level = self._autonomy_level()
        if task.assigned_role == "manager":
            if autonomy_level == "low":
                clarification_expectation = "ask_for_human_input_on_minor_scope_uncertainty"
            elif autonomy_level == "high":
                clarification_expectation = "ask_for_human_input_only_on_hard_blockers"
            else:
                clarification_expectation = "ask_for_human_input_on_material_scope_gaps"
        else:
            clarification_expectation = "follow_manager_scope_and_only_escalate_true_blockers"
        return {
            "autonomy_level": autonomy_level,
            "clarification_expectation": clarification_expectation,
        }

    @staticmethod
    def _truncate_text(value: str, *, max_chars: int = 600) -> str:
        normalized = " ".join(str(value).split()).strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _normalize_question_key(question: str) -> str:
        normalized = " ".join(str(question).split()).strip()
        normalized = normalized.rstrip("?.! \t")
        return normalized.casefold()

    def _apply_human_answer_to_task_input(
        self,
        *,
        task: TaskRecord,
        request: HumanRequestRecord,
        answer_text: str,
        reused: bool = False,
    ) -> TaskRecord:
        updated_input = dict(task.input_json)
        latest_human_answer = {
            "request_id": request.id,
            "question": request.question,
            "answer_text": answer_text,
        }
        if reused:
            latest_human_answer["reused_answer"] = True
        updated_input["latest_human_answer"] = latest_human_answer

        human_answers = updated_input.get("human_answers")
        if not isinstance(human_answers, dict):
            human_answers = {}
        human_answers[request.id] = answer_text
        updated_input["human_answers"] = human_answers

        clarification_answers = updated_input.get("clarification_answers")
        if not isinstance(clarification_answers, dict):
            clarification_answers = {}
        clarification_answers[request.question] = answer_text
        updated_input["clarification_answers"] = clarification_answers

        updated_task = task.model_copy(update={"input_json": updated_input})
        self.orchestration.state.update_task(updated_task)
        return self.orchestration.state.task(task.id)

    def _answered_clarification_for_question(
        self,
        *,
        task: TaskRecord,
        question: str,
    ) -> tuple[HumanRequestRecord, str] | None:
        normalized_question = self._normalize_question_key(question)
        if not normalized_question:
            return None
        matches: list[HumanRequestRecord] = []
        for request in self.orchestration.state.human_requests.values():
            if request.task_id != task.id:
                continue
            if request.request_type != HumanRequestType.CLARIFICATION:
                continue
            if request.status != HumanRequestStatus.ANSWERED:
                continue
            answer_text = str(request.answer_text or "").strip()
            if not answer_text:
                continue
            if self._normalize_question_key(request.question) != normalized_question:
                continue
            matches.append(request)
        if not matches:
            return None
        matches.sort(key=lambda item: (item.created_at, item.id))
        latest = matches[-1]
        return latest, str(latest.answer_text or "").strip()

    def _record_reused_clarification(
        self,
        *,
        task: TaskRecord,
        question: str,
        answer_text: str,
    ) -> tuple[TaskRecord, int]:
        updated_input = dict(task.input_json)
        reuse_counts = updated_input.get("clarification_retry_counts")
        if not isinstance(reuse_counts, dict):
            reuse_counts = {}
        normalized_question = self._normalize_question_key(question)
        current_value = reuse_counts.get(normalized_question, 0)
        try:
            reuse_count = max(0, int(current_value)) + 1
        except (TypeError, ValueError):
            reuse_count = 1
        reuse_counts[normalized_question] = reuse_count
        updated_input["clarification_retry_counts"] = reuse_counts
        updated_input["clarification_loop_guard"] = {
            "question": question,
            "answer_text": answer_text,
            "reuse_count": reuse_count,
        }
        updated_task = task.model_copy(update={"input_json": updated_input})
        self.orchestration.state.update_task(updated_task)
        return self.orchestration.state.task(task.id), reuse_count

    def _memory_scopes_for_task(self, task: TaskRecord) -> tuple[str, ...]:
        template = self._task_template(task.task_key, task)
        agent_definition = self.agent_definition(task.assigned_role)
        seen: set[str] = set()
        scopes: list[str] = []
        for raw_scope in (*template.memory_scopes, *agent_definition.default_memory_scopes):
            scope = str(raw_scope).strip()
            if not scope or scope in seen:
                continue
            scopes.append(scope)
            seen.add(scope)
        return tuple(scopes)

    def _memory_scope_identifier(self, task: TaskRecord, scope: str) -> tuple[str, str]:
        scope_text = str(scope).strip()
        scope_type, separator, scope_id = scope_text.partition(":")
        if separator and scope_id:
            return scope_type, scope_id

        with self._runtime_lock:
            workflow_run = self.orchestration.state.graph.workflow_run
            project_id = workflow_run.project_id
        normalized = scope_type or "project"
        if normalized == "project":
            return "project", project_id
        if normalized == "workflow_run":
            return "workflow_run", task.workflow_run_id
        if normalized == "task":
            return "task", task.id
        return normalized, task.workflow_run_id

    def _memory_context(self, task: TaskRecord) -> list[dict[str, object]]:
        context_blocks: list[dict[str, object]] = []
        for scope in self._memory_scopes_for_task(task):
            scope_type, scope_id = self._memory_scope_identifier(task, scope)
            entries = self.storage.context_service.list_memory_entries(scope_type, scope_id, limit=6)
            if not entries:
                continue
            entries = sorted(entries, key=lambda item: (item.created_at, item.id), reverse=True)
            context_blocks.append(
                {
                    "scope": f"{scope_type}:{scope_id}",
                    "entries": [
                        {
                            "memory_id": entry.id,
                            "layer": entry.memory_layer.value,
                            "content": self._truncate_text(entry.content, max_chars=500),
                            "metadata": entry.metadata_json,
                        }
                        for entry in entries[:3]
                    ],
                }
            )
        return context_blocks

    def _persist_memory_entry(
        self,
        *,
        task: TaskRecord,
        content: str,
        memory_layer: MemoryLayer,
        metadata_json: Mapping[str, Any] | None = None,
        scopes: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        normalized = self._truncate_text(content, max_chars=1500)
        if not normalized:
            return ()

        with self._runtime_lock:
            project_id = self.orchestration.state.graph.workflow_run.project_id
            repository = self.storage.workflow_repository

        scope_names = tuple(scopes or self._memory_scopes_for_task(task) or ("workflow_run", "task"))
        metadata = {
            "task_id": task.id,
            "task_key": task.task_key,
            "assigned_role": task.assigned_role,
            **dict(metadata_json or {}),
        }
        stored_ids: list[str] = []
        for scope_name in scope_names:
            scope_type, scope_id = self._memory_scope_identifier(task, scope_name)
            entry = MemoryEntryRecord(
                project_id=project_id,
                scope_type=scope_type,
                scope_id=scope_id,
                memory_layer=memory_layer,
                content=normalized,
                metadata_json=metadata,
            )
            if hasattr(repository, "save_memory_entry"):
                repository.save_memory_entry(entry)
            self.storage.memory_store.write(entry)
            stored_ids.append(entry.id)
        return tuple(stored_ids)

    def _graph_projection_payload(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        event_type: str,
        payload_json: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(payload_json or {})
        payload.setdefault("task_key", task.task_key)
        payload.setdefault("task_title", task.title)
        payload.setdefault("task_state", task.state.value)
        payload.setdefault("attempt_state", attempt.state.value)
        payload.setdefault("entity_id", task.id)
        payload.setdefault("entity_type", "Task")
        if payload.get("artifact_id"):
            payload.setdefault("relation", "PUBLISHED_ARTIFACT")
            payload.setdefault("target_id", str(payload["artifact_id"]))
            payload.setdefault("target_entity_type", "Artifact")
        elif payload.get("human_request_id"):
            payload.setdefault("relation", "REQUESTED_HUMAN_INPUT")
            payload.setdefault("target_id", str(payload["human_request_id"]))
            payload.setdefault("target_entity_type", "HumanRequest")
        elif payload.get("approval_request_id"):
            payload.setdefault("relation", "REQUESTED_APPROVAL")
            payload.setdefault("target_id", str(payload["approval_request_id"]))
            payload.setdefault("target_entity_type", "ApprovalRequest")
        elif event_type.startswith(("attempt.", "openhands.")):
            payload.setdefault("relation", "HAS_ATTEMPT")
            payload.setdefault("target_id", attempt.id)
            payload.setdefault("target_entity_type", "TaskAttempt")
        return payload

    def _upstream_artifact_context(self, task: TaskRecord) -> list[dict[str, object]]:
        artifacts = self.storage.context_service.get_upstream_artifacts(task_id=task.id)
        return [
            {
                "artifact_id": artifact.id,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "summary": artifact.summary,
                "produced_by_role": artifact.produced_by_role,
                "status": artifact.status.value,
                "version": artifact.version,
            }
            for artifact in artifacts
        ]

    def _prepare_task_for_dispatch(self, task: TaskRecord) -> TaskRecord:
        with self._runtime_lock:
            merged_input = dict(self.orchestration.state.graph.workflow_run.root_input_json)
            merged_input.update(task.input_json)
            merged_input["operator_policy"] = self._operator_policy(task)
            workflow_request = self._workflow_request()
            if workflow_request and not str(merged_input.get("user_request", "")).strip():
                merged_input["user_request"] = workflow_request
            upstream_artifacts = self._upstream_artifact_context(task)
            if upstream_artifacts:
                merged_input["upstream_artifacts"] = upstream_artifacts
            if task.required_artifact_types_json:
                merged_input["required_artifact_types"] = list(task.required_artifact_types_json)
            if task.produced_artifact_types_json:
                merged_input["produced_artifact_types"] = list(task.produced_artifact_types_json)
            memory_context = self._memory_context(task)
            if memory_context:
                merged_input["memory_context"] = memory_context
            if merged_input == task.input_json:
                return task
            updated_task = task.model_copy(update={"input_json": merged_input})
            self.orchestration.state.update_task(updated_task)
            self._sync_canonical_state()
            return self.orchestration.state.task(task.id)

    def _approval_policy_requires_pre_dispatch(
        self,
        *,
        task: TaskRecord,
        agent_definition: AgentDefinitionConfig,
        approval_requirements: list[str],
    ) -> bool:
        policy = agent_definition.approval_policy.strip().lower()
        with self._runtime_lock:
            if approval_requirements:
                for request in self.orchestration.state.approval_requests.values():
                    if request.task_id != task.id:
                        continue
                    if request.approval_type not in approval_requirements:
                        continue
                    if request.status == ApprovalStatus.APPROVED:
                        return False
                return True
            return policy in {"request-before-execution", "approval-before-execution", "human-review-required"}

    def _approval_reason(
        self,
        *,
        task: TaskRecord,
        approval_requirements: list[str],
        agent_definition: AgentDefinitionConfig,
    ) -> str:
        if approval_requirements:
            requirement_text = ", ".join(approval_requirements)
            return f"Approval required before dispatch: {requirement_text}"
        return f"Approval policy requires operator confirmation before dispatch for role {agent_definition.role}"

    def _latest_active_attempt(self, task_id: str) -> TaskAttemptRecord | None:
        with self._runtime_lock:
            active_attempts = self.orchestration.active_attempts(task_id)
            if not active_attempts:
                return None
            active_attempts.sort(key=lambda item: item.attempt_number)
            return active_attempts[-1]

    def _max_parallel_dispatches(self) -> int:
        configured_limit = self.settings.autoweave_max_active_attempts
        try:
            configured_limit = max(1, int(configured_limit))
        except (TypeError, ValueError):
            configured_limit = 1
        workflow_limit = self.workflow_definition.policies.get("max_active_attempts")
        try:
            if workflow_limit is not None:
                configured_limit = min(configured_limit, max(1, int(workflow_limit)))
        except (TypeError, ValueError):
            pass
        return configured_limit

    def _worker_workspace_path(self, attempt_id: str) -> str:
        return str(Path("/workspace") / "workspaces" / attempt_id)

    def _graph_structure_signature(self) -> tuple[str, int, tuple[str, ...], tuple[str, ...]]:
        with self._runtime_lock:
            graph = self.orchestration.state.graph
            return (
                graph.workflow_run.id,
                graph.workflow_run.graph_revision,
                tuple(task.id for task in graph.tasks),
                tuple(edge.id for edge in graph.edges),
            )

    def _ensure_canonical_graph_seeded(self) -> None:
        if self._last_persisted_graph_signature is not None:
            return
        self.storage.workflow_repository.save_graph(self.orchestration.state.graph)
        self._last_persisted_graph_signature = self._graph_structure_signature()

    def _reset_example_workflow_run(self) -> None:
        workflow_definition_id = f"{self.workflow_definition.name}:{self.workflow_definition.version}"
        self._reset_workflow_run(
            workflow_run_id=f"{workflow_definition_id.replace(':', '_')}_run_{generate_id('demo')}",
        )

    def _reset_workflow_run(
        self,
        *,
        workflow_run_id: str | None = None,
        root_input_json: JsonDict | None = None,
    ) -> None:
        workflow_definition_id = f"{self.workflow_definition.name}:{self.workflow_definition.version}"
        fresh_graph = build_workflow_graph(
            self.workflow_definition,
            project_id="local",
            team_id="local",
            workflow_definition_id=workflow_definition_id,
            workflow_run_id=workflow_run_id or f"{workflow_definition_id.replace(':', '_')}_run_{generate_id('demo')}",
            root_input_json=root_input_json or {},
        )
        self.storage.workflow_repository.save_graph(fresh_graph)
        canonical_graph = self.storage.workflow_repository.get_graph(fresh_graph.workflow_run.id)
        self.orchestration = OrchestrationService(WorkflowRunState.from_graph(canonical_graph))
        self._last_persisted_graph_signature = self._graph_structure_signature()

    def initialize_workflow_run(
        self,
        *,
        request: str,
        workflow_run_id: str | None = None,
    ) -> str:
        self._reset_workflow_run(
            workflow_run_id=workflow_run_id,
            root_input_json={"user_request": request},
        )
        with self._runtime_lock:
            return self.orchestration.state.graph.workflow_run.id

    def _task_template(self, task_key: str, task: TaskRecord | None = None) -> TaskTemplateConfig:
        for template in self.workflow_definition.task_templates:
            if template.key == task_key:
                return template
        if task is None:
            task = self.orchestration.state.task(task_key)
        input_json = task.input_json
        return TaskTemplateConfig(
            key=task.task_key,
            title=task.title,
            assigned_role=task.assigned_role,
            description_template=task.description,
            hard_dependencies=[],
            soft_dependencies=[],
            required_artifacts=list(task.required_artifact_types_json),
            produced_artifacts=list(task.produced_artifact_types_json),
            approval_requirements=list(input_json.get("_template_approval_requirements", []))
            if isinstance(input_json.get("_template_approval_requirements"), list)
            else [],
            memory_scopes=list(input_json.get("_template_memory_scopes", []))
            if isinstance(input_json.get("_template_memory_scopes"), list)
            else [],
            route_hints=list(input_json.get("_template_route_hints", []))
            if isinstance(input_json.get("_template_route_hints"), list)
            else [],
        )

    def _sync_canonical_state(self) -> None:
        """Persist the authoritative orchestration snapshot through the repository wiring."""

        with self._runtime_lock:
            repository = self.storage.workflow_repository
            graph_signature = self._graph_structure_signature()
            full_graph_sync = graph_signature != self._last_persisted_graph_signature
            tasks = list(self.orchestration.state.tasks_by_id.values())
            attempts = list(self.orchestration.state.attempts_by_id.values())
            human_requests = list(self.orchestration.state.human_requests.values())
            approval_requests = list(self.orchestration.state.approval_requests.values())

            if hasattr(repository, "save_runtime_state"):
                repository.save_runtime_state(
                    workflow_run=self.orchestration.state.graph.workflow_run,
                    tasks=tasks,
                    attempts=attempts,
                    human_requests=human_requests,
                    approval_requests=approval_requests,
                    graph=self.orchestration.state.graph if full_graph_sync else None,
                )
                if full_graph_sync:
                    self._last_persisted_graph_signature = graph_signature
                return

            if full_graph_sync:
                repository.save_graph(self.orchestration.state.graph)
                self._last_persisted_graph_signature = graph_signature
            elif hasattr(repository, "save_workflow_run"):
                repository.save_workflow_run(self.orchestration.state.graph.workflow_run)
            else:
                repository.save_graph(self.orchestration.state.graph)
                self._last_persisted_graph_signature = graph_signature
                full_graph_sync = True

            if not full_graph_sync:
                for task in tasks:
                    repository.save_task(task)
            for attempt in attempts:
                repository.save_attempt(attempt)
            for request in human_requests:
                if hasattr(repository, "save_human_request"):
                    repository.save_human_request(request)
            for request in approval_requests:
                if hasattr(repository, "save_approval_request"):
                    repository.save_approval_request(request)

    def _publish_lifecycle_event(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        event_type: str,
        source: str,
        payload_json: dict[str, Any] | None = None,
        route_model_name: str | None = None,
        route_reason: str | None = None,
    ) -> EventRecord:
        with self._runtime_lock:
            projected_payload = self._graph_projection_payload(
                task=task,
                attempt=attempt,
                event_type=event_type,
                payload_json=payload_json,
            )
            event = self.event_service.publish(
                make_event(
                    workflow_run_id=task.workflow_run_id,
                    task_id=task.id,
                    task_attempt_id=attempt.id,
                    agent_role=task.assigned_role,
                    provider_name=self.vertex_config.provider_name,
                    model_name=route_model_name or attempt.compiled_worker_config_json.get("model_name"),
                    route_reason=route_reason or str(attempt.compiled_worker_config_json.get("route_reason", "")),
                    event_type=event_type,
                    source=source,
                    payload_json=projected_payload,
                    sandbox_id=attempt.workspace_id,
                ),
                correlation=EventCorrelationContext(
                    workflow_run_id=task.workflow_run_id,
                    task_id=task.id,
                    task_attempt_id=attempt.id,
                    agent_role=task.assigned_role,
                    provider_name=self.vertex_config.provider_name,
                    model_name=route_model_name or attempt.compiled_worker_config_json.get("model_name"),
                    route_reason=route_reason or str(attempt.compiled_worker_config_json.get("route_reason", "")),
                    sandbox_id=attempt.workspace_id,
                ),
            )
            if hasattr(self.storage.workflow_repository, "save_event"):
                self.storage.workflow_repository.save_event(event)
            if hasattr(self.storage.graph_projection, "project_event"):
                try:
                    self.storage.graph_projection.project_event(event)
                except Exception as exc:
                    self.observability.record_debug_artifact(
                        workflow_run_id=task.workflow_run_id,
                        task_id=task.id,
                        task_attempt_id=attempt.id,
                        name="graph.projection_error",
                        payload_json={
                            "event_id": event.id,
                            "event_type": event.event_type,
                            "source": event.source,
                            "error": str(exc),
                        },
                    )
            return event

    def _normalize_stream_events(
        self,
        bootstrap_call: OpenHandsServiceCall | None,
        stream_events: Iterable[Mapping[str, Any] | OpenHandsStreamEvent] | None,
    ) -> list[OpenHandsStreamEvent]:
        normalized: list[OpenHandsStreamEvent] = []
        if bootstrap_call is not None:
            normalized.extend(extract_openhands_stream_events(bootstrap_call.response_json))
        if stream_events is not None:
            normalized.extend(normalize_openhands_stream_event(event) for event in stream_events)
        return normalized

    def _put_artifact(
        self,
        artifact: ArtifactRecord,
        *,
        payload: Any | None = None,
    ) -> ArtifactRecord:
        with self._runtime_lock:
            registry = self.storage.artifact_registry
            if payload is None:
                return registry.put_artifact(artifact)
            try:
                return registry.put_artifact(artifact, payload=payload)  # type: ignore[call-arg]
            except TypeError:
                return registry.put_artifact(artifact)

    def _conversation_summary(self, events: Iterable[OpenHandsStreamEvent], execution_status: str) -> str:
        messages = [event.message.strip() for event in events if event.message.strip()]
        if messages:
            return messages[-1]
        return f"OpenHands conversation finished with status {execution_status}"

    def _rewrite_empty_response_terminal_event(
        self,
        events: list[OpenHandsStreamEvent],
        *,
        conversation_id: str,
        execution_status: str,
        model_name: str,
    ) -> list[OpenHandsStreamEvent]:
        empty_events = [event for event in events if event.empty_response]
        if not empty_events or execution_status != "stuck":
            return events
        reasoning_only_count = sum(
            1
            for event in empty_events
            if bool(event.payload_json.get("reasoning_content_present"))
        )

        diagnostic = (
            "worker_empty_response_loop: "
            f"OpenHands emitted {len(empty_events)} empty assistant responses without text or tool calls "
            f"before the conversation became stuck for model {model_name or 'unknown'}"
        )
        if reasoning_only_count:
            diagnostic += (
                f"; {reasoning_only_count} empty turns still carried reasoning content, "
                "which is typically a Vertex/OpenHands reasoning-only response"
            )
        terminal_index = next(
            (
                index
                for index in range(len(events) - 1, -1, -1)
                if events[index].terminal and events[index].outcome in {"stuck", "error", "timeout"}
            ),
            None,
        )
        replacement = OpenHandsStreamEvent(
            event_type="error",
            message=diagnostic,
            payload_json={
                "conversation_id": conversation_id,
                "execution_status": execution_status,
                "diagnostic_code": "worker_empty_response_loop",
                "empty_response_count": len(empty_events),
                "reasoning_only_count": reasoning_only_count,
                "model_name": model_name,
            },
            outcome="error",
            terminal=True,
        )
        if terminal_index is None:
            return [*events, replacement]
        updated = list(events)
        updated[terminal_index] = replacement
        return updated

    def _retry_policy_max_attempts(self) -> int:
        raw_value = self.runtime_config.retry_policy.get("max_attempts", 1)
        try:
            return max(1, int(raw_value))
        except (TypeError, ValueError):
            return 1

    def _retry_policy_backoff_seconds(self) -> float:
        raw_value = self.runtime_config.retry_policy.get("backoff_seconds", 0)
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            return 0.0

    def _clarification_retry_limit(self) -> int:
        try:
            return max(1, int(self.runtime_config.clarification_retry_limit))
        except (TypeError, ValueError):
            return 2

    def _retryable_failure_reason(self, events: Iterable[OpenHandsStreamEvent]) -> str | None:
        for event in reversed(tuple(events)):
            if event.payload_json.get("diagnostic_code") == "worker_empty_response_loop":
                return event.message or "worker_empty_response_loop"
        return None

    def _downgrade_recovered_terminal_failures(
        self,
        events: Iterable[OpenHandsStreamEvent],
    ) -> list[OpenHandsStreamEvent]:
        event_list = list(events)
        if not event_list:
            return event_list

        recovered_events: list[OpenHandsStreamEvent] = []
        seen_nonfailure_terminal = False
        success_outcomes = {"success", "succeeded", "complete", "completed"}
        failure_outcomes = {"failure", "failed", "error", "timeout", "stuck", "crash", "orphaned"}

        for event in reversed(event_list):
            outcome = (event.outcome or "").lower()
            is_nonfailure_terminal = event.terminal and (
                outcome in success_outcomes
                or event.event_type in {"complete", "completed", "final"}
                or event.requires_human
                or event.approval_required
            )
            is_failure_terminal = event.terminal and (
                outcome in failure_outcomes
                or event.event_type == "error"
            )
            if seen_nonfailure_terminal and is_failure_terminal:
                event = replace(
                    event,
                    event_type="diagnostic",
                    terminal=False,
                    outcome="recovered_error",
                    payload_json={
                        **event.payload_json,
                        "recovered_after_terminal_event": True,
                        "original_event_type": event.event_type,
                        "original_outcome": event.outcome,
                    },
                )
            recovered_events.append(event)
            if is_nonfailure_terminal:
                seen_nonfailure_terminal = True

        recovered_events.reverse()
        return recovered_events

    def _semantic_manager_clarification(
        self,
        *,
        task: TaskRecord,
        stream_event: OpenHandsStreamEvent,
    ) -> str | None:
        if task.assigned_role != "manager":
            return None
        if stream_event.requires_human or stream_event.approval_required:
            return None
        if stream_event.event_type not in {"message", "complete"}:
            return None
        if stream_event.event_type == "message":
            event_role = str(stream_event.payload_json.get("role") or "").strip().lower()
            event_source = str(stream_event.payload_json.get("source") or "").strip().lower()
            if event_role and event_role != "assistant":
                return None
            if event_source and event_source not in {"agent", "assistant"}:
                return None
        questions = extract_semantic_clarification_questions(stream_event.message)
        if not questions:
            return None
        autonomy_level = self._autonomy_level()
        if autonomy_level == "high":
            lower_message = stream_event.message.lower()
            hard_blocker_markers = (
                "cannot proceed",
                "can't proceed",
                "blocked until",
                "must know",
                "required before i continue",
                "need this to continue",
            )
            if not any(marker in lower_message for marker in hard_blocker_markers):
                return None
        return "\n".join(questions)

    def _task_artifacts(self, task: TaskRecord) -> list[ArtifactRecord]:
        repository = self.storage.workflow_repository
        if hasattr(repository, "list_artifacts_for_task"):
            try:
                return list(repository.list_artifacts_for_task(task.id))
            except KeyError:
                return []
        return []

    def _upstream_final_artifacts(
        self,
        task: TaskRecord,
        *,
        artifact_types: set[str] | None = None,
    ) -> list[ArtifactRecord]:
        artifacts = self.storage.context_service.get_upstream_artifacts(
            task_id=task.id,
            status=ArtifactStatus.FINAL.value,
        )
        if not artifact_types:
            return list(artifacts)
        return [artifact for artifact in artifacts if artifact.artifact_type in artifact_types]

    def _review_supporting_summaries(self, task: TaskRecord) -> list[str]:
        summaries: list[str] = []
        for artifact in self._upstream_final_artifacts(
            task,
            artifact_types={"integration_report", "integration_rework_report"},
        ):
            summary = artifact.summary.strip()
            if summary:
                summaries.append(summary)
        return summaries

    def _review_feedback_text(self, task: TaskRecord) -> str:
        candidates: list[str] = []
        for artifact in self._task_artifacts(task):
            if artifact.artifact_type != "review_notes" or artifact.status != ArtifactStatus.FINAL:
                continue
            summary = artifact.summary.strip()
            if summary:
                candidates.append(summary)
        result_summary = str(task.output_json.get("result_summary", "")).strip()
        if result_summary:
            candidates.append(result_summary)
        candidates.extend(self._review_supporting_summaries(task))
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.casefold()
            if key in seen:
                continue
            deduped.append(candidate)
            seen.add(key)
        return "\n\n".join(deduped)

    def _review_has_validation_evidence(self, task: TaskRecord, review_feedback: str) -> bool:
        lower_feedback = review_feedback.strip().lower()
        if not lower_feedback:
            return False
        evidence_cues = (
            "validated",
            "verified",
            "smoke test passed",
            "smoke-tested",
            "build passed",
            "tests passed",
            "previewed",
            "ran locally",
            "manual qa passed",
            "checked in browser",
            "api smoke test passed",
            "runnable",
            "working end to end",
            "verified end to end",
        )
        if any(cue in lower_feedback for cue in evidence_cues):
            return True
        for summary in self._review_supporting_summaries(task):
            lower_summary = summary.lower()
            if any(cue in lower_summary for cue in evidence_cues):
                return True
        return False

    def _review_decision(self, task: TaskRecord, review_feedback: str) -> str:
        lower_feedback = review_feedback.strip().lower()
        if not lower_feedback:
            return "revise"
        if "review_decision: revise" in lower_feedback:
            return "revise"
        explicit_approve = "review_decision: approve" in lower_feedback
        approve_cues = (
            "no blocking issues",
            "ready to ship",
            "recommendation: approve",
        )
        revise_cues = (
            "changes requested",
            "recommendation: revise",
            "needs rework",
            "must fix",
            "not ready to ship",
            "before release",
            "blocking issue",
            "blocker",
            "build failed",
            "compile error",
            "failed to compile",
            "type error",
            "lint failed",
            "manual patch",
            "not verified",
            "could not run",
            "did not run",
            "untested",
            "runtime error",
            "missing asset",
            "requires follow-up",
        )
        if any(cue in lower_feedback for cue in revise_cues):
            return "revise"
        has_validation_evidence = self._review_has_validation_evidence(task, review_feedback)
        if explicit_approve or any(cue in lower_feedback for cue in approve_cues):
            return "approve" if has_validation_evidence else "revise"
        return "revise"

    def _build_dynamic_task(
        self,
        *,
        workflow_run_id: str,
        task_key: str,
        title: str,
        description: str,
        assigned_role: str,
        required_artifacts: list[str],
        produced_artifacts: list[str],
        route_hints: list[str],
        extra_input_json: Mapping[str, Any] | None = None,
        approval_requirements: list[str] | None = None,
    ) -> TaskRecord:
        return TaskRecord(
            workflow_run_id=workflow_run_id,
            task_key=task_key,
            title=title,
            description=description,
            assigned_role=assigned_role,
            input_json={
                **dict(extra_input_json or {}),
                "_template_memory_scopes": ["workflow_run", "task"],
                "_template_route_hints": route_hints,
                "_template_approval_requirements": list(approval_requirements or []),
            },
            required_artifact_types_json=required_artifacts,
            produced_artifact_types_json=produced_artifacts,
        )

    def _should_require_release_signoff(self) -> bool:
        return bool(getattr(self.runtime_config, "require_release_signoff", True))

    def _append_review_rework_tasks(
        self,
        *,
        review_task: TaskRecord,
        review_attempt: TaskAttemptRecord,
    ) -> tuple[str, ...]:
        if review_task.task_key != "review":
            return ()

        review_feedback = self._review_feedback_text(review_task)
        if self._review_decision(review_task, review_feedback) != "revise":
            return ()

        with self._runtime_lock:
            existing_keys = {task.task_key for task in self.orchestration.state.tasks_by_id.values()}
            if {"manager_rework", "backend_rework", "frontend_rework", "integration_rework"} & existing_keys:
                return ()

        manager_rework = self._build_dynamic_task(
            workflow_run_id=review_task.workflow_run_id,
            task_key="manager_rework",
            title="Manager rework plan",
            description="Turn the single review pass into a concrete rework plan and assign backend/frontend fixes without scheduling another review.",
            assigned_role="manager",
            required_artifacts=["review_notes"],
            produced_artifacts=["rework_plan"],
            route_hints=["planning", "rework"],
            extra_input_json={"review_feedback": review_feedback},
        )
        backend_rework = self._build_dynamic_task(
            workflow_run_id=review_task.workflow_run_id,
            task_key="backend_rework",
            title="Backend rework",
            description="Apply the backend-facing fixes called out in the review notes and manager rework plan.",
            assigned_role="backend",
            required_artifacts=["review_notes", "rework_plan"],
            produced_artifacts=["backend_rework"],
            route_hints=["implementation", "rework"],
            extra_input_json={"review_feedback": review_feedback},
        )
        frontend_rework = self._build_dynamic_task(
            workflow_run_id=review_task.workflow_run_id,
            task_key="frontend_rework",
            title="Frontend rework",
            description="Apply the frontend-facing fixes called out in the review notes and manager rework plan.",
            assigned_role="frontend",
            required_artifacts=["review_notes", "rework_plan"],
            produced_artifacts=["frontend_rework"],
            route_hints=["implementation", "rework"],
            extra_input_json={"review_feedback": review_feedback},
        )
        integration_rework = self._build_dynamic_task(
            workflow_run_id=review_task.workflow_run_id,
            task_key="integration_rework",
            title="Integration rework",
            description="Re-integrate the backend and frontend fixes from the single review pass and produce the final handoff artifact.",
            assigned_role="backend",
            required_artifacts=["backend_rework", "frontend_rework"],
            produced_artifacts=["integration_rework_report"],
            route_hints=["integration", "rework"],
            extra_input_json={"review_feedback": review_feedback},
        )
        edges = [
            TaskEdgeRecord(
                workflow_run_id=review_task.workflow_run_id,
                from_task_id=review_task.id,
                to_task_id=manager_rework.id,
                edge_type=EdgeType.HARD,
                is_hard_dependency=True,
            ),
            TaskEdgeRecord(
                workflow_run_id=review_task.workflow_run_id,
                from_task_id=manager_rework.id,
                to_task_id=backend_rework.id,
                edge_type=EdgeType.HARD,
                is_hard_dependency=True,
            ),
            TaskEdgeRecord(
                workflow_run_id=review_task.workflow_run_id,
                from_task_id=manager_rework.id,
                to_task_id=frontend_rework.id,
                edge_type=EdgeType.HARD,
                is_hard_dependency=True,
            ),
            TaskEdgeRecord(
                workflow_run_id=review_task.workflow_run_id,
                from_task_id=backend_rework.id,
                to_task_id=integration_rework.id,
                edge_type=EdgeType.HARD,
                is_hard_dependency=True,
            ),
            TaskEdgeRecord(
                workflow_run_id=review_task.workflow_run_id,
                from_task_id=frontend_rework.id,
                to_task_id=integration_rework.id,
                edge_type=EdgeType.HARD,
                is_hard_dependency=True,
            ),
        ]
        with self._runtime_lock:
            appended_tasks = self.orchestration.add_dynamic_tasks(
                tasks=[manager_rework, backend_rework, frontend_rework, integration_rework],
                edges=edges,
            )
        self._persist_memory_entry(
            task=review_task,
            content=f"Review requested rework once: {self._truncate_text(review_feedback, max_chars=900)}",
            memory_layer=MemoryLayer.SEMANTIC,
            metadata_json={
                "kind": "review_rework",
                "rework_task_keys": [task.task_key for task in appended_tasks],
            },
        )
        self._publish_lifecycle_event(
            task=review_task,
            attempt=review_attempt,
            event_type="workflow.rework_planned",
            source="orchestrator",
            payload_json={
                "review_decision": "revise",
                "rework_task_keys": [task.task_key for task in appended_tasks],
            },
        )
        return tuple(task.task_key for task in appended_tasks)

    def _append_release_signoff_task(
        self,
        *,
        trigger_task: TaskRecord,
        trigger_attempt: TaskAttemptRecord,
        required_artifacts: list[str],
        release_context: str,
    ) -> tuple[str, ...]:
        if not self._should_require_release_signoff():
            return ()

        with self._runtime_lock:
            existing_keys = {task.task_key for task in self.orchestration.state.tasks_by_id.values()}
            if "release_signoff" in existing_keys:
                return ()

        release_signoff = self._build_dynamic_task(
            workflow_run_id=trigger_task.workflow_run_id,
            task_key="release_signoff",
            title="Release signoff",
            description="Wait for operator release signoff, then package the final handoff artifact without scheduling another review pass.",
            assigned_role="manager",
            required_artifacts=required_artifacts,
            produced_artifacts=["release_handoff"],
            route_hints=["handoff", "approval"],
            extra_input_json={"release_context": release_context},
            approval_requirements=["release_signoff"],
        )
        edge = TaskEdgeRecord(
            workflow_run_id=trigger_task.workflow_run_id,
            from_task_id=trigger_task.id,
            to_task_id=release_signoff.id,
            edge_type=EdgeType.HARD,
            is_hard_dependency=True,
        )
        with self._runtime_lock:
            appended_tasks = self.orchestration.add_dynamic_tasks(
                tasks=[release_signoff],
                edges=[edge],
            )
        self._persist_memory_entry(
            task=trigger_task,
            content=f"Release signoff required after {trigger_task.task_key}: {self._truncate_text(release_context, max_chars=900)}",
            memory_layer=MemoryLayer.SEMANTIC,
            metadata_json={
                "kind": "release_signoff",
                "release_task_keys": [task.task_key for task in appended_tasks],
            },
        )
        self._publish_lifecycle_event(
            task=trigger_task,
            attempt=trigger_attempt,
            event_type="workflow.release_signoff_required",
            source="orchestrator",
            payload_json={
                "trigger_task_key": trigger_task.task_key,
                "release_task_keys": [task.task_key for task in appended_tasks],
            },
        )
        return tuple(task.task_key for task in appended_tasks)

    def _collect_openhands_stream(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        bootstrap_call: OpenHandsServiceCall,
        stream_events: Iterable[Mapping[str, Any] | OpenHandsStreamEvent] | None,
    ) -> tuple[list[OpenHandsStreamEvent], tuple[str, ...]]:
        normalized = self._normalize_stream_events(bootstrap_call, stream_events)
        if normalized:
            return normalized, ()

        conversation_id = bootstrap_call.conversation_id
        if not conversation_id:
            return normalized, ()

        initial_info = self.openhands_client.get_conversation(conversation_id)
        if initial_info.ok and initial_info.execution_status == "idle":
            run_call = self.openhands_client.run_conversation(conversation_id)
            self._publish_lifecycle_event(
                task=task,
                attempt=attempt,
                event_type="attempt.run_requested",
                source="orchestrator",
                payload_json={
                    "conversation_id": conversation_id,
                    "run_ok": run_call.ok,
                },
            )
            if not run_call.ok and run_call.status_code != 409:
                return [
                    OpenHandsStreamEvent(
                        event_type="error",
                        message=run_call.error or run_call.response_text or "conversation run request failed",
                        payload_json=run_call.response_json,
                        outcome="error",
                        terminal=True,
                    )
                ], ()

        poll_timeout_seconds = float(self.settings.autoweave_openhands_poll_timeout_seconds)
        poll_interval_seconds = float(self.settings.autoweave_openhands_poll_interval_seconds)
        final_info = self.openhands_client.wait_for_conversation(
            conversation_id,
            timeout_seconds=poll_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        if self._should_retry_openhands_poll(final_info):
            retry_timeout_seconds = min(60.0, max(10.0, poll_interval_seconds * 5.0))
            self._publish_lifecycle_event(
                task=task,
                attempt=attempt,
                event_type="attempt.poll_retry",
                source="orchestrator",
                payload_json={
                    "conversation_id": conversation_id,
                    "initial_error": final_info.error,
                    "retry_timeout_seconds": retry_timeout_seconds,
                },
            )
            retry_info = self.openhands_client.wait_for_conversation(
                conversation_id,
                timeout_seconds=retry_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            final_info = retry_info
        event_payloads = self.openhands_client.list_all_conversation_events(conversation_id)
        normalized.extend(extract_openhands_stream_events({"items": event_payloads}))
        refreshed_info = self.openhands_client.get_conversation(conversation_id)
        terminal_statuses = {"finished", "error", "stuck", "paused", "waiting_for_confirmation"}
        if (
            refreshed_info.ok
            and refreshed_info.execution_status
            and (
                final_info.execution_status not in terminal_statuses
                or refreshed_info.execution_status in terminal_statuses
            )
        ):
            final_info = refreshed_info
        execution_status = (
            final_info.execution_status
            or bootstrap_call.execution_status
            or str(initial_info.response_json.get("execution_status", "unknown"))
        )
        normalized = self._rewrite_empty_response_terminal_event(
            normalized,
            conversation_id=conversation_id,
            execution_status=execution_status,
            model_name=str(attempt.compiled_worker_config_json.get("model_name", "")),
        )
        has_terminal_success = any(
            event.outcome in {"success", "succeeded", "complete", "completed"}
            or event.event_type in {"complete", "completed", "final"}
            for event in normalized
        )
        has_terminal_pause = any(event.requires_human or event.approval_required for event in normalized)

        if not normalized:
            if execution_status == "finished":
                normalized.append(
                    OpenHandsStreamEvent(
                        event_type="complete",
                        message="conversation finished",
                        payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                        outcome="success",
                        terminal=True,
                    )
                )
            elif execution_status in {"paused", "waiting_for_confirmation"}:
                normalized.append(
                    OpenHandsStreamEvent(
                        event_type="paused",
                        message=f"conversation {execution_status}",
                        payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                        approval_required=(execution_status == "waiting_for_confirmation"),
                        requires_human=(execution_status == "paused"),
                    )
                )
            else:
                normalized.append(
                    OpenHandsStreamEvent(
                        event_type="error",
                        message=final_info.error or f"conversation {execution_status}",
                        payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                        outcome="timeout" if "timed out" in (final_info.error or "").lower() else "error",
                        terminal=True,
                    )
                )
        elif execution_status == "finished" and not has_terminal_success:
            normalized.append(
                OpenHandsStreamEvent(
                    event_type="complete",
                    message="conversation finished",
                    payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                    outcome="success",
                    terminal=True,
                )
            )
        elif execution_status in {"paused", "waiting_for_confirmation"} and not has_terminal_pause:
            normalized.append(
                OpenHandsStreamEvent(
                    event_type="paused",
                    message=f"conversation {execution_status}",
                    payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                    approval_required=(execution_status == "waiting_for_confirmation"),
                    requires_human=(execution_status == "paused"),
                )
            )
        elif final_info.error is not None and all(event.outcome not in {"error", "timeout"} for event in normalized):
            normalized.append(
                OpenHandsStreamEvent(
                    event_type="error",
                    message=final_info.error,
                    payload_json={"conversation_id": conversation_id, "execution_status": execution_status},
                    outcome="timeout",
                    terminal=True,
                )
            )
        normalized = self._downgrade_recovered_terminal_failures(normalized)

        debug_payload = {
            "conversation_id": conversation_id,
            "execution_status": execution_status,
            "bootstrap": bootstrap_call.response_json,
            "conversation": final_info.response_json,
            "events": event_payloads,
        }
        with self._runtime_lock:
            self.observability.record_debug_artifact(
                workflow_run_id=task.workflow_run_id,
                task_id=task.id,
                task_attempt_id=attempt.id,
                name="openhands.conversation",
                payload_json=debug_payload,
            )
        replay_artifact = ArtifactRecord(
            workflow_run_id=task.workflow_run_id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            produced_by_role=task.assigned_role,
            artifact_type="openhands_replay",
            title=f"OpenHands conversation {conversation_id}",
            summary=self._conversation_summary(normalized, execution_status),
            status=ArtifactStatus.FINAL if execution_status in {"finished", "error", "stuck", "paused", "waiting_for_confirmation"} else ArtifactStatus.DRAFT,
            version=1,
            storage_uri="",
            checksum="",
            metadata_json={
                "content_type": "application/json",
                "conversation_id": conversation_id,
                "execution_status": execution_status,
                "event_count": len(event_payloads),
                "persistence_dir": final_info.response_json.get("persistence_dir", bootstrap_call.response_json.get("persistence_dir")),
            },
        )
        stored_replay = self._put_artifact(replay_artifact, payload=debug_payload)
        return normalized, (stored_replay.id,)

    def _should_retry_openhands_poll(self, final_info: OpenHandsServiceCall) -> bool:
        error_text = (final_info.error or "").strip().lower()
        if "timed out" not in error_text:
            return False
        if final_info.execution_status in {"finished", "error", "stuck", "paused", "waiting_for_confirmation"}:
            return False
        return True

    def _process_openhands_stream(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        stream_events: list[OpenHandsStreamEvent],
    ) -> tuple[TaskRecord, TaskAttemptRecord, tuple[str, ...], tuple[str, ...]]:
        emitted_types: list[str] = []
        artifact_ids: list[str] = []
        current_task = task
        current_attempt = attempt
        latest_message = ""
        latest_terminal_message = ""
        for stream_event in stream_events:
            semantic_question = self._semantic_manager_clarification(
                task=current_task,
                stream_event=stream_event,
            )
            if semantic_question is not None:
                stream_event = replace(
                    stream_event,
                    event_type="clarification",
                    message=semantic_question,
                    payload_json={
                        **stream_event.payload_json,
                        "semantic_clarification": True,
                        "context_summary": stream_event.message,
                    },
                    terminal=True,
                    requires_human=True,
                )
            emitted_types.append(stream_event.event_type)
            if stream_event.message.strip():
                latest_message = stream_event.message.strip()
            if stream_event.terminal and stream_event.message.strip():
                latest_terminal_message = stream_event.message.strip()
            self._publish_lifecycle_event(
                task=current_task,
                attempt=current_attempt,
                event_type=f"openhands.{stream_event.event_type}",
                source="openhands",
                payload_json=stream_event.payload_json | {"message": stream_event.message, "outcome": stream_event.outcome},
            )
            if stream_event.requires_human:
                answered_clarification = self._answered_clarification_for_question(
                    task=current_task,
                    question=stream_event.message,
                )
                if answered_clarification is not None:
                    answered_request, answer_text = answered_clarification
                    current_task = self._apply_human_answer_to_task_input(
                        task=current_task,
                        request=answered_request,
                        answer_text=answer_text,
                        reused=True,
                    )
                    current_task, reuse_count = self._record_reused_clarification(
                        task=current_task,
                        question=answered_request.question,
                        answer_text=answer_text,
                    )
                    retry_limit = self._clarification_retry_limit()
                    current_attempt = self.orchestration.abort_attempt(current_attempt.id)
                    if reuse_count >= retry_limit:
                        diagnostic_reason = (
                            "duplicate_answered_clarification_loop: "
                            f"{answered_request.question}"
                        )
                        current_task = current_task.model_copy(
                            update={
                                "output_json": {
                                    **current_task.output_json,
                                    "result_summary": diagnostic_reason,
                                }
                            }
                        )
                        self.orchestration.state.update_task(current_task)
                        current_task = self.orchestration.fail_task(
                            current_task.id,
                            reason=diagnostic_reason,
                        )
                        self._persist_memory_entry(
                            task=current_task,
                            content=(
                                f"Manager clarification loop detected for {current_task.title}: "
                                f"{answered_request.question} Answer: {answer_text}"
                            ),
                            memory_layer=MemoryLayer.EPISODIC,
                            metadata_json={
                                "kind": "duplicate_answered_clarification_loop",
                                "human_request_id": answered_request.id,
                                "reuse_count": reuse_count,
                                "retry_limit": retry_limit,
                            },
                        )
                        self._publish_lifecycle_event(
                            task=current_task,
                            attempt=current_attempt,
                            event_type="attempt.duplicate_answered_clarification_loop",
                            source="orchestrator",
                            payload_json={
                                "human_request_id": answered_request.id,
                                "question": answered_request.question,
                                "reuse_count": reuse_count,
                                "retry_limit": retry_limit,
                            },
                        )
                        self._sync_canonical_state()
                        current_task = self.orchestration.state.task(current_task.id)
                        current_attempt = self.orchestration.state.attempt(current_attempt.id)
                        break
                    current_task = self.orchestration.block_task(
                        current_task.id,
                        reason=f"reused_answered_clarification:{answered_request.id}",
                    )
                    current_task = self.orchestration.unblock_task(current_task.id)
                    self._persist_memory_entry(
                        task=current_task,
                        content=(
                            f"Reused answered clarification for {current_task.title}: "
                            f"{answered_request.question} Answer: {answer_text}"
                        ),
                        memory_layer=MemoryLayer.SEMANTIC,
                        metadata_json={
                            "kind": "human_answer_reused",
                            "human_request_id": answered_request.id,
                        },
                    )
                    self._publish_lifecycle_event(
                        task=current_task,
                        attempt=current_attempt,
                        event_type="attempt.answered_human_request_reused",
                        source="orchestrator",
                        payload_json={
                            "human_request_id": answered_request.id,
                            "question": answered_request.question,
                            "reuse_count": reuse_count,
                            "retry_limit": retry_limit,
                        },
                    )
                    self._sync_canonical_state()
                    current_task = self.orchestration.state.task(current_task.id)
                    current_attempt = self.orchestration.state.attempt(current_attempt.id)
                    break
                self.orchestration.needs_input_attempt(current_attempt.id)
                request = self.orchestration.request_clarification(
                    task_id=current_task.id,
                    task_attempt_id=current_attempt.id,
                    question=stream_event.message or "Clarification requested by worker",
                    context_summary=str(stream_event.payload_json.get("context_summary", "")),
                )
                self._persist_memory_entry(
                    task=current_task,
                    content=f"Clarification requested for {current_task.title}: {request.question}",
                    memory_layer=MemoryLayer.EPISODIC,
                    metadata_json={
                        "kind": "human_request",
                        "human_request_id": request.id,
                    },
                )
                self._publish_lifecycle_event(
                    task=current_task,
                    attempt=current_attempt,
                    event_type="attempt.waiting_for_human",
                    source="orchestrator",
                    payload_json={
                        "human_request_id": request.id,
                        "question": request.question,
                    },
                )
                self._sync_canonical_state()
                current_task = self.orchestration.state.task(current_task.id)
                current_attempt = self.orchestration.state.attempt(current_attempt.id)
                break
            if stream_event.approval_required:
                self.orchestration.pause_attempt(current_attempt.id)
                request = self.orchestration.request_approval(
                    task_id=current_task.id,
                    task_attempt_id=current_attempt.id,
                    approval_type=str(stream_event.payload_json.get("approval_type", "review")),
                    reason=stream_event.message or "Approval requested by worker",
                )
                self._persist_memory_entry(
                    task=current_task,
                    content=f"Approval requested for {current_task.title}: {request.reason}",
                    memory_layer=MemoryLayer.EPISODIC,
                    metadata_json={
                        "kind": "approval_request",
                        "approval_request_id": request.id,
                        "approval_type": request.approval_type,
                    },
                )
                self._publish_lifecycle_event(
                    task=current_task,
                    attempt=current_attempt,
                    event_type="attempt.waiting_for_approval",
                    source="orchestrator",
                    payload_json={
                        "approval_request_id": request.id,
                        "approval_type": request.approval_type,
                        "reason": request.reason,
                    },
                )
                self._sync_canonical_state()
                current_task = self.orchestration.state.task(current_task.id)
                current_attempt = self.orchestration.state.attempt(current_attempt.id)
                break

            artifact = stream_event_to_artifact(stream_event, task=current_task, attempt=current_attempt)
            if artifact is not None:
                stored_artifact = self.storage.artifact_registry.put_artifact(artifact)
                artifact_ids.append(stored_artifact.id)
                if stored_artifact.status == ArtifactStatus.FINAL:
                    self._persist_memory_entry(
                        task=current_task,
                        content=f"{stored_artifact.artifact_type}: {stored_artifact.summary}",
                        memory_layer=MemoryLayer.SEMANTIC,
                        metadata_json={
                            "kind": "artifact",
                            "artifact_id": stored_artifact.id,
                            "artifact_type": stored_artifact.artifact_type,
                        },
                    )
                self._publish_lifecycle_event(
                    task=current_task,
                    attempt=current_attempt,
                    event_type="artifact.published",
                    source="artifacts",
                    payload_json={
                        "artifact_id": stored_artifact.id,
                        "artifact_type": stored_artifact.artifact_type,
                        "status": stored_artifact.status.value,
                        "storage_uri": stored_artifact.storage_uri,
                    },
                )

            outcome = (stream_event.outcome or "").lower()
            terminal = stream_event.terminal or outcome in {"success", "succeeded", "complete", "completed", "failure", "failed", "error", "timeout", "crash", "orphaned"}
            if outcome in {"success", "succeeded", "complete", "completed"} or (stream_event.event_type in {"complete", "completed", "final"} and not outcome):
                terminal_summary = latest_terminal_message or latest_message or current_task.description
                current_task = current_task.model_copy(
                    update={
                        "output_json": {
                            **current_task.output_json,
                            "result_summary": terminal_summary,
                        }
                    }
                )
                self.orchestration.state.update_task(current_task)
                current_task, current_attempt = self.orchestration.finalize_attempt_success(current_task.id, current_attempt.id)
                self._persist_memory_entry(
                    task=current_task,
                    content=f"{current_task.title}: {terminal_summary}",
                    memory_layer=MemoryLayer.SEMANTIC,
                    metadata_json={"kind": "task_result", "outcome": "success"},
                )
                rework_task_keys = self._append_review_rework_tasks(
                    review_task=current_task,
                    review_attempt=current_attempt,
                )
                if current_task.task_key == "review" and not rework_task_keys:
                    self._append_release_signoff_task(
                        trigger_task=current_task,
                        trigger_attempt=current_attempt,
                        required_artifacts=["review_notes"],
                        release_context=self._review_feedback_text(current_task) or terminal_summary,
                    )
                elif current_task.task_key == "integration_rework":
                    self._append_release_signoff_task(
                        trigger_task=current_task,
                        trigger_attempt=current_attempt,
                        required_artifacts=["review_notes", "integration_rework_report"],
                        release_context=terminal_summary,
                    )
                if not artifact_ids and current_task.produced_artifact_types_json:
                    fallback_artifact = ArtifactRecord(
                        workflow_run_id=current_task.workflow_run_id,
                        task_id=current_task.id,
                        task_attempt_id=current_attempt.id,
                        produced_by_role=current_task.assigned_role,
                        artifact_type=current_task.produced_artifact_types_json[0],
                        title=current_task.title,
                        summary=terminal_summary,
                        status=ArtifactStatus.FINAL,
                        version=1,
                        storage_uri="",
                        checksum="",
                        metadata_json={
                            "content_type": "text/plain",
                            "artifact_source": "terminal_success_fallback",
                        },
                    )
                    stored_artifact = self.storage.artifact_registry.put_artifact(
                        fallback_artifact,
                        payload=terminal_summary,
                    )
                    artifact_ids.append(stored_artifact.id)
                    self._publish_lifecycle_event(
                        task=current_task,
                        attempt=current_attempt,
                        event_type="artifact.published",
                        source="artifacts",
                        payload_json={
                            "artifact_id": stored_artifact.id,
                            "artifact_type": stored_artifact.artifact_type,
                            "status": stored_artifact.status.value,
                            "storage_uri": stored_artifact.storage_uri,
                            "artifact_source": "terminal_success_fallback",
                        },
                    )
                self._sync_canonical_state()
            elif outcome in {"timeout", "crash", "orphaned"}:
                current_task, current_attempt = self.orchestration.finalize_attempt_failure(
                    current_task.id,
                    current_attempt.id,
                    reason=stream_event.message or outcome or "worker_recovery",
                    recoverable=True,
                )
                self._persist_memory_entry(
                    task=current_task,
                    content=f"{current_task.title} stalled: {stream_event.message or outcome or 'worker_recovery'}",
                    memory_layer=MemoryLayer.EPISODIC,
                    metadata_json={"kind": "task_result", "outcome": outcome or "timeout"},
                )
                self._sync_canonical_state()
            elif outcome in {"failure", "failed", "error"}:
                recoverable_failure = stream_event.payload_json.get("diagnostic_code") == "worker_empty_response_loop"
                current_task, current_attempt = self.orchestration.finalize_attempt_failure(
                    current_task.id,
                    current_attempt.id,
                    reason=stream_event.message or outcome or "worker_failure",
                    recoverable=recoverable_failure,
                )
                self._persist_memory_entry(
                    task=current_task,
                    content=f"{current_task.title} failed: {stream_event.message or outcome or 'worker_failure'}",
                    memory_layer=MemoryLayer.EPISODIC,
                    metadata_json={
                        "kind": "task_result",
                        "outcome": outcome or "error",
                        "recoverable": recoverable_failure,
                    },
                )
                self._sync_canonical_state()
            elif stream_event.event_type == "progress":
                if current_task.state == TaskState.READY:
                    current_task = self.orchestration.start_task(current_task.id)
                    self._sync_canonical_state()
                if current_attempt.state in {AttemptState.PAUSED, AttemptState.NEEDS_INPUT}:
                    current_attempt = self.orchestration.resume_attempt(current_attempt.id)
                    self._sync_canonical_state()
                elif current_attempt.state == AttemptState.QUEUED:
                    current_attempt = self.orchestration.start_attempt(current_attempt.id)
                    self._sync_canonical_state()
            if terminal:
                break
        return current_task, current_attempt, tuple(emitted_types), tuple(artifact_ids)

    def _run_task(
        self,
        *,
        task: TaskRecord,
        dispatch: bool,
        stream_events: Iterable[Mapping[str, Any] | OpenHandsStreamEvent] | None = None,
    ) -> LocalTaskRunReport:
        task = self._prepare_task_for_dispatch(task)
        template = self._task_template(task.task_key, task)
        agent_definition = self.agent_definition(task.assigned_role)
        with self._runtime_lock:
            attempt = self.orchestration.open_attempt(
                task_id=task.id,
                agent_definition_id=f"{task.assigned_role}-agent",
            )
        route_hints = list(dict.fromkeys([*template.route_hints, *agent_definition.model_profile_hints]))
        route = self.router.select_route(task=task, attempt=attempt, hints=route_hints)
        workspace_reservation = self.worker_adapter.reserve_workspace(attempt=attempt)
        runtime_policy = dict(self.runtime_policy)
        runtime_policy["tool_groups"] = list(agent_definition.allowed_tool_groups)
        launch_payload = self.worker_adapter.compile_launch_payload(
            task=task,
            attempt=attempt,
            route_reason=route.route_reason,
            route_model_name=route.model_name,
            runtime_policy=runtime_policy,
        )
        launch_payload = {
            **launch_payload,
            "workspace_path": self._worker_workspace_path(attempt.id),
        }
        with self._runtime_lock:
            attempt = self.orchestration.record_attempt(
                attempt.model_copy(
                    update={
                        "workspace_id": workspace_reservation.sandbox_id,
                        "lease_key": f"lease:{attempt.id}",
                        "model_route_id": route.id,
                        "compiled_worker_config_json": launch_payload,
                    }
                )
            )
            self._sync_canonical_state()
        self._publish_lifecycle_event(
            task=task,
            attempt=attempt,
            event_type="attempt.opened",
            source="orchestrator",
            payload_json={
                "workspace_path": str(workspace_reservation.workspace_path),
                "sandbox_id": workspace_reservation.sandbox_id,
                "route_reason": route.route_reason,
                "route_model_name": route.model_name,
            },
            route_model_name=route.model_name,
            route_reason=route.route_reason,
        )
        health = self.openhands_client.health_probe()
        with self._runtime_lock:
            published_event = self.event_service.publish_route(route)
        bootstrap_call = None
        processed_stream_events: tuple[str, ...] = ()
        artifact_ids: tuple[str, ...] = ()
        failure_reason: str | None = None
        with self._runtime_lock:
            final_task = self.orchestration.state.task(task.id)
            final_attempt = self.orchestration.state.attempt(attempt.id)
        approval_requirements = list(template.approval_requirements)
        if dispatch and self._approval_policy_requires_pre_dispatch(
            task=task,
            agent_definition=agent_definition,
            approval_requirements=approval_requirements,
        ):
            approval_reason = self._approval_reason(
                task=task,
                approval_requirements=approval_requirements,
                agent_definition=agent_definition,
            )
            with self._runtime_lock:
                request = self.orchestration.request_approval(
                    task_id=task.id,
                    task_attempt_id=attempt.id,
                    approval_type=approval_requirements[0] if approval_requirements else "operator_confirmation",
                    reason=approval_reason,
                )
            self._persist_memory_entry(
                task=task,
                content=f"Approval requested for {task.title}: {request.reason}",
                memory_layer=MemoryLayer.EPISODIC,
                metadata_json={
                    "kind": "approval_request",
                    "approval_request_id": request.id,
                    "approval_type": request.approval_type,
                },
            )
            self._publish_lifecycle_event(
                task=task,
                attempt=attempt,
                event_type="attempt.waiting_for_approval",
                source="orchestrator",
                payload_json={
                    "approval_request_id": request.id,
                    "approval_type": request.approval_type,
                    "reason": approval_reason,
                    "approval_requirements": approval_requirements,
                },
                route_model_name=route.model_name,
                route_reason=route.route_reason,
            )
            with self._runtime_lock:
                self._sync_canonical_state()
                final_task = self.orchestration.state.task(task.id)
                final_attempt = self.orchestration.state.attempt(attempt.id)
            return LocalTaskRunReport(
                workflow_run_id=final_task.workflow_run_id,
                task_key=final_task.task_key,
                route_model_name=route.model_name,
                launch_payload=launch_payload,
                openhands_health=health,
                bootstrap_call=None,
                published_event=published_event,
                task_state=final_task.state.value,
                attempt_state=final_attempt.state.value,
                workflow_status=self.orchestration.state.graph.workflow_run.status.value,
                stream_event_types=(),
                artifact_ids=(),
                failure_reason=approval_reason,
            )
        if dispatch:
            dispatch_idempotency_key = self.storage.redis_wire.idempotency_key(f"dispatch:{attempt.id}")
            if not self.storage.idempotency_store.claim(
                dispatch_idempotency_key,
                int(self.settings.autoweave_lease_ttl_seconds),
                value={"attempt_id": attempt.id, "task_id": task.id},
            ):
                with self._runtime_lock:
                    final_attempt = self.orchestration.abort_attempt(attempt.id)
                self._publish_lifecycle_event(
                    task=final_task,
                    attempt=final_attempt,
                    event_type="attempt.duplicate_dispatch_suppressed",
                    source="redis",
                    payload_json={"idempotency_key": dispatch_idempotency_key},
                    route_model_name=route.model_name,
                    route_reason=route.route_reason,
                )
                with self._runtime_lock:
                    self._sync_canonical_state()
                return LocalTaskRunReport(
                    workflow_run_id=final_task.workflow_run_id,
                    task_key=final_task.task_key,
                    route_model_name=route.model_name,
                    launch_payload=launch_payload,
                    openhands_health=health,
                    bootstrap_call=None,
                    published_event=published_event,
                    task_state=final_task.state.value,
                    attempt_state=final_attempt.state.value,
                    workflow_status=self.orchestration.state.graph.workflow_run.status.value,
                    stream_event_types=(),
                    artifact_ids=(),
                    failure_reason="duplicate_dispatch_suppressed",
                )
            if not self.storage.lease_manager.acquire(
                attempt.lease_key or self.storage.redis_wire.lease_key(attempt.id),
                int(self.settings.autoweave_lease_ttl_seconds),
            ):
                with self._runtime_lock:
                    final_attempt = self.orchestration.abort_attempt(attempt.id)
                    final_task = self.orchestration.block_task(task.id, reason="lease_unavailable")
                self._publish_lifecycle_event(
                    task=final_task,
                    attempt=final_attempt,
                    event_type="attempt.lease_unavailable",
                    source="redis",
                    payload_json={"lease_key": attempt.lease_key},
                    route_model_name=route.model_name,
                    route_reason=route.route_reason,
                )
                with self._runtime_lock:
                    self._sync_canonical_state()
                return LocalTaskRunReport(
                    workflow_run_id=final_task.workflow_run_id,
                    task_key=final_task.task_key,
                    route_model_name=route.model_name,
                    launch_payload=launch_payload,
                    openhands_health=health,
                    bootstrap_call=None,
                    published_event=published_event,
                    task_state=final_task.state.value,
                    attempt_state=final_attempt.state.value,
                    workflow_status=self.orchestration.state.graph.workflow_run.status.value,
                    stream_event_types=(),
                    artifact_ids=(),
                    failure_reason="lease_unavailable",
                )
            with self._runtime_lock:
                final_task = self.orchestration.start_task(task.id)
                final_attempt = self.orchestration.dispatch_attempt(attempt.id)
                final_attempt = self.orchestration.start_attempt(attempt.id)
                self._sync_canonical_state()
            try:
                bootstrap_call = self.openhands_client.bootstrap_attempt(launch_payload)
                self.storage.lease_manager.heartbeat(
                    attempt.lease_key or self.storage.redis_wire.lease_key(attempt.id),
                    int(self.settings.autoweave_lease_ttl_seconds),
                )
                self._publish_lifecycle_event(
                    task=final_task,
                    attempt=final_attempt,
                    event_type="attempt.dispatched",
                    source="orchestrator",
                    payload_json={"bootstrap_ok": bootstrap_call.ok, "bootstrap_path": bootstrap_call.path},
                    route_model_name=route.model_name,
                    route_reason=route.route_reason,
                )
                if bootstrap_call.ok:
                    combined_stream, replay_artifact_ids = self._collect_openhands_stream(
                        task=final_task,
                        attempt=final_attempt,
                        bootstrap_call=bootstrap_call,
                        stream_events=stream_events,
                    )
                    if combined_stream:
                        final_task, final_attempt, processed_stream_events, artifact_ids = self._process_openhands_stream(
                            task=final_task,
                            attempt=final_attempt,
                            stream_events=combined_stream,
                        )
                        failure_reason = next(
                            (
                                event.message
                                for event in reversed(combined_stream)
                                if event.outcome in {"error", "timeout", "stuck"} or event.event_type == "error"
                            ),
                            None,
                        )
                        if final_task.state == TaskState.FAILED and not failure_reason:
                            failure_reason = str(final_task.output_json.get("result_summary", "")).strip() or None
                        artifact_ids = tuple((*artifact_ids, *replay_artifact_ids))
                        self._sync_canonical_state()
                        retryable_reason = self._retryable_failure_reason(combined_stream)
                        max_attempts = self._retry_policy_max_attempts()
                        if (
                            dispatch
                            and retryable_reason is not None
                            and final_task.state == TaskState.BLOCKED
                            and final_attempt.state == AttemptState.ORPHANED
                            and final_attempt.attempt_number < max_attempts
                        ):
                            backoff_seconds = self._retry_policy_backoff_seconds()
                            self._publish_lifecycle_event(
                                task=final_task,
                                attempt=final_attempt,
                                event_type="attempt.retry_scheduled",
                                source="orchestrator",
                                payload_json={
                                    "reason": retryable_reason,
                                    "attempt_number": final_attempt.attempt_number,
                                    "max_attempts": max_attempts,
                                    "backoff_seconds": backoff_seconds,
                                },
                                route_model_name=route.model_name,
                                route_reason=route.route_reason,
                            )
                            if backoff_seconds > 0:
                                time.sleep(backoff_seconds)
                            retry_task = self.orchestration.unblock_task(final_task.id)
                            self._sync_canonical_state()
                            retry_report = self._run_task(
                                task=retry_task,
                                dispatch=dispatch,
                                stream_events=stream_events,
                            )
                            return replace(
                                retry_report,
                                stream_event_types=tuple((*processed_stream_events, *retry_report.stream_event_types)),
                                artifact_ids=tuple((*artifact_ids, *retry_report.artifact_ids)),
                            )
                    else:
                        artifact_ids = replay_artifact_ids
                else:
                    with self._runtime_lock:
                        final_task, final_attempt = self.orchestration.finalize_attempt_failure(
                            task.id,
                            attempt.id,
                            reason=bootstrap_call.error or bootstrap_call.response_text or "openhands bootstrap failed",
                            recoverable=False,
                        )
                    failure_reason = bootstrap_call.error or bootstrap_call.response_text or "openhands bootstrap failed"
                    with self._runtime_lock:
                        self._sync_canonical_state()
            finally:
                self.storage.lease_manager.release(attempt.lease_key or self.storage.redis_wire.lease_key(attempt.id))
        else:
            with self._runtime_lock:
                self._sync_canonical_state()
        return LocalTaskRunReport(
            workflow_run_id=final_task.workflow_run_id,
            task_key=final_task.task_key,
            route_model_name=route.model_name,
            launch_payload=launch_payload,
            openhands_health=health,
            bootstrap_call=bootstrap_call,
            published_event=published_event,
            task_state=final_task.state.value,
            attempt_state=final_attempt.state.value,
            workflow_status=self.orchestration.state.graph.workflow_run.status.value,
            stream_event_types=processed_stream_events,
            artifact_ids=artifact_ids,
            failure_reason=failure_reason,
        )

    def _probe_postgres_health(self) -> str:
        if not self.settings.postgres_url.strip():
            return "disabled (POSTGRES_URL not configured)"
        try:
            import psycopg

            schema = self.settings.autoweave_postgres_schema
            with psycopg.connect(self.settings.postgres_url, autocommit=True, connect_timeout=5) as conn:
                database = str(conn.execute("SELECT current_database()").fetchone()[0])
                table_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = %s
                        """,
                        (schema,),
                    ).fetchone()[0]
                )
            mode = "active" if self.settings.autoweave_canonical_backend == "postgres" else "reachable"
            return f"ok ({mode}; database={database}; schema={schema}; tables={table_count})"
        except Exception as exc:
            return f"error ({exc})"

    def _probe_neo4j_health(self) -> str:
        if not self.settings.neo4j_url.strip():
            return "disabled (NEO4J_URL not configured)"
        try:
            from neo4j import GraphDatabase

            auth = None
            if self.settings.neo4j_username or self.settings.neo4j_password:
                auth = (self.settings.neo4j_username, self.settings.neo4j_password)
            driver = GraphDatabase.driver(self.settings.neo4j_url, auth=auth, connection_timeout=5.0)
            try:
                driver.verify_connectivity()
            finally:
                driver.close()
            mode = "active" if self.settings.autoweave_graph_backend == "neo4j" else "reachable"
            return f"ok ({mode}; host={self.settings.neo4j_target().host})"
        except Exception as exc:
            return f"error ({exc})"

    def _probe_redis_health(self) -> str:
        try:
            from autoweave.storage.coordination import RedisClient

            return "ok" if RedisClient(self.settings.redis_url).ping() else "error (ping returned false)"
        except Exception as exc:
            return f"error ({exc})"

    def _probe_artifact_store_health(self) -> str:
        artifact_root = self.settings.artifact_store_path()
        probe_path = artifact_root / ".autoweave-healthcheck"
        payload = json.dumps({"probe": "artifact_store", "timestamp": time.time()}, sort_keys=True)
        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            probe_path.write_text(payload, encoding="utf-8")
            echoed = probe_path.read_text(encoding="utf-8")
            if echoed != payload:
                return "error (write/read mismatch)"
            return f"ok (root={artifact_root})"
        except Exception as exc:
            return f"error ({exc})"
        finally:
            if probe_path.exists():
                probe_path.unlink()

    def _probe_celery_health(self) -> str:
        backend = str(self.runtime_config.execution_backend).strip().lower()
        if backend != "celery":
            return "disabled (execution_backend=inline)"
        from autoweave.celery_queue import CeleryWorkflowDispatcher

        dispatcher = CeleryWorkflowDispatcher.from_runtime(self)
        return dispatcher.worker_health()

    def doctor(self) -> LocalRuntimeDoctorReport:
        ready_task_keys = tuple(
            self.orchestration.state.task(task_id).task_key
            for task_id in self.orchestration.schedule().ready_tasks
        )
        return LocalRuntimeDoctorReport(
            project_root=self.settings.project_root,
            loaded_env_files=self.settings.loaded_env_files,
            config_paths={
                "workflow": self.settings.resolve_config_path(self.settings.autoweave_default_workflow),
                "runtime": self.settings.resolve_config_path(self.settings.autoweave_runtime_config),
                "storage": self.settings.resolve_config_path(self.settings.autoweave_storage_config),
                "vertex": self.settings.resolve_config_path(self.settings.autoweave_vertex_config),
                "observability": self.settings.resolve_config_path(self.settings.autoweave_observability_config),
            },
            vertex_worker_env=self.settings.worker_environment(),
            canonical_backend=self.settings.autoweave_canonical_backend,
            graph_backend=self.settings.autoweave_graph_backend,
            execution_backend=str(self.runtime_config.execution_backend).strip().lower() or "inline",
            postgres_target=json.dumps(self.settings.postgres_target().redacted_dump(), sort_keys=True),
            neo4j_target=json.dumps(self.settings.neo4j_target().redacted_dump(), sort_keys=True),
            redis_target=json.dumps(self.settings.redis_target().redacted_dump(), sort_keys=True),
            artifact_store_path=self.settings.artifact_store_path(),
            postgres_health=self._probe_postgres_health(),
            neo4j_health=self._probe_neo4j_health(),
            redis_health=self._probe_redis_health(),
            artifact_store_health=self._probe_artifact_store_health(),
            celery_health=self._probe_celery_health(),
            openhands_target=self.settings.openhands_target().base_url,
            openhands_health=self.openhands_client.health_probe(),
            openhands_worker_timeout_seconds=self.settings.openhands_worker_timeout_seconds,
            openhands_poll_timeout_seconds=self.settings.autoweave_openhands_poll_timeout_seconds,
            ready_task_keys=ready_task_keys,
        )

    def run_example(
        self,
        *,
        dispatch: bool = False,
        stream_events: Iterable[Mapping[str, Any] | OpenHandsStreamEvent] | None = None,
    ) -> LocalExampleRunReport:
        self._ensure_canonical_graph_seeded()
        schedule = self.orchestration.schedule()
        if not schedule.ready_tasks:
            self._reset_example_workflow_run()
            schedule = self.orchestration.schedule()
        if not schedule.ready_tasks:
            raise RuntimeError("example workflow has no runnable tasks")

        task = self.orchestration.state.task(schedule.ready_tasks[0])
        task_report = self._run_task(
            task=task,
            dispatch=dispatch,
            stream_events=stream_events,
        )
        return LocalExampleRunReport(
            workflow_run_id=task_report.workflow_run_id,
            task_key=task_report.task_key,
            ready_task_keys=tuple(self.orchestration.state.task(task_id).task_key for task_id in schedule.ready_tasks),
            route_model_name=task_report.route_model_name,
            launch_payload=task_report.launch_payload,
            openhands_health=task_report.openhands_health,
            bootstrap_call=task_report.bootstrap_call,
            published_event=task_report.published_event,
            task_state=task_report.task_state,
            attempt_state=task_report.attempt_state,
            workflow_status=task_report.workflow_status,
            stream_event_types=task_report.stream_event_types,
            artifact_ids=task_report.artifact_ids,
            failure_reason=task_report.failure_reason,
        )

    def purge_workflow_runs(
        self,
        workflow_run_ids: Iterable[str],
        *,
        clear_projection_namespace: bool = False,
    ) -> LocalCleanupReport:
        selected_run_ids = tuple(dict.fromkeys(run_id.strip() for run_id in workflow_run_ids if run_id and run_id.strip()))
        repository = self.storage.workflow_repository
        if not hasattr(repository, "delete_workflow_run"):
            raise RuntimeError("workflow repository does not support run deletion")

        purged_run_ids: list[str] = []
        missing_run_ids: list[str] = []
        deleted_paths: list[Path] = []

        for workflow_run_id in selected_run_ids:
            try:
                workflow_run = repository.get_graph(workflow_run_id).workflow_run
                tasks = repository.list_tasks_for_run(workflow_run_id)
                attempts = repository.list_attempts_for_run(workflow_run_id)
                artifacts = repository.list_artifacts_for_run(workflow_run_id)
            except KeyError:
                workflow_run = None
                tasks = []
                attempts = []
                artifacts = []
            deleted = repository.delete_workflow_run(workflow_run_id)
            if not deleted:
                missing_run_ids.append(workflow_run_id)
                continue
            self._purge_memory_store_entries(
                workflow_run_id=workflow_run_id,
                project_id=workflow_run.project_id if workflow_run is not None else None,
                task_ids={task.id for task in tasks},
            )
            purged_run_ids.append(workflow_run_id)
            deleted_paths.extend(self._cleanup_workflow_run_files(workflow_run_id, attempts=attempts, artifacts=artifacts))

        projection_cleared = False
        if clear_projection_namespace and hasattr(self.storage.graph_projection, "clear_namespace"):
            self.storage.graph_projection.clear_namespace()
            projection_cleared = True

        return LocalCleanupReport(
            selected_run_ids=selected_run_ids,
            purged_run_ids=tuple(purged_run_ids),
            missing_run_ids=tuple(missing_run_ids),
            deleted_paths=tuple(deleted_paths),
            projection_cleared=projection_cleared,
        )

    def run_workflow(
        self,
        *,
        request: str,
        dispatch: bool = False,
        max_steps: int = 8,
        stream_events_by_task: Mapping[str, Iterable[Mapping[str, Any] | OpenHandsStreamEvent]] | None = None,
    ) -> LocalWorkflowRunReport:
        self._reset_workflow_run(root_input_json={"user_request": request})
        return self._advance_current_workflow(
            request=request,
            dispatch=dispatch,
            max_steps=max_steps,
            stream_events_by_task=stream_events_by_task,
        )

    def continue_workflow_run(
        self,
        *,
        workflow_run_id: str,
        dispatch: bool = False,
        max_steps: int = 8,
        stream_events_by_task: Mapping[str, Iterable[Mapping[str, Any] | OpenHandsStreamEvent]] | None = None,
    ) -> LocalWorkflowRunReport:
        self.load_workflow_run(workflow_run_id)
        return self._advance_current_workflow(
            request=self._workflow_request(),
            dispatch=dispatch,
            max_steps=max_steps,
            stream_events_by_task=stream_events_by_task,
        )

    def answer_human_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        answer_text: str,
        answered_by: str,
        dispatch: bool = True,
        max_steps: int = 8,
    ) -> LocalWorkflowRunReport:
        self.load_workflow_run(workflow_run_id)
        request = self.orchestration.state.human_requests[request_id]
        task = self.orchestration.state.task(request.task_id)
        active_attempt = self._latest_active_attempt(task.id)
        if active_attempt is not None:
            self.orchestration.abort_attempt(active_attempt.id)
        task = self._apply_human_answer_to_task_input(
            task=task,
            request=request,
            answer_text=answer_text,
        )
        self.orchestration.answer_human_request(request_id, answer_text=answer_text, answered_by=answered_by)
        self._persist_memory_entry(
            task=task,
            content=f"Human answer for {task.title}: {request.question} Answer: {answer_text}",
            memory_layer=MemoryLayer.SEMANTIC,
            metadata_json={
                "kind": "human_answer",
                "human_request_id": request.id,
                "answered_by": answered_by,
            },
        )
        self._sync_canonical_state()
        return self._advance_current_workflow(
            request=self._workflow_request(),
            dispatch=dispatch,
            max_steps=max_steps,
        )

    def _cleanup_workflow_run_files(
        self,
        workflow_run_id: str,
        *,
        attempts: Iterable[TaskAttemptRecord],
        artifacts: Iterable[ArtifactRecord],
    ) -> list[Path]:
        deleted_paths: list[Path] = []
        artifact_root = self.settings.artifact_store_path() / workflow_run_id
        self._remove_path_if_exists(artifact_root, deleted_paths)
        for artifact in artifacts:
            artifact_dir = self.settings.artifact_store_path() / artifact.workflow_run_id / artifact.task_id / artifact.id
            self._remove_path_if_exists(artifact_dir, deleted_paths)
        for attempt in attempts:
            workspace_path = self.worker_adapter.workspace_policy.workspace_path_for_attempt(attempt.id)
            self._remove_path_if_exists(workspace_path, deleted_paths)
        return deleted_paths

    def _purge_memory_store_entries(
        self,
        *,
        workflow_run_id: str,
        project_id: str | None,
        task_ids: set[str],
    ) -> tuple[str, ...]:
        metadata_task_ids = set(task_ids)
        return self.storage.memory_store.delete_matching(
            lambda entry: (
                (entry.scope_type == "workflow_run" and entry.scope_id == workflow_run_id)
                or (entry.scope_type == "task" and entry.scope_id in metadata_task_ids)
                or (
                    entry.scope_type == "project"
                    and project_id is not None
                    and entry.scope_id == project_id
                    and (
                        str(entry.metadata_json.get("workflow_run_id") or "").strip() == workflow_run_id
                        or str(entry.metadata_json.get("task_id") or "").strip() in metadata_task_ids
                    )
                )
            )
        )

    @staticmethod
    def _remove_path_if_exists(path: Path, deleted_paths: list[Path]) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted_paths.append(path)

    def resolve_approval_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        approved: bool,
        resolved_by: str,
        dispatch: bool = True,
        max_steps: int = 8,
    ) -> LocalWorkflowRunReport:
        self.load_workflow_run(workflow_run_id)
        request = self.orchestration.state.approval_requests[request_id]
        task = self.orchestration.state.task(request.task_id)
        active_attempt = self._latest_active_attempt(task.id)
        if active_attempt is not None:
            self.orchestration.abort_attempt(active_attempt.id)
        self.orchestration.resolve_approval(request_id, approved=approved, resolved_by=resolved_by)
        decision = "approved" if approved else "rejected"
        self._persist_memory_entry(
            task=task,
            content=f"Approval {decision} for {task.title}: {request.reason}",
            memory_layer=MemoryLayer.SEMANTIC,
            metadata_json={
                "kind": "approval_resolution",
                "approval_request_id": request.id,
                "approval_type": request.approval_type,
                "resolved_by": resolved_by,
                "approved": approved,
            },
        )
        self._sync_canonical_state()
        return self._advance_current_workflow(
            request=self._workflow_request(),
            dispatch=dispatch,
            max_steps=max_steps,
        )

    def _advance_current_workflow(
        self,
        *,
        request: str,
        dispatch: bool,
        max_steps: int,
        stream_events_by_task: Mapping[str, Iterable[Mapping[str, Any] | OpenHandsStreamEvent]] | None = None,
    ) -> LocalWorkflowRunReport:
        step_reports_by_index: dict[int, LocalTaskRunReport] = {}
        remaining_steps = 1 if not dispatch else max(1, max_steps)

        if not dispatch:
            launch_index = 0
            while remaining_steps > 0:
                with self._runtime_lock:
                    schedule = self.orchestration.schedule()
                    if not schedule.ready_tasks:
                        break
                    task = self.orchestration.state.task(schedule.ready_tasks[0])
                    task_stream = None
                    if stream_events_by_task is not None:
                        task_stream = stream_events_by_task.get(task.task_key)
                step_report = self._run_task(task=task, dispatch=dispatch, stream_events=task_stream)
                step_reports_by_index[launch_index] = step_report
                launch_index += 1
                remaining_steps -= 1
                if step_report.attempt_state in {"needs_input", "paused"} or step_report.task_state in {
                    "waiting_for_human",
                    "waiting_for_approval",
                }:
                    break
            with self._runtime_lock:
                final_schedule = self.orchestration.schedule()
                open_human_questions = tuple(
                    request.question
                    for request in self.orchestration.state.human_requests.values()
                    if request.status.value == "open"
                )
                open_approval_reasons = tuple(
                    request.reason
                    for request in self.orchestration.state.approval_requests.values()
                    if request.status.value == "requested"
                )
            ordered_reports = tuple(step_reports_by_index[index] for index in sorted(step_reports_by_index))
            with self._runtime_lock:
                workflow_run_id = self.orchestration.state.graph.workflow_run.id
                workflow_status = self.orchestration.state.graph.workflow_run.status.value
                ready_task_keys = tuple(
                    self.orchestration.state.task(task_id).task_key for task_id in final_schedule.ready_tasks
                )
            return LocalWorkflowRunReport(
                workflow_run_id=workflow_run_id,
                request=request,
                workflow_status=workflow_status,
                dispatched_task_keys=tuple(step.task_key for step in ordered_reports),
                ready_task_keys=ready_task_keys,
                open_human_questions=open_human_questions,
                open_approval_reasons=open_approval_reasons,
                step_reports=ordered_reports,
            )

        max_parallel_dispatches = self._max_parallel_dispatches()
        running_futures: dict[Future[LocalTaskRunReport], tuple[int, str]] = {}
        next_launch_index = 0
        stop_launching = False

        with ThreadPoolExecutor(max_workers=max_parallel_dispatches) as executor:
            while remaining_steps > 0 or running_futures:
                if not stop_launching and remaining_steps > 0:
                    running_task_ids = {task_id for _, task_id in running_futures.values()}
                    with self._runtime_lock:
                        schedule = self.orchestration.schedule()
                        active_attempt_count = len(self.orchestration.active_attempts())
                        ready_task_ids = [
                            task_id
                            for task_id in schedule.ready_tasks
                            if task_id not in running_task_ids
                        ]
                    available_capacity = max(
                        0,
                        max_parallel_dispatches - max(len(running_futures), active_attempt_count),
                    )
                    for task_id in ready_task_ids[:available_capacity]:
                        if remaining_steps <= 0:
                            break
                        with self._runtime_lock:
                            task = self.orchestration.state.task(task_id)
                            if task.state != TaskState.READY:
                                continue
                            task_stream = None
                            if stream_events_by_task is not None:
                                task_stream = stream_events_by_task.get(task.task_key)
                        future = executor.submit(
                            self._run_task,
                            task=task,
                            dispatch=True,
                            stream_events=task_stream,
                        )
                        running_futures[future] = (next_launch_index, task.id)
                        next_launch_index += 1
                        remaining_steps -= 1
                if not running_futures:
                    break
                completed, _ = wait(tuple(running_futures), return_when=FIRST_COMPLETED)
                for future in completed:
                    launch_index, _task_id = running_futures.pop(future)
                    step_report = future.result()
                    step_reports_by_index[launch_index] = step_report
                    if step_report.attempt_state in {"needs_input", "paused"} or step_report.task_state in {
                        "waiting_for_human",
                        "waiting_for_approval",
                    }:
                        stop_launching = True

        with self._runtime_lock:
            final_schedule = self.orchestration.schedule()
            open_human_questions = tuple(
                request.question
                for request in self.orchestration.state.human_requests.values()
                if request.status.value == "open"
            )
            open_approval_reasons = tuple(
                request.reason
                for request in self.orchestration.state.approval_requests.values()
                if request.status.value == "requested"
            )
            workflow_run_id = self.orchestration.state.graph.workflow_run.id
            workflow_status = self.orchestration.state.graph.workflow_run.status.value
            ready_task_keys = tuple(
                self.orchestration.state.task(task_id).task_key for task_id in final_schedule.ready_tasks
            )
        ordered_reports = tuple(step_reports_by_index[index] for index in sorted(step_reports_by_index))
        return LocalWorkflowRunReport(
            workflow_run_id=workflow_run_id,
            request=request,
            workflow_status=workflow_status,
            dispatched_task_keys=tuple(step.task_key for step in ordered_reports),
            ready_task_keys=ready_task_keys,
            open_human_questions=open_human_questions,
            open_approval_reasons=open_approval_reasons,
            step_reports=ordered_reports,
        )


def build_local_runtime(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Any | None = None,
    bootstrap_path: str = "/api/conversations",
    workflow_run_id: str | None = None,
) -> LocalRuntime:
    return LocalRuntime.build(
        root=root,
        environ=environ,
        transport=transport,
        bootstrap_path=bootstrap_path,
        workflow_run_id=workflow_run_id,
    )
