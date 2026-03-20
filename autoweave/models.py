"""Canonical domain models and enums for AutoWeave."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoweave.exceptions import StateTransitionError
from autoweave.types import JsonDict


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class TaskState(StrEnum):
    CREATED = "created"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    WAITING_FOR_HUMAN = "waiting_for_human"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptState(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    PAUSED = "paused"
    NEEDS_INPUT = "needs_input"
    SUCCEEDED = "succeeded"
    ERRORED = "errored"
    ABORTED = "aborted"
    ORPHANED = "orphaned"


class WorkflowRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ApprovalStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HumanRequestStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    CANCELLED = "cancelled"


class HumanRequestType(StrEnum):
    CLARIFICATION = "clarification"
    APPROVAL = "approval"
    BLOCKER = "blocker"
    STATE_TRANSITION = "state_transition"


class MemoryLayer(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    CODE = "code"
    GRAPH = "graph"


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EdgeType(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class MissingContextReason(StrEnum):
    NOT_FOUND = "not_found"
    NOT_INDEXED_YET = "not_indexed_yet"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    ACCESS_DENIED = "access_denied"
    NEEDS_HUMAN_INPUT = "needs_human_input"


class BaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimestampedRecord(BaseRecord):
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectRecord(TimestampedRecord):
    id: str = Field(default_factory=lambda: generate_id("proj"))
    slug: str
    name: str
    repo_url: str | None = None
    default_branch: str = "main"
    settings_json: JsonDict = Field(default_factory=dict)


class TeamRecord(TimestampedRecord):
    id: str = Field(default_factory=lambda: generate_id("team"))
    project_id: str
    name: str
    workflow_definition_id: str
    status: str = "active"


class AgentDefinitionRecord(TimestampedRecord):
    id: str = Field(default_factory=lambda: generate_id("agent"))
    project_id: str
    role: str
    name: str
    version: str
    soul_md: str
    playbook_yaml: str
    autoweave_yaml: str
    status: str = "active"


class WorkflowDefinitionRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("wfd"))
    project_id: str
    version: str
    content_yaml: str
    checksum: str
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowRunRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("wfr"))
    project_id: str
    team_id: str
    workflow_definition_id: str
    graph_revision: int = 1
    root_input_json: JsonDict = Field(default_factory=dict)
    status: WorkflowRunStatus = WorkflowRunStatus.CREATED
    started_at: datetime | None = None
    ended_at: datetime | None = None


class TaskRecord(TimestampedRecord):
    id: str = Field(default_factory=lambda: generate_id("task"))
    workflow_run_id: str
    task_key: str
    title: str
    description: str
    assigned_role: str
    state: TaskState = TaskState.CREATED
    priority: int = 100
    input_json: JsonDict = Field(default_factory=dict)
    output_json: JsonDict = Field(default_factory=dict)
    required_artifact_types_json: list[str] = Field(default_factory=list)
    produced_artifact_types_json: list[str] = Field(default_factory=list)
    block_reason: str | None = None

    def transition(self, new_state: TaskState, *, reason: str | None = None) -> "TaskRecord":
        allowed = {
            TaskState.CREATED: {TaskState.READY, TaskState.CANCELLED, TaskState.WAITING_FOR_DEPENDENCY},
            TaskState.READY: {
                TaskState.IN_PROGRESS,
                TaskState.WAITING_FOR_HUMAN,
                TaskState.WAITING_FOR_APPROVAL,
                TaskState.BLOCKED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.IN_PROGRESS: {
                TaskState.WAITING_FOR_HUMAN,
                TaskState.WAITING_FOR_APPROVAL,
                TaskState.BLOCKED,
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.WAITING_FOR_DEPENDENCY: {TaskState.READY, TaskState.CANCELLED},
            TaskState.WAITING_FOR_HUMAN: {TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED},
            TaskState.WAITING_FOR_APPROVAL: {TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED},
            TaskState.BLOCKED: {TaskState.READY, TaskState.FAILED, TaskState.CANCELLED},
            TaskState.COMPLETED: set(),
            TaskState.FAILED: set(),
            TaskState.CANCELLED: set(),
        }
        if new_state not in allowed[self.state]:
            raise StateTransitionError(f"task transition {self.state.value} -> {new_state.value} is not allowed")
        return self.model_copy(
            update={
                "state": new_state,
                "block_reason": reason if new_state is TaskState.BLOCKED else None,
                "updated_at": utc_now(),
            }
        )


class TaskEdgeRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("edge"))
    workflow_run_id: str
    from_task_id: str
    to_task_id: str
    edge_type: EdgeType = EdgeType.HARD
    is_hard_dependency: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class TaskAttemptRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("attempt"))
    task_id: str
    attempt_number: int
    state: AttemptState = AttemptState.QUEUED
    worker_mode: str = "remote"
    agent_definition_id: str
    workspace_id: str | None = None
    compiled_worker_config_json: JsonDict = Field(default_factory=dict)
    model_route_id: str | None = None
    lease_key: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def transition(self, new_state: AttemptState) -> "TaskAttemptRecord":
        allowed = {
            AttemptState.QUEUED: {AttemptState.DISPATCHING, AttemptState.ABORTED},
            AttemptState.DISPATCHING: {AttemptState.RUNNING, AttemptState.ERRORED, AttemptState.ORPHANED},
            AttemptState.RUNNING: {
                AttemptState.PAUSED,
                AttemptState.NEEDS_INPUT,
                AttemptState.SUCCEEDED,
                AttemptState.ERRORED,
                AttemptState.ORPHANED,
                AttemptState.ABORTED,
            },
            AttemptState.PAUSED: {AttemptState.RUNNING, AttemptState.ABORTED, AttemptState.ORPHANED},
            AttemptState.NEEDS_INPUT: {AttemptState.PAUSED, AttemptState.RUNNING, AttemptState.ABORTED},
            AttemptState.SUCCEEDED: set(),
            AttemptState.ERRORED: set(),
            AttemptState.ABORTED: set(),
            AttemptState.ORPHANED: set(),
        }
        if new_state not in allowed[self.state]:
            raise StateTransitionError(
                f"attempt transition {self.state.value} -> {new_state.value} is not allowed"
            )
        return self.model_copy(update={"state": new_state})


class ArtifactRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("artifact"))
    workflow_run_id: str
    task_id: str
    task_attempt_id: str
    produced_by_role: str
    artifact_type: str
    title: str
    summary: str
    status: ArtifactStatus = ArtifactStatus.DRAFT
    version: int = 1
    storage_uri: str
    checksum: str
    metadata_json: JsonDict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class DecisionRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("decision"))
    workflow_run_id: str
    task_id: str
    task_attempt_id: str
    title: str
    decision_text: str
    rationale: str
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)


class MemoryEntryRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("memory"))
    project_id: str
    scope_type: str
    scope_id: str
    memory_layer: MemoryLayer
    content: str
    metadata_json: JsonDict = Field(default_factory=dict)
    valid_from: datetime = Field(default_factory=utc_now)
    valid_to: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class HumanRequestRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("human"))
    workflow_run_id: str
    task_id: str
    task_attempt_id: str
    request_type: HumanRequestType
    question: str
    context_summary: str
    status: HumanRequestStatus = HumanRequestStatus.OPEN
    answer_text: str | None = None
    answered_by: str | None = None
    answered_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalRequestRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("approval"))
    workflow_run_id: str
    task_id: str
    task_attempt_id: str
    approval_type: str
    reason: str
    status: ApprovalStatus = ApprovalStatus.REQUESTED
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class EventRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("event"))
    workflow_run_id: str
    task_id: str | None = None
    task_attempt_id: str | None = None
    agent_id: str | None = None
    agent_role: str | None = None
    sandbox_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    route_reason: str | None = None
    event_type: str
    source: str
    severity: EventSeverity = EventSeverity.INFO
    sequence_no: int = 0
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ModelRouteRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("route"))
    workflow_run_id: str
    task_id: str
    task_attempt_id: str
    provider_name: str = "VertexAI"
    model_name: str
    route_reason: str
    fallback_from: str | None = None
    estimated_cost_class: str
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceRecord(BaseRecord):
    id: str = Field(default_factory=lambda: generate_id("workspace"))
    workflow_run_id: str
    task_attempt_id: str
    sandbox_id: str
    repo_ref: str
    branch_name: str
    worktree_path_or_uri: str
    status: str = "created"
    created_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None


class TypedMissResponse(BaseRecord):
    found: bool = False
    reason: MissingContextReason
    searched_sources: list[str] = Field(
        default_factory=lambda: ["workspace", "postgres", "pgvector", "artifact_store", "neo4j", "redis"]
    )
    next_action: str


class TaskReadiness(BaseRecord):
    task_id: str
    ready: bool
    reasons: list[str] = Field(default_factory=list)
    missing_artifacts: list[str] = Field(default_factory=list)


class WorkflowGraph(BaseRecord):
    workflow_run: WorkflowRunRecord
    tasks: list[TaskRecord]
    edges: list[TaskEdgeRecord]

    @model_validator(mode="after")
    def validate_edges(self) -> "WorkflowGraph":
        task_ids = {task.id for task in self.tasks}
        for edge in self.edges:
            if edge.from_task_id not in task_ids or edge.to_task_id not in task_ids:
                raise ValueError("graph edge references an unknown task")
        return self
