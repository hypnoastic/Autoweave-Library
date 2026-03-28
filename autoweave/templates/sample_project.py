"""Packaged sample-project assets used by bootstrap and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

AGENT_ROLES = ("manager", "backend", "frontend", "reviewer")
AGENT_FILES = ("soul.md", "playbook.yaml", "autoweave.yaml")
AGENT_SKILL_FILES: dict[str, tuple[Path, ...]] = {
    "manager": (
        Path("skills/README.md"),
        Path("skills/workflow_decomposition.md"),
        Path("skills/stakeholder_alignment.md"),
    ),
    "backend": (
        Path("skills/README.md"),
        Path("skills/api_contracts.md"),
        Path("skills/data_integrity.md"),
    ),
    "frontend": (
        Path("skills/README.md"),
        Path("skills/ui_states.md"),
        Path("skills/accessibility_checks.md"),
    ),
    "reviewer": (
        Path("skills/README.md"),
        Path("skills/qa_validation.md"),
        Path("skills/release_readiness.md"),
    ),
}
RUNTIME_FILES = (
    Path("configs/runtime/runtime.yaml"),
    Path("configs/runtime/storage.yaml"),
    Path("configs/runtime/vertex.yaml"),
    Path("configs/runtime/observability.yaml"),
)
WORKFLOW_FILE = Path("configs/workflows/team.workflow.yaml")
ROUTING_FILE = Path("configs/routing/model_profiles.yaml")


def render_agent_soul(role: str) -> str:
    role_souls = {
        "manager": (
            "The manager agent turns a user brief into a dependency-aware DAG, "
            "surfaces missing details early, and coordinates downstream work through AutoWeave."
        ),
        "backend": (
            "The backend agent owns contracts, data shapes, and integration seams before implementation begins."
        ),
        "frontend": (
            "The frontend agent delivers user-facing flows, state handling, and accessible interaction states."
        ),
        "reviewer": (
            "The reviewer agent acts as tester and release gate, checking quality, regressions, and residual risk."
        ),
    }
    return (
        f"# {role.title()} Agent Soul\n\n"
        f"{role_souls.get(role, 'This agent executes only the work assigned by AutoWeave.')}\n\n"
        "It relies on the orchestrator for canonical task state, dependencies, approvals, and artifact visibility.\n"
    )


def render_agent_playbook(role: str) -> str:
    role_playbooks: dict[str, dict[str, Any]] = {
        "manager": {
            "focus": [
                "convert the user request into a concrete DAG task list",
                "call out missing scope before downstream work starts",
                "keep the plan readable for operators and reviewers",
            ],
            "artifact_types": ["workflow_plan", "scope_notes", "open_questions"],
        },
        "backend": {
            "focus": [
                "define contracts before code",
                "protect data integrity and API compatibility",
                "produce implementation notes and handoff details",
            ],
            "artifact_types": ["backend_contract", "backend_impl", "migration_notes"],
        },
        "frontend": {
            "focus": [
                "translate product intent into concrete screens and states",
                "cover loading, empty, and error states",
                "document accessibility and interaction decisions",
            ],
            "artifact_types": ["frontend_ui", "state_matrix", "a11y_notes"],
        },
        "reviewer": {
            "focus": [
                "verify behavior against acceptance criteria",
                "look for edge cases, regressions, and release blockers",
                "summarize test status, a release verdict, and concrete rework notes clearly",
            ],
            "artifact_types": ["qa_report", "review_notes", "release_risk"],
        },
    }
    playbook: dict[str, Any] = {
        "version": "1.0",
        "role": role,
        "goals": role_playbooks.get(
            role,
            {
                "focus": ["follow orchestrator scope", "publish artifacts through AutoWeave services"],
                "artifact_types": ["role_notes"],
            },
        )["focus"],
        "artifact_types": role_playbooks.get(role, {"artifact_types": ["role_notes"]})["artifact_types"],
        "workflow_notes": [
            "no raw database access",
            "no peer-to-peer workflow authority",
            "resume only through the current attempt",
            "escalate missing requirements instead of guessing scope",
        ],
    }
    return yaml.safe_dump(playbook, sort_keys=False)


def render_agent_autoweave(role: str) -> str:
    role_metadata: dict[str, dict[str, Any]] = {
        "manager": {
            "allowed_tool_groups": ["context", "artifacts", "approvals", "workflow"],
            "model_profile_hints": ["planner"],
            "specialization": "workflow-decomposition",
            "primary_skills": ["workflow_decomposition", "stakeholder_alignment"],
        },
        "backend": {
            "allowed_tool_groups": ["context", "artifacts", "workspace", "terminal"],
            "model_profile_hints": ["balanced"],
            "specialization": "api-and-data-contracts",
            "primary_skills": ["api_contracts", "data_integrity"],
        },
        "frontend": {
            "allowed_tool_groups": ["context", "artifacts", "workspace", "terminal"],
            "model_profile_hints": ["fast", "balanced"],
            "specialization": "ui-delivery",
            "primary_skills": ["ui_states", "accessibility_checks"],
        },
        "reviewer": {
            "allowed_tool_groups": ["context", "artifacts", "workspace", "approvals"],
            "model_profile_hints": ["balanced"],
            "specialization": "quality-and-release",
            "primary_skills": ["qa_validation", "release_readiness"],
        },
    }
    metadata = role_metadata.get(
        role,
        {
            "allowed_tool_groups": ["context", "artifacts", "workspace"],
            "model_profile_hints": ["balanced"],
            "specialization": "general",
            "primary_skills": ["role_notes"],
        },
    )
    payload: dict[str, Any] = {
        "name": f"{role}-agent",
        "role": role,
        "description": f"AutoWeave sample {role} agent focused on {metadata['specialization'].replace('-', ' ')}.",
        "allowed_workflow_stages": ["planning", "implementation", "integration", "review"],
        "default_memory_scopes": ["project", "workflow_run", "task"],
        "allowed_tool_groups": metadata["allowed_tool_groups"],
        "sandbox_profile": "isolated-worktree",
        "model_profile_hints": metadata["model_profile_hints"],
        "approval_policy": "request-before-risky-action",
        "human_interaction_policy": "request-clarification-through-orchestrator",
        "specialization": metadata["specialization"],
        "primary_skills": metadata["primary_skills"],
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
    skills = {
        "manager": ["workflow_decomposition.md", "stakeholder_alignment.md"],
        "backend": ["api_contracts.md", "data_integrity.md"],
        "frontend": ["ui_states.md", "accessibility_checks.md"],
        "reviewer": ["qa_validation.md", "release_readiness.md"],
    }.get(role, ["role_notes.md"])
    skill_list = "\n".join(f"- `{skill}`" for skill in skills)
    return (
        f"# {role.title()} Skills\n\n"
        "Use the role-specific markdown files below as the operating checklist for this agent.\n\n"
        f"{skill_list}\n"
    )


def render_agent_skill_markdown(role: str, filename: str) -> str:
    if role == "manager" and filename == "workflow_decomposition.md":
        return (
            "# Workflow Decomposition\n\n"
            "Use when turning a user request into a DAG.\n\n"
            "## When to use\n"
            "- A brief arrives and the work needs to be split into independent branches.\n"
            "- The request is underspecified and needs clarification before execution.\n\n"
            "## Do\n"
            "- Restate the outcome in concrete terms.\n"
            "- Identify hard dependencies, parallel branches, and review gates.\n"
            "- Capture open questions before dispatching tasks.\n\n"
            "## Output\n"
            "- A task graph summary.\n"
            "- A list of blocked assumptions.\n"
            "- A handoff note for downstream agents.\n"
        )
    if role == "manager" and filename == "stakeholder_alignment.md":
        return (
            "# Stakeholder Alignment\n\n"
            "Use when scope, acceptance, or sequencing is unclear.\n\n"
            "## Do\n"
            "- Ask for the missing detail instead of inventing scope.\n"
            "- Translate vague language into explicit delivery criteria.\n"
            "- Record decisions in the workflow plan artifact.\n"
        )
    if role == "backend" and filename == "api_contracts.md":
        return (
            "# API Contracts\n\n"
            "Use when defining routes, payloads, and integration boundaries.\n\n"
            "## Do\n"
            "- Specify request and response shapes.\n"
            "- Note validation, authorization, and error states.\n"
            "- List downstream dependencies and contract tests.\n"
        )
    if role == "backend" and filename == "data_integrity.md":
        return (
            "# Data Integrity\n\n"
            "Use when the work touches persistence, migrations, or domain invariants.\n\n"
            "## Do\n"
            "- Protect canonical data shapes.\n"
            "- Document migration order and rollback considerations.\n"
            "- Call out idempotency and consistency checks.\n"
        )
    if role == "frontend" and filename == "ui_states.md":
        return (
            "# UI States\n\n"
            "Use when designing or implementing user-facing screens.\n\n"
            "## Do\n"
            "- Cover loading, empty, success, and failure states.\n"
            "- Keep responsive behavior explicit.\n"
            "- Map UI actions to backend dependencies.\n"
        )
    if role == "frontend" and filename == "accessibility_checks.md":
        return (
            "# Accessibility Checks\n\n"
            "Use before finishing a UI branch.\n\n"
            "## Do\n"
            "- Check keyboard flow and focus order.\n"
            "- Confirm labels, contrast, and error messaging.\n"
            "- Note any known accessibility tradeoffs.\n"
        )
    if role == "reviewer" and filename == "qa_validation.md":
        return (
            "# QA Validation\n\n"
            "Use when checking whether the delivered work is ready to merge or ship.\n\n"
            "## Do\n"
            "- Verify the acceptance criteria one by one.\n"
            "- Look for regressions, stale assumptions, and missing tests.\n"
            "- Record the exact commands, previews, or smoke checks you ran and whether they passed.\n"
            "- Record what is still blocked.\n"
            "- Start the final verdict with `REVIEW_DECISION: APPROVE` or `REVIEW_DECISION: REVISE`.\n"
        )
    if role == "reviewer" and filename == "release_readiness.md":
        return (
            "# Release Readiness\n\n"
            "Use when deciding whether the branch is safe to hand off.\n\n"
            "## Do\n"
            "- Confirm artifacts are final and traceable.\n"
            "- Summarize residual risk and unresolved questions.\n"
            "- Only approve when you can cite concrete runnable validation evidence.\n"
            "- If revision is needed, provide detailed backend, frontend, and integration fixes in one pass.\n"
            "- Assume the workflow will rework once from your notes and will not request a second review pass.\n"
        )
    return (
        f"# {role.title()} Skill\n\n"
        "Use this file as the role-specific delivery checklist.\n"
    )


def render_agent_skill_files(role: str) -> dict[Path, str]:
    files = {
        Path("skills/README.md"): render_agent_skills_readme(role),
    }
    for skill_file in AGENT_SKILL_FILES.get(role, (Path("skills/role_notes.md"),)):
        if skill_file.name == "README.md":
            continue
        files[skill_file] = render_agent_skill_markdown(role, skill_file.name)
    return files


def render_project_files() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for role in AGENT_ROLES:
        role_dir = Path("agents") / role
        files[role_dir / "soul.md"] = render_agent_soul(role)
        files[role_dir / "playbook.yaml"] = render_agent_playbook(role)
        files[role_dir / "autoweave.yaml"] = render_agent_autoweave(role)
        for relative_path, content in render_agent_skill_files(role).items():
            files[role_dir / relative_path] = content
    files[WORKFLOW_FILE] = render_workflow_yaml()
    files[ROUTING_FILE] = render_model_profiles_yaml()
    files.update(render_runtime_files())
    return files


def render_project_file(relative_path: str | Path) -> str | None:
    normalized = Path(relative_path)
    candidates = [normalized]
    parts = normalized.parts
    for marker in ("agents", "configs"):
        if marker in parts:
            candidates.append(Path(*parts[parts.index(marker) :]))
    rendered_files = render_project_files()
    for candidate in candidates:
        if candidate in rendered_files:
            return rendered_files[candidate]
    return None


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
                "description_template": "Turn the brief into a DAG, split work across branches, and surface missing details.",
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
                "description_template": "Define the API, data contract, and integration boundaries for the feature.",
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
                "description_template": "Implement the backend after the contract is finalized and integration points are clear.",
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
                "description_template": "Build the user-facing flow with responsive, accessible states.",
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
                "description_template": "Integrate backend and frontend work, then resolve contract or runtime blockers.",
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
                "description_template": "Validate the integrated delivery, run quality checks, and approve or reject.",
                "hard_dependencies": ["integration"],
                "soft_dependencies": [],
                "required_artifacts": ["integration_report"],
                "produced_artifacts": ["review_notes"],
                "approval_requirements": [],
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
            {"name": "balanced", "model": "gemini-3-flash-preview", "budget_class": "balanced"},
            {"name": "planner", "model": "gemini-3.1-pro-preview", "budget_class": "high"},
            {"name": "fast", "model": "gemini-3-flash-preview", "budget_class": "low"},
            {"name": "legacy_balanced", "model": "gemini-2.5-pro", "budget_class": "balanced"},
            {"name": "legacy_planner", "model": "gemini-2.5-pro", "budget_class": "high"},
            {"name": "legacy_fast", "model": "gemini-2.5-flash", "budget_class": "low"},
        ]
    }
    return yaml.safe_dump(profiles, sort_keys=False)


def render_runtime_files() -> dict[Path, str]:
    return {
        Path("configs/runtime/runtime.yaml"): yaml.safe_dump(
            {
                "execution_backend": "celery",
                "celery_queue_names": ["dispatch"],
                "celery_result_expires_seconds": 3600,
                "celery_worker_pool": "auto",
                "clarification_retry_limit": 2,
                "require_release_signoff": True,
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
                    {"name": "planner", "model": "gemini-3.1-pro-preview", "timeout_seconds": 1800, "max_retries": 2},
                    {"name": "balanced", "model": "gemini-3-flash-preview", "timeout_seconds": 1200, "max_retries": 2},
                    {"name": "fast", "model": "gemini-3-flash-preview", "timeout_seconds": 900, "max_retries": 1},
                    {"name": "legacy_planner", "model": "gemini-2.5-pro", "timeout_seconds": 1800, "max_retries": 2},
                    {"name": "legacy_balanced", "model": "gemini-2.5-pro", "timeout_seconds": 1800, "max_retries": 2},
                    {"name": "legacy_fast", "model": "gemini-2.5-flash", "timeout_seconds": 900, "max_retries": 1},
                ],
                "fallback_order": ["fast", "balanced", "planner", "legacy_planner", "legacy_balanced", "legacy_fast"],
                "timeout_policy": {"dispatch_seconds": 10},
                "retry_policy": {"escalate_after_failures": 2},
                "token_cost_budgets": {
                    "planner": 120000,
                    "balanced": 80000,
                    "fast": 20000,
                    "legacy_planner": 120000,
                    "legacy_balanced": 80000,
                    "legacy_fast": 20000,
                },
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
