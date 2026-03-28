"""Canonical config schemas loaded from repository YAML files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaseConfigModel(BaseModel):
    """Shared strict model policy for configuration files."""

    model_config = ConfigDict(extra="forbid")


class ArtifactContractConfig(BaseConfigModel):
    artifact_type: str
    visibility: Literal["upstream", "shared", "restricted"] = "upstream"
    required_status: Literal["draft", "final"] = "final"
    required: bool = True


class AgentDefinitionConfig(BaseConfigModel):
    name: str
    role: str
    description: str
    allowed_workflow_stages: list[str]
    default_memory_scopes: list[str]
    allowed_tool_groups: list[str]
    sandbox_profile: str
    model_profile_hints: list[str] = Field(default_factory=list)
    approval_policy: str
    human_interaction_policy: str
    specialization: str | None = None
    primary_skills: list[str] = Field(default_factory=list)
    artifact_contracts: list[ArtifactContractConfig] = Field(default_factory=list)
    route_priority: int = 100


class TaskTemplateConfig(BaseConfigModel):
    key: str
    title: str
    assigned_role: str
    description_template: str
    hard_dependencies: list[str] = Field(default_factory=list)
    soft_dependencies: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    produced_artifacts: list[str] = Field(default_factory=list)
    approval_requirements: list[str] = Field(default_factory=list)
    memory_scopes: list[str] = Field(default_factory=list)
    route_hints: list[str] = Field(default_factory=list)


class WorkflowDefinitionConfig(BaseConfigModel):
    name: str
    version: str
    roles: list[str]
    stages: list[str]
    entrypoint: str
    policies: dict[str, object] = Field(default_factory=dict)
    task_templates: list[TaskTemplateConfig]
    completion_rules: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entrypoint(self) -> "WorkflowDefinitionConfig":
        known_keys = {template.key for template in self.task_templates}
        if self.entrypoint not in known_keys:
            raise ValueError(f"entrypoint {self.entrypoint!r} is not defined in task_templates")
        return self


class RuntimeConfig(BaseConfigModel):
    execution_backend: Literal["inline", "celery"] = "inline"
    celery_queue_names: list[str] = Field(default_factory=list)
    celery_result_expires_seconds: int = 3600
    celery_worker_pool: str = "auto"
    clarification_retry_limit: int = 2
    require_release_signoff: bool = True
    default_concurrency: int = 1
    retry_policy: dict[str, object] = Field(default_factory=dict)
    heartbeat_intervals: dict[str, int] = Field(default_factory=dict)
    cleanup_schedules: dict[str, str] = Field(default_factory=dict)
    compaction_thresholds: dict[str, int] = Field(default_factory=dict)


class StorageConfig(BaseConfigModel):
    postgres_dsn_name: str = "POSTGRES_URL"
    redis_dsn_name: str = "REDIS_URL"
    neo4j_dsn_name: str = "NEO4J_URL"
    artifact_store_config: dict[str, object] = Field(default_factory=dict)
    pgvector_index_config: dict[str, object] = Field(default_factory=dict)


class VertexProfileConfig(BaseConfigModel):
    name: str
    model: str
    timeout_seconds: int
    max_retries: int = 1
    budget_class: str = "balanced"


class VertexConfig(BaseConfigModel):
    provider_name: Literal["VertexAI"] = "VertexAI"
    profile_definitions: list[VertexProfileConfig]
    fallback_order: list[str] = Field(default_factory=list)
    timeout_policy: dict[str, object] = Field(default_factory=dict)
    retry_policy: dict[str, object] = Field(default_factory=dict)
    token_cost_budgets: dict[str, object] = Field(default_factory=dict)


class ObservabilityConfig(BaseConfigModel):
    event_retention_policy: dict[str, object] = Field(default_factory=dict)
    otlp_exporter_config: dict[str, object] = Field(default_factory=dict)
    metric_sinks: list[str] = Field(default_factory=list)
    redaction_rules: list[str] = Field(default_factory=list)
    replay_retention_windows: dict[str, object] = Field(default_factory=dict)
