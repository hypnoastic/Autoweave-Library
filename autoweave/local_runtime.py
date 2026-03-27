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
from autoweave.models import ApprovalStatus, AttemptState, ArtifactRecord, ArtifactStatus, EventRecord, TaskAttemptRecord, TaskRecord, TaskState, generate_id
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
from autoweave.config_models import AgentDefinitionConfig, ObservabilityConfig, RuntimeConfig, StorageConfig, VertexConfig, WorkflowDefinitionConfig
from autoweave.events.schema import EventCorrelationContext, make_event
from autoweave.types import JsonDict


@dataclass(slots=True, frozen=True)
class LocalRuntimeDoctorReport:
    project_root: Path
    loaded_env_files: tuple[Path, ...]
    config_paths: dict[str, Path]
    vertex_worker_env: dict[str, str]
    postgres_target: str
    neo4j_target: str
    redis_target: str
    artifact_store_path: Path
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
            f"postgres={self.postgres_target}",
            f"neo4j={self.neo4j_target}",
            f"redis={self.redis_target}",
            f"artifact_store={self.artifact_store_path}",
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

    def _task_template(self, task_key: str):
        return next(template for template in self.workflow_definition.task_templates if template.key == task_key)

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
                    payload_json=payload_json or {},
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
        questions = extract_semantic_clarification_questions(stream_event.message)
        if not questions:
            return None
        return "\n".join(questions)

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
                self.orchestration.needs_input_attempt(current_attempt.id)
                self.orchestration.request_clarification(
                    task_id=current_task.id,
                    task_attempt_id=current_attempt.id,
                    question=stream_event.message or "Clarification requested by worker",
                    context_summary=str(stream_event.payload_json.get("context_summary", "")),
                )
                self._sync_canonical_state()
                current_task = self.orchestration.state.task(current_task.id)
                current_attempt = self.orchestration.state.attempt(current_attempt.id)
                break
            if stream_event.approval_required:
                self.orchestration.pause_attempt(current_attempt.id)
                self.orchestration.request_approval(
                    task_id=current_task.id,
                    task_attempt_id=current_attempt.id,
                    approval_type=str(stream_event.payload_json.get("approval_type", "review")),
                    reason=stream_event.message or "Approval requested by worker",
                )
                self._sync_canonical_state()
                current_task = self.orchestration.state.task(current_task.id)
                current_attempt = self.orchestration.state.attempt(current_attempt.id)
                break

            artifact = stream_event_to_artifact(stream_event, task=current_task, attempt=current_attempt)
            if artifact is not None:
                stored_artifact = self.storage.artifact_registry.put_artifact(artifact)
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
                self._sync_canonical_state()
            elif outcome in {"failure", "failed", "error"}:
                recoverable_failure = stream_event.payload_json.get("diagnostic_code") == "worker_empty_response_loop"
                current_task, current_attempt = self.orchestration.finalize_attempt_failure(
                    current_task.id,
                    current_attempt.id,
                    reason=stream_event.message or outcome or "worker_failure",
                    recoverable=recoverable_failure,
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
        template = self._task_template(task.task_key)
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
                self.orchestration.request_approval(
                    task_id=task.id,
                    task_attempt_id=attempt.id,
                    approval_type=approval_requirements[0] if approval_requirements else "operator_confirmation",
                    reason=approval_reason,
                )
            self._publish_lifecycle_event(
                task=task,
                attempt=attempt,
                event_type="attempt.waiting_for_approval",
                source="orchestrator",
                payload_json={"reason": approval_reason, "approval_requirements": approval_requirements},
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
            postgres_target=json.dumps(self.settings.postgres_target().redacted_dump(), sort_keys=True),
            neo4j_target=json.dumps(self.settings.neo4j_target().redacted_dump(), sort_keys=True),
            redis_target=json.dumps(self.settings.redis_target().redacted_dump(), sort_keys=True),
            artifact_store_path=self.settings.artifact_store_path(),
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
                attempts = repository.list_attempts_for_run(workflow_run_id)
                artifacts = repository.list_artifacts_for_run(workflow_run_id)
            except KeyError:
                attempts = []
                artifacts = []
            deleted = repository.delete_workflow_run(workflow_run_id)
            if not deleted:
                missing_run_ids.append(workflow_run_id)
                continue
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
        updated_input = dict(task.input_json)
        updated_input["latest_human_answer"] = {
            "request_id": request.id,
            "question": request.question,
            "answer_text": answer_text,
        }
        human_answers = updated_input.get("human_answers")
        if not isinstance(human_answers, dict):
            human_answers = {}
        human_answers[request.id] = answer_text
        updated_input["human_answers"] = human_answers
        self.orchestration.state.update_task(task.model_copy(update={"input_json": updated_input}))
        self.orchestration.answer_human_request(request_id, answer_text=answer_text, answered_by=answered_by)
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
