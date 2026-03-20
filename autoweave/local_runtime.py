"""Terminal-first local runtime composition for AutoWeave."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from autoweave.compiler.loader import CanonicalConfigLoader
from autoweave.events.service import EventService
from autoweave.models import AttemptState, ArtifactRecord, ArtifactStatus, EventRecord, TaskAttemptRecord, TaskRecord, TaskState, generate_id
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
    extract_openhands_stream_events,
    normalize_openhands_stream_event,
    stream_event_to_artifact,
    WorkspacePolicy,
)
from autoweave.workflows import build_workflow_graph
from autoweave.config_models import ObservabilityConfig, RuntimeConfig, StorageConfig, VertexConfig, WorkflowDefinitionConfig
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


@dataclass(slots=True)
class LocalRuntime:
    settings: LocalEnvironmentSettings
    runtime_config: RuntimeConfig
    storage_config: StorageConfig
    vertex_config: VertexConfig
    observability_config: ObservabilityConfig
    workflow_definition: WorkflowDefinitionConfig
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

    @classmethod
    def build(
        cls,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        transport: Any | None = None,
        bootstrap_path: str = "/api/conversations",
    ) -> "LocalRuntime":
        settings = LocalEnvironmentSettings.load(root=root, environ=environ)
        settings.ensure_local_layout()

        loader = CanonicalConfigLoader(root_dir=settings.project_root)
        runtime_config = loader.load_runtime_config(settings.autoweave_runtime_config)
        storage_config = loader.load_storage_config(settings.autoweave_storage_config)
        vertex_config = loader.load_vertex_config(settings.autoweave_vertex_config)
        observability_config = loader.load_observability_config(settings.autoweave_observability_config)
        workflow_definition = loader.load_workflow_definition(settings.autoweave_default_workflow)

        workflow_graph = build_workflow_graph(
            workflow_definition,
            project_id="local",
            team_id="local",
            workflow_definition_id=f"{workflow_definition.name}:{workflow_definition.version}",
        )

        storage = build_local_storage_wiring(settings)
        try:
            canonical_graph = storage.workflow_repository.get_graph(workflow_graph.workflow_run.id)
        except KeyError:
            storage.workflow_repository.save_graph(workflow_graph)
            canonical_graph = storage.workflow_repository.get_graph(workflow_graph.workflow_run.id)
        router = VertexModelRouter(vertex_config)
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
            storage=storage,
            router=router,
            event_service=event_service,
            observability=observability,
            worker_adapter=worker_adapter,
            openhands_client=openhands_client,
            orchestration=orchestration,
        )
        runtime._last_persisted_graph_signature = runtime._graph_structure_signature()
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

    def _worker_workspace_path(self, attempt_id: str) -> str:
        return str(Path("/workspace") / "workspaces" / attempt_id)

    def _graph_structure_signature(self) -> tuple[str, int, tuple[str, ...], tuple[str, ...]]:
        graph = self.orchestration.state.graph
        return (
            graph.workflow_run.id,
            graph.workflow_run.graph_revision,
            tuple(task.id for task in graph.tasks),
            tuple(edge.id for edge in graph.edges),
        )

    def _reset_example_workflow_run(self) -> None:
        workflow_definition_id = f"{self.workflow_definition.name}:{self.workflow_definition.version}"
        fresh_graph = build_workflow_graph(
            self.workflow_definition,
            project_id="local",
            team_id="local",
            workflow_definition_id=workflow_definition_id,
            workflow_run_id=f"{workflow_definition_id.replace(':', '_')}_run_{generate_id('demo')}",
        )
        self.storage.workflow_repository.save_graph(fresh_graph)
        canonical_graph = self.storage.workflow_repository.get_graph(fresh_graph.workflow_run.id)
        self.orchestration = OrchestrationService(WorkflowRunState.from_graph(canonical_graph))
        self._last_persisted_graph_signature = self._graph_structure_signature()

    def _sync_canonical_state(self) -> None:
        """Persist the authoritative orchestration snapshot through the repository wiring."""

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

        final_info = self.openhands_client.wait_for_conversation(
            conversation_id,
            timeout_seconds=float(self.settings.autoweave_openhands_poll_timeout_seconds),
            poll_interval_seconds=float(self.settings.autoweave_openhands_poll_interval_seconds),
        )
        event_payloads = self.openhands_client.list_all_conversation_events(conversation_id)
        normalized.extend(extract_openhands_stream_events({"items": event_payloads}))
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

        debug_payload = {
            "conversation_id": conversation_id,
            "execution_status": execution_status,
            "bootstrap": bootstrap_call.response_json,
            "conversation": final_info.response_json,
            "events": event_payloads,
        }
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
        for stream_event in stream_events:
            emitted_types.append(stream_event.event_type)
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
                continue
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
                continue

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
                current_task, current_attempt = self.orchestration.finalize_attempt_success(current_task.id, current_attempt.id)
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
                current_task, current_attempt = self.orchestration.finalize_attempt_failure(
                    current_task.id,
                    current_attempt.id,
                    reason=stream_event.message or outcome or "worker_failure",
                    recoverable=False,
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
            ready_task_keys=ready_task_keys,
        )

    def run_example(
        self,
        *,
        dispatch: bool = False,
        stream_events: Iterable[Mapping[str, Any] | OpenHandsStreamEvent] | None = None,
    ) -> LocalExampleRunReport:
        schedule = self.orchestration.schedule()
        if not schedule.ready_tasks:
            self._reset_example_workflow_run()
            schedule = self.orchestration.schedule()
        if not schedule.ready_tasks:
            raise RuntimeError("example workflow has no runnable tasks")

        task = self.orchestration.state.task(schedule.ready_tasks[0])
        template = next(template for template in self.workflow_definition.task_templates if template.key == task.task_key)
        attempt = self.orchestration.open_attempt(
            task_id=task.id,
            agent_definition_id=f"{task.assigned_role}-agent",
        )
        route = self.router.select_route(task=task, attempt=attempt, hints=list(template.route_hints))
        workspace_reservation = self.worker_adapter.reserve_workspace(attempt=attempt)
        launch_payload = self.worker_adapter.compile_launch_payload(
            task=task,
            attempt=attempt,
            route_reason=route.route_reason,
            route_model_name=route.model_name,
            runtime_policy=self.runtime_policy,
        )
        launch_payload = {
            **launch_payload,
            "workspace_path": self._worker_workspace_path(attempt.id),
        }
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
        published_event = self.event_service.publish_route(route)
        bootstrap_call = None
        processed_stream_events: tuple[str, ...] = ()
        artifact_ids: tuple[str, ...] = ()
        failure_reason: str | None = None
        final_task = self.orchestration.state.task(task.id)
        final_attempt = self.orchestration.state.attempt(attempt.id)
        if dispatch:
            final_task = self.orchestration.start_task(task.id)
            final_attempt = self.orchestration.dispatch_attempt(attempt.id)
            final_attempt = self.orchestration.start_attempt(attempt.id)
            self._sync_canonical_state()
            bootstrap_call = self.openhands_client.bootstrap_attempt(launch_payload)
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
                else:
                    artifact_ids = replay_artifact_ids
            else:
                final_task, final_attempt = self.orchestration.finalize_attempt_failure(
                    task.id,
                    attempt.id,
                    reason=bootstrap_call.error or bootstrap_call.response_text or "openhands bootstrap failed",
                    recoverable=False,
                )
                failure_reason = bootstrap_call.error or bootstrap_call.response_text or "openhands bootstrap failed"
                self._sync_canonical_state()
        else:
            self._sync_canonical_state()
        return LocalExampleRunReport(
            workflow_run_id=final_task.workflow_run_id,
            task_key=final_task.task_key,
            ready_task_keys=tuple(self.orchestration.state.task(task_id).task_key for task_id in schedule.ready_tasks),
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


def build_local_runtime(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Any | None = None,
    bootstrap_path: str = "/api/conversations",
) -> LocalRuntime:
    return LocalRuntime.build(root=root, environ=environ, transport=transport, bootstrap_path=bootstrap_path)
