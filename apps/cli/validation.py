"""Repository validation helpers for the AutoWeave CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apps.cli.bootstrap import AGENT_ROLES, RUNTIME_FILES, ROUTING_FILE, WORKFLOW_FILE, expected_repository_files


@dataclass(frozen=True)
class ValidationResult:
    root: Path
    missing: tuple[Path, ...] = ()
    invalid: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.invalid


def validate_repository(root: Path) -> ValidationResult:
    checked: list[Path] = []
    missing: list[Path] = []
    invalid: list[str] = []

    for path in expected_repository_files(root):
        checked.append(path)
        if not path.exists():
            missing.append(path)

    if not missing:
        invalid.extend(_validate_yaml_contracts(root))

    return ValidationResult(root=root, missing=tuple(missing), invalid=tuple(invalid), checked=tuple(checked))


def _validate_yaml_contracts(root: Path) -> list[str]:
    issues: list[str] = []
    workflow = _load_yaml(root / WORKFLOW_FILE)
    templates = workflow.get("task_templates", [])
    if workflow.get("entrypoint") not in {template.get("key") for template in templates}:
        issues.append("workflow entrypoint is not defined in task_templates")

    required_workflow_keys = {"name", "version", "roles", "stages", "entrypoint", "task_templates", "completion_rules"}
    missing_workflow_keys = required_workflow_keys.difference(workflow.keys())
    if missing_workflow_keys:
        issues.append(f"workflow missing keys: {sorted(missing_workflow_keys)}")

    workflow_roles = set(workflow.get("roles", []))
    missing_roles = set(AGENT_ROLES).difference(workflow_roles)
    if missing_roles:
        issues.append(f"workflow missing agent roles: {sorted(missing_roles)}")

    task_keys = [template.get("key") for template in templates]
    if len(task_keys) != len(set(task_keys)):
        issues.append("workflow contains duplicate task template keys")
    template_keys = set(task_keys)
    for template in templates:
        dependencies = set(template.get("hard_dependencies", [])) | set(template.get("soft_dependencies", []))
        unknown_dependencies = dependencies.difference(template_keys)
        if unknown_dependencies:
            issues.append(
                f"workflow template {template.get('key')!r} has unknown dependencies: {sorted(unknown_dependencies)}"
            )

    runtime_issues = _require_yaml_keys(root / RUNTIME_FILES[0], root, {"default_concurrency"})
    storage_issues = _require_yaml_keys(root / RUNTIME_FILES[1], root, {"postgres_dsn_name", "redis_dsn_name", "neo4j_dsn_name"})
    vertex_issues = _require_yaml_keys(root / RUNTIME_FILES[2], root, {"provider_name", "profile_definitions", "fallback_order"})
    observability_issues = _require_yaml_keys(root / RUNTIME_FILES[3], root, {"event_retention_policy", "otlp_exporter_config"})
    issues.extend(runtime_issues)
    issues.extend(storage_issues)
    issues.extend(vertex_issues)
    issues.extend(observability_issues)

    for role in AGENT_ROLES:
        agent_path = root / "agents" / role / "autoweave.yaml"
        agent_data = _load_yaml(agent_path)
        required_agent_keys = {
            "name",
            "role",
            "description",
            "allowed_workflow_stages",
            "default_memory_scopes",
            "allowed_tool_groups",
            "sandbox_profile",
            "model_profile_hints",
            "approval_policy",
            "human_interaction_policy",
            "artifact_contracts",
            "route_priority",
        }
        missing_agent_keys = required_agent_keys.difference(agent_data.keys())
        if missing_agent_keys:
            issues.append(f"{agent_path.relative_to(root)} missing keys: {sorted(missing_agent_keys)}")
        if agent_data.get("role") != role:
            issues.append(f"{agent_path.relative_to(root)} role mismatch: expected {role!r}")

    return issues


def _require_yaml_keys(path: Path, root: Path, required_keys: set[str]) -> list[str]:
    data = _load_yaml(path)
    missing_keys = required_keys.difference(data.keys())
    if missing_keys:
        return [f"{path.relative_to(root)} missing keys: {sorted(missing_keys)}"]
    return []


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return loaded
