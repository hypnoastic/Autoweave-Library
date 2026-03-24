"""Shared service protocols that concrete workstreams implement."""

from __future__ import annotations

from typing import Protocol

from autoweave.config_models import (
    AgentDefinitionConfig,
    ObservabilityConfig,
    RuntimeConfig,
    StorageConfig,
    VertexConfig,
    WorkflowDefinitionConfig,
)
from autoweave.models import (
    ApprovalRequestRecord,
    ArtifactRecord,
    EventRecord,
    HumanRequestRecord,
    ModelRouteRecord,
    TaskAttemptRecord,
    TaskReadiness,
    TaskRecord,
    TypedMissResponse,
    WorkflowGraph,
    WorkflowRunRecord,
)
from autoweave.types import JsonDict


class ConfigLoader(Protocol):
    def load_agent_definition(self, role: str) -> AgentDefinitionConfig: ...

    def load_workflow_definition(self, name: str) -> WorkflowDefinitionConfig: ...

    def load_runtime_config(self) -> RuntimeConfig: ...

    def load_storage_config(self) -> StorageConfig: ...

    def load_vertex_config(self) -> VertexConfig: ...

    def load_observability_config(self) -> ObservabilityConfig: ...


class WorkflowRepository(Protocol):
    def list_workflow_runs(self) -> list[WorkflowRunRecord]: ...

    def get_graph(self, workflow_run_id: str) -> WorkflowGraph: ...

    def list_tasks_for_run(self, workflow_run_id: str) -> list[TaskRecord]: ...

    def list_attempts_for_run(self, workflow_run_id: str) -> list[TaskAttemptRecord]: ...

    def save_task(self, task: TaskRecord) -> TaskRecord: ...

    def save_attempt(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord: ...

    def list_active_attempts(self, workflow_run_id: str) -> list[TaskAttemptRecord]: ...

    def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]: ...

    def list_approval_requests_for_run(self, workflow_run_id: str) -> list[ApprovalRequestRecord]: ...

    def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]: ...

    def list_events(self, workflow_run_id: str) -> list[EventRecord]: ...


class ArtifactRegistry(Protocol):
    def put_artifact(self, artifact: ArtifactRecord, payload: object | None = None) -> ArtifactRecord: ...

    def get_upstream_artifacts(
        self,
        *,
        task_id: str,
        artifact_type: str | None = None,
        from_role: str | None = None,
        status: str | None = None,
    ) -> list[ArtifactRecord]: ...


class ContextResolver(Protocol):
    def get_task(self, task_id: str) -> TaskRecord: ...

    def search_memory(self, query: str, scope: str, top_k: int) -> list[str]: ...

    def get_related_code_context(self, query: str, file_filters: list[str] | None = None) -> list[str]: ...

    def resolve_typed_miss(self, reason: str, *, next_action: str) -> TypedMissResponse: ...


class HumanLoopService(Protocol):
    def open_request(self, request: HumanRequestRecord) -> HumanRequestRecord: ...

    def answer_request(self, request_id: str, answer_text: str, answered_by: str) -> HumanRequestRecord: ...

    def create_approval(self, request: ApprovalRequestRecord) -> ApprovalRequestRecord: ...


class ApprovalService(Protocol):
    def resolve(self, request_id: str, approved: bool, resolved_by: str) -> ApprovalRequestRecord: ...


class EventSink(Protocol):
    def emit(self, event: EventRecord) -> EventRecord: ...


class LeaseManager(Protocol):
    def acquire(self, lease_key: str, ttl_seconds: int) -> bool: ...

    def heartbeat(self, lease_key: str, ttl_seconds: int) -> None: ...

    def release(self, lease_key: str) -> None: ...


class ModelRouter(Protocol):
    def select_route(self, *, task: TaskRecord, attempt: TaskAttemptRecord, hints: list[str]) -> ModelRouteRecord: ...


class WorkerCompiler(Protocol):
    def compile_attempt_config(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        route: ModelRouteRecord,
        runtime_policy: JsonDict,
    ) -> JsonDict: ...


class WorkerRuntime(Protocol):
    def launch(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord: ...

    def resume(self, attempt: TaskAttemptRecord) -> TaskAttemptRecord: ...

    def cleanup(self, attempt: TaskAttemptRecord) -> None: ...


class Scheduler(Protocol):
    def evaluate(self, graph: WorkflowGraph) -> list[TaskReadiness]: ...

    def runnable_tasks(self, graph: WorkflowGraph) -> list[TaskRecord]: ...


class GraphProjectionBackend(Protocol):
    def project_event(self, event: EventRecord) -> None: ...

    def query_related_entities(self, entity_id: str, depth: int = 1) -> list[dict[str, str]]: ...


class ObservabilityExporter(Protocol):
    def record_route(self, route: ModelRouteRecord) -> None: ...

    def publish_metrics(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None: ...
