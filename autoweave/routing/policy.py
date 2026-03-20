"""Vertex AI routing policy and audit helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from autoweave.config_models import VertexConfig, VertexProfileConfig
from autoweave.models import ModelRouteRecord, TaskAttemptRecord, TaskRecord

_ROLE_BASELINE = {
    "manager": 2,
    "reviewer": 2,
    "integration": 2,
    "backend": 1,
    "frontend": 1,
}

_HINT_BASELINE = {
    "critical": 2,
    "escalate": 2,
    "high_reasoning": 2,
    "planning": 2,
    "review": 2,
    "integration": 2,
    "analysis": 1,
    "implementation": 1,
    "complex": 1,
    "boilerplate": 0,
}

_BUDGET_RANK = {"low": 0, "balanced": 1, "high": 2, "premium": 3}


@dataclass(slots=True)
class RouteFailureLedger:
    """Track route failures per attempt so escalation is deterministic."""

    failures_by_attempt: dict[str, int] = field(default_factory=dict)
    last_route_by_attempt: dict[str, str] = field(default_factory=dict)

    def record_failure(self, attempt_id: str) -> int:
        count = self.failures_by_attempt.get(attempt_id, 0) + 1
        self.failures_by_attempt[attempt_id] = count
        return count

    def failure_count(self, attempt_id: str) -> int:
        return self.failures_by_attempt.get(attempt_id, 0)

    def record_route(self, attempt_id: str, model_name: str) -> None:
        self.last_route_by_attempt[attempt_id] = model_name

    def last_route(self, attempt_id: str) -> str | None:
        return self.last_route_by_attempt.get(attempt_id)


@dataclass(slots=True)
class RouteAuditLog:
    """In-memory route audit log used by the runtime workstream."""

    records: list[ModelRouteRecord] = field(default_factory=list)

    def record(self, route: ModelRouteRecord) -> ModelRouteRecord:
        self.records.append(route)
        return route


@dataclass(slots=True)
class VertexModelRouter:
    """Select and record Vertex AI routes for a task attempt."""

    vertex_config: VertexConfig
    ledger: RouteFailureLedger = field(default_factory=RouteFailureLedger)
    audit_log: RouteAuditLog = field(default_factory=RouteAuditLog)

    def select_route(
        self,
        *,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        hints: list[str],
    ) -> ModelRouteRecord:
        profiles = self._ordered_profiles()
        index_floor = self._baseline_index(task.assigned_role, hints, len(profiles))
        failure_count = self.ledger.failure_count(attempt.id)
        selected_index = min(index_floor + failure_count, len(profiles) - 1)
        selected_profile = profiles[selected_index]
        previous_model = self.ledger.last_route(attempt.id)
        route_reason = self._build_route_reason(
            task=task,
            hints=hints,
            selected_profile=selected_profile,
            index_floor=index_floor,
            failure_count=failure_count,
        )
        route = ModelRouteRecord(
            workflow_run_id=task.workflow_run_id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            provider_name=self.vertex_config.provider_name,
            model_name=selected_profile.model,
            route_reason=route_reason,
            fallback_from=previous_model if previous_model != selected_profile.model else None,
            estimated_cost_class=selected_profile.budget_class,
        )
        self.ledger.record_route(attempt.id, route.model_name)
        self.audit_log.record(route)
        return route

    def record_failure(self, attempt_id: str) -> int:
        return self.ledger.record_failure(attempt_id)

    def _ordered_profiles(self) -> list[VertexProfileConfig]:
        by_name = {profile.name: profile for profile in self.vertex_config.profile_definitions}
        if self.vertex_config.fallback_order:
            ordered = [by_name[name] for name in self.vertex_config.fallback_order if name in by_name]
            if ordered:
                return ordered
        return list(self.vertex_config.profile_definitions)

    def _baseline_index(self, role: str, hints: list[str], profile_count: int) -> int:
        baseline = _ROLE_BASELINE.get(role, 0)
        for hint in hints:
            baseline = max(baseline, _HINT_BASELINE.get(hint, baseline))
            if hint in {profile.name for profile in self.vertex_config.profile_definitions}:
                ordered = self._ordered_profiles()
                return min(
                    next(i for i, profile in enumerate(ordered) if profile.name == hint),
                    profile_count - 1,
                )
        return min(baseline, profile_count - 1)

    def _build_route_reason(
        self,
        *,
        task: TaskRecord,
        hints: list[str],
        selected_profile: VertexProfileConfig,
        index_floor: int,
        failure_count: int,
    ) -> str:
        hint_text = ",".join(hints) if hints else "none"
        return (
            f"role={task.assigned_role}; "
            f"hints={hint_text}; "
            f"baseline_index={index_floor}; "
            f"failure_count={failure_count}; "
            f"profile={selected_profile.name}; "
            f"model={selected_profile.model}"
        )
