"""Canonical-to-OpenHands config compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autoweave.config_models import RuntimeConfig, VertexConfig
from autoweave.models import ModelRouteRecord, TaskAttemptRecord, TaskRecord
from autoweave.types import JsonDict
from autoweave.workers.runtime import WorkspacePolicy, build_vertex_worker_env


class OpenHandsWorkerConfig(BaseModel):
    """Worker-facing launch config that the runtime adapter hands to OpenHands."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str
    model_name: str
    interactive_login: bool = False
    env: dict[str, str] = Field(default_factory=dict)
    workspace_path: str
    task_id: str
    task_attempt_id: str
    task_role: str
    task_title: str
    task_description: str
    route_reason: str
    permission_mode: str = "workspace-write"
    tool_groups: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    runtime_policy: JsonDict = Field(default_factory=dict)


@dataclass(slots=True)
class OpenHandsConfigCompiler:
    """Compile AutoWeave canonical task state into a worker launch config."""

    vertex_config: VertexConfig
    service_account_file: str | Path
    workspace_policy: WorkspacePolicy = field(default_factory=WorkspacePolicy)
    default_tool_groups: tuple[str, ...] = ("context", "artifacts", "approvals")

    def compile_attempt_config(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        route: ModelRouteRecord,
        runtime_policy: JsonDict,
    ) -> JsonDict:
        env = build_vertex_worker_env(
            project=str(runtime_policy.get("vertex_project", "")),
            location=str(runtime_policy.get("vertex_location", "")),
            service_account_file=self.service_account_file,
        )
        workspace = self.workspace_policy.workspace_path_for_attempt(attempt.id)
        compiled = OpenHandsWorkerConfig(
            provider_name=route.provider_name,
            model_name=route.model_name,
            interactive_login=False,
            env=env,
            workspace_path=str(workspace),
            task_id=task.id,
            task_attempt_id=attempt.id,
            task_role=task.assigned_role,
            task_title=task.title,
            task_description=task.description,
            route_reason=route.route_reason,
            permission_mode=str(runtime_policy.get("permission_mode", "workspace-write")),
            tool_groups=list(runtime_policy.get("tool_groups", self.default_tool_groups)),
            mcp_servers=list(runtime_policy.get("mcp_servers", [])),
            runtime_policy=runtime_policy,
        )
        return compiled.model_dump()
