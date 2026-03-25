"""Canonical config loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml

from autoweave.config_models import (
    AgentDefinitionConfig,
    ObservabilityConfig,
    RuntimeConfig,
    StorageConfig,
    VertexConfig,
    WorkflowDefinitionConfig,
)
from autoweave.templates import sample_project

TConfig = TypeVar("TConfig")


def load_yaml_model(path: str | Path, model_cls: type[TConfig]) -> TConfig:
    """Load a YAML file and validate it against a pydantic model."""

    raw_path = Path(path)
    if raw_path.exists():
        payload = yaml.safe_load(raw_path.read_text()) or {}
    else:
        rendered = sample_project.render_project_file(raw_path)
        if rendered is None:
            raise FileNotFoundError(raw_path)
        payload = yaml.safe_load(rendered) or {}
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)  # type: ignore[no-any-return]
    return model_cls(**payload)  # type: ignore[call-arg, no-any-return]


class CanonicalConfigLoader:
    """Load canonical AutoWeave config models from YAML files."""

    def __init__(self, root_dir: str | Path = ".") -> None:
        self.root_dir = Path(root_dir)

    def load_runtime_config(self, relative_path: str | Path) -> RuntimeConfig:
        return load_yaml_model(self.root_dir / relative_path, RuntimeConfig)

    def load_storage_config(self, relative_path: str | Path) -> StorageConfig:
        return load_yaml_model(self.root_dir / relative_path, StorageConfig)

    def load_vertex_config(self, relative_path: str | Path) -> VertexConfig:
        return load_yaml_model(self.root_dir / relative_path, VertexConfig)

    def load_observability_config(self, relative_path: str | Path) -> ObservabilityConfig:
        return load_yaml_model(self.root_dir / relative_path, ObservabilityConfig)

    def load_workflow_definition(self, relative_path: str | Path) -> WorkflowDefinitionConfig:
        return load_yaml_model(self.root_dir / relative_path, WorkflowDefinitionConfig)

    def load_agent_definition(self, relative_path: str | Path) -> AgentDefinitionConfig:
        return load_yaml_model(self.root_dir / relative_path, AgentDefinitionConfig)
