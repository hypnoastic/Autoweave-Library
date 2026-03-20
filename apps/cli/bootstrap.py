"""Bootstrap helpers for the AutoWeave repository layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DOC_FILES = (
    Path("docs/autoweave_high_level_architecture.md"),
    Path("docs/autoweave_implementation_spec.md"),
    Path("docs/autoweave_diagrams_source.md"),
)

AGENT_ROLES = ("manager", "backend", "frontend", "reviewer")
AGENT_FILES = ("soul.md", "playbook.yaml", "autoweave.yaml")
RUNTIME_FILES = (
    Path("configs/runtime/runtime.yaml"),
    Path("configs/runtime/storage.yaml"),
    Path("configs/runtime/vertex.yaml"),
    Path("configs/runtime/observability.yaml"),
)
WORKFLOW_FILE = Path("configs/workflows/team.workflow.yaml")
ROUTING_FILE = Path("configs/routing/model_profiles.yaml")


@dataclass(frozen=True)
class BootstrapResult:
    created: tuple[Path, ...]


def repository_root(root: Path | None = None) -> Path:
    return Path.cwd() if root is None else root


def expected_repository_files(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = list(DOC_FILES) + [WORKFLOW_FILE, ROUTING_FILE, *RUNTIME_FILES]
    for role in AGENT_ROLES:
        role_dir = Path("agents") / role
        paths.extend(role_dir / filename for filename in AGENT_FILES)
        paths.append(role_dir / "skills" / "README.md")
    return tuple(root / relative for relative in paths)


def bootstrap_repository(root: Path) -> BootstrapResult:
    created: list[Path] = []

    for role in AGENT_ROLES:
        created.extend(_write_agent_bundle(root, role))

    created.extend(_write_text_file(root / WORKFLOW_FILE, render_workflow_yaml(), overwrite=False))
    created.extend(_write_text_file(root / ROUTING_FILE, render_model_profiles_yaml(), overwrite=False))
    for path, content in render_runtime_files().items():
        created.extend(_write_text_file(root / path, content, overwrite=False))

    return BootstrapResult(created=tuple(created))


def _write_agent_bundle(root: Path, role: str) -> list[Path]:
    role_dir = root / "agents" / role
    files = {
        role_dir / "soul.md": render_agent_soul(role),
        role_dir / "playbook.yaml": render_agent_playbook(role),
        role_dir / "autoweave.yaml": render_agent_autoweave(role),
        role_dir / "skills" / "README.md": render_agent_skills_readme(role),
    }
    created: list[Path] = []
    for path, content in files.items():
        created.extend(_write_text_file(path, content, overwrite=False))
    return created


def _write_text_file(path: Path, content: str, *, overwrite: bool) -> list[Path]:
    if path.exists() and not overwrite:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return [path]


def render_agent_soul(role: str) -> str:
    return (
        f"# {role.title()} Agent Soul\n\n"
        f"The {role} agent executes only the work assigned by AutoWeave.\n"
        "It relies on the orchestrator for canonical task state, dependencies, and approvals.\n"
    )


def render_agent_playbook(role: str) -> str:
    playbook: dict[str, Any] = {
        "version": "1.0",
        "role": role,
        "goals": [
            "follow orchestrator scope",
            "publish artifacts through AutoWeave services",
            "request human help when blocked",
        ],
        "workflow_notes": [
            "no raw database access",
            "no peer-to-peer workflow authority",
            "resume only through the current attempt",
        ],
    }
    return yaml.safe_dump(playbook, sort_keys=False)


def render_agent_autoweave(role: str) -> str:
    payload: dict[str, Any] = {
        "name": f"{role}-agent",
        "role": role,
        "description": f"AutoWeave sample {role} agent",
        "allowed_workflow_stages": ["planning", "implementation", "integration", "review"],
        "default_memory_scopes": ["project", "workflow_run", "task"],
        "allowed_tool_groups": ["context", "artifacts", "approvals", "workspace"],
        "sandbox_profile": "isolated-worktree",
        "model_profile_hints": ["balanced"],
        "approval_policy": "request-before-risky-action",
        "human_interaction_policy": "request-clarification-through-orchestrator",
        "artifact_contracts": [
            {
                "artifact_type": f"{role}_notes",
                "visibility": "upstream",
                "required_status": "final",
                "required": False,
            }
        ],
        "route_priority": 50 if role == "manager" else 100,
    }
    return yaml.safe_dump(payload, sort_keys=False)


def render_agent_skills_readme(role: str) -> str:
    return (
        f"# {role.title()} Skills\n\n"
        "This directory is reserved for local, role-specific skills or playbooks.\n"
    )


def render_workflow_yaml() -> str:
    workflow: dict[str, Any] = {
        "name": "team",
        "version": "1.0",
        "roles": ["manager", "backend", "frontend", "reviewer"],
        "stages": ["planning", "implementation", "integration", "review"],
        "entrypoint": "manager_plan",
        "policies": {
            "max_active_attempts": 4,
            "human_requests": "orchestrator_authoritative",
        },
        "task_templates": [
            {
                "key": "manager_plan",
                "title": "Manager plan",
                "assigned_role": "manager",
                "description_template": "Plan the implementation and split work across branches.",
                "hard_dependencies": [],
                "soft_dependencies": [],
                "required_artifacts": [],
                "produced_artifacts": ["workflow_plan"],
                "approval_requirements": [],
                "memory_scopes": ["project", "workflow_run"],
                "route_hints": ["planning"],
            },
            {
                "key": "backend_contract",
                "title": "Backend contract",
                "assigned_role": "backend",
                "description_template": "Define API and data contract for notifications settings.",
                "hard_dependencies": ["manager_plan"],
                "soft_dependencies": [],
                "required_artifacts": ["workflow_plan"],
                "produced_artifacts": ["backend_contract"],
                "approval_requirements": [],
                "memory_scopes": ["workflow_run", "task"],
                "route_hints": ["analysis"],
            },
            {
                "key": "backend_impl",
                "title": "Backend implementation",
                "assigned_role": "backend",
                "description_template": "Implement the backend API after the contract is finalized.",
                "hard_dependencies": ["backend_contract"],
                "soft_dependencies": [],
                "required_artifacts": ["backend_contract"],
                "produced_artifacts": ["backend_impl"],
                "approval_requirements": [],
                "memory_scopes": ["workflow_run", "task"],
                "route_hints": ["implementation"],
            },
            {
                "key": "frontend_ui",
                "title": "Frontend UI",
                "assigned_role": "frontend",
                "description_template": "Build the notifications settings page UI.",
                "hard_dependencies": ["manager_plan"],
                "soft_dependencies": [],
                "required_artifacts": ["workflow_plan"],
                "produced_artifacts": ["frontend_ui"],
                "approval_requirements": [],
                "memory_scopes": ["workflow_run", "task"],
                "route_hints": ["implementation"],
            },
            {
                "key": "integration",
                "title": "Integration",
                "assigned_role": "backend",
                "description_template": "Integrate backend and frontend work and resolve blockers.",
                "hard_dependencies": ["backend_impl", "frontend_ui"],
                "soft_dependencies": [],
                "required_artifacts": ["backend_impl", "frontend_ui"],
                "produced_artifacts": ["integration_report"],
                "approval_requirements": [],
                "memory_scopes": ["workflow_run", "task"],
                "route_hints": ["integration"],
            },
            {
                "key": "review",
                "title": "Review",
                "assigned_role": "reviewer",
                "description_template": "Review the integrated changes and approve or reject.",
                "hard_dependencies": ["integration"],
                "soft_dependencies": [],
                "required_artifacts": ["integration_report"],
                "produced_artifacts": ["review_notes"],
                "approval_requirements": ["human_review"],
                "memory_scopes": ["workflow_run", "task"],
                "route_hints": ["review"],
            },
        ],
        "completion_rules": {
            "required_final_states": ["integration", "review"],
            "artifact_visibility": "dependency_scoped",
        },
    }
    return yaml.safe_dump(workflow, sort_keys=False)


def render_model_profiles_yaml() -> str:
    profiles: dict[str, Any] = {
        "profiles": [
            {"name": "balanced", "model": "gemini-2.5-pro", "budget_class": "balanced"},
            {"name": "planner", "model": "gemini-2.5-pro", "budget_class": "high"},
            {"name": "fast", "model": "gemini-2.5-flash", "budget_class": "low"},
        ]
    }
    return yaml.safe_dump(profiles, sort_keys=False)


def render_runtime_files() -> dict[Path, str]:
    return {
        Path("configs/runtime/runtime.yaml"): yaml.safe_dump(
            {

                "default_concurrency": 4,
                "retry_policy": {"max_attempts": 3, "backoff_seconds": 15},
                "heartbeat_intervals": {"worker": 15, "lease": 60},
                "cleanup_schedules": {"workspace": "0 * * * *"},
                "compaction_thresholds": {"context_tokens": 12000},
            },
            sort_keys=False,
        ),
        Path("configs/runtime/storage.yaml"): yaml.safe_dump(
            {
                "postgres_dsn_name": "POSTGRES_URL",
                "redis_dsn_name": "REDIS_URL",
                "neo4j_dsn_name": "NEO4J_URL",
                "artifact_store_config": {"kind": "local-fs", "base_path": "./artifacts"},
                "pgvector_index_config": {"dimension": 1536},
            },
            sort_keys=False,
        ),
        Path("configs/runtime/vertex.yaml"): yaml.safe_dump(
            {
                "provider_name": "VertexAI",
                "profile_definitions": [
                    {"name": "planner", "model": "gemini-2.5-pro", "timeout_seconds": 1800, "max_retries": 2},
                    {"name": "balanced", "model": "gemini-2.5-pro", "timeout_seconds": 1800, "max_retries": 2},
                    {"name": "fast", "model": "gemini-2.5-flash", "timeout_seconds": 900, "max_retries": 1},
                ],
                "fallback_order": ["fast", "balanced", "planner"],
                "timeout_policy": {"dispatch_seconds": 10},
                "retry_policy": {"escalate_after_failures": 2},
                "token_cost_budgets": {"planner": 120000, "balanced": 80000, "fast": 20000},
            },
            sort_keys=False,
        ),
        Path("configs/runtime/observability.yaml"): yaml.safe_dump(
            {
                "event_retention_policy": {"days": 30},
                "otlp_exporter_config": {"endpoint": "http://localhost:4317"},
                "metric_sinks": ["stdout"],
                "redaction_rules": ["service_account", "api_key", "password"],
                "replay_retention_windows": {"failed_runs_days": 14},
            },
            sort_keys=False,
        ),
    }
