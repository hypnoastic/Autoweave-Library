"""Workflow parsing, validation, and graph-building helpers."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import json
from typing import Any, Mapping

import yaml

from autoweave.config_models import TaskTemplateConfig, WorkflowDefinitionConfig
from autoweave.models import EdgeType, TaskEdgeRecord, TaskRecord, WorkflowGraph, WorkflowRunRecord
from autoweave.types import JsonDict


@dataclass(slots=True, frozen=True)
class WorkflowTopology:
    """In-memory dependency view of a workflow definition."""

    definition: WorkflowDefinitionConfig
    hard_dependencies: dict[str, tuple[str, ...]]
    soft_dependencies: dict[str, tuple[str, ...]]
    topological_order: tuple[str, ...]

    def hard_predecessors(self, task_key: str) -> tuple[str, ...]:
        return self.hard_dependencies.get(task_key, ())

    def soft_predecessors(self, task_key: str) -> tuple[str, ...]:
        return self.soft_dependencies.get(task_key, ())


def parse_workflow_definition(source: str | Mapping[str, Any]) -> WorkflowDefinitionConfig:
    """Parse a workflow definition from YAML text or a mapping."""

    raw: Any
    if isinstance(source, str):
        raw = yaml.safe_load(source)
    else:
        raw = dict(source)
    if not isinstance(raw, dict):
        raise ValueError("workflow definition must parse to a mapping")
    return WorkflowDefinitionConfig.model_validate(raw)


def build_workflow_topology(definition: WorkflowDefinitionConfig) -> WorkflowTopology:
    """Validate dependency references and compute a topological order."""

    task_templates = {template.key: template for template in definition.task_templates}
    _validate_dependency_references(task_templates)
    _validate_acyclic(task_templates)

    hard_dependencies = {
        template.key: tuple(template.hard_dependencies)
        for template in definition.task_templates
    }
    soft_dependencies = {
        template.key: tuple(template.soft_dependencies)
        for template in definition.task_templates
    }
    topological_order = tuple(_topological_order(task_templates))
    return WorkflowTopology(
        definition=definition,
        hard_dependencies=hard_dependencies,
        soft_dependencies=soft_dependencies,
        topological_order=topological_order,
    )


def build_workflow_graph(
    definition: WorkflowDefinitionConfig,
    *,
    project_id: str,
    team_id: str,
    workflow_definition_id: str | None = None,
    workflow_run_id: str | None = None,
    root_input_json: JsonDict | None = None,
    graph_revision: int = 1,
) -> WorkflowGraph:
    """Instantiate a canonical workflow graph from a validated definition."""

    topology = build_workflow_topology(definition)
    workflow_definition_id = workflow_definition_id or f"{definition.name}:{definition.version}"
    workflow_run = WorkflowRunRecord(
        id=workflow_run_id or workflow_definition_id.replace(":", "_") + "_run",
        project_id=project_id,
        team_id=team_id,
        workflow_definition_id=workflow_definition_id,
        graph_revision=graph_revision,
        root_input_json=root_input_json or {},
    )

    tasks: list[TaskRecord] = []
    tasks_by_key: dict[str, TaskRecord] = {}
    root_payload = dict(root_input_json or {})
    for template in definition.task_templates:
        task = TaskRecord(
            workflow_run_id=workflow_run.id,
            task_key=template.key,
            title=template.title,
            description=_render_template(template.description_template, root_payload),
            assigned_role=template.assigned_role,
            input_json=dict(root_payload) if template.key == definition.entrypoint and root_payload else {},
            required_artifact_types_json=list(template.required_artifacts),
            produced_artifact_types_json=list(template.produced_artifacts),
        )
        tasks.append(task)
        tasks_by_key[template.key] = task

    edges: list[TaskEdgeRecord] = []
    for template in definition.task_templates:
        task = tasks_by_key[template.key]
        for dependency_key in template.hard_dependencies:
            dependency = tasks_by_key[dependency_key]
            edges.append(
                TaskEdgeRecord(
                    workflow_run_id=workflow_run.id,
                    from_task_id=dependency.id,
                    to_task_id=task.id,
                    edge_type=EdgeType.HARD,
                    is_hard_dependency=True,
                )
            )
        for dependency_key in template.soft_dependencies:
            dependency = tasks_by_key[dependency_key]
            edges.append(
                TaskEdgeRecord(
                    workflow_run_id=workflow_run.id,
                    from_task_id=dependency.id,
                    to_task_id=task.id,
                    edge_type=EdgeType.SOFT,
                    is_hard_dependency=False,
                )
            )

    # The topology is intentionally built and validated even though the graph object
    # is the final return value. This ensures compile-time cycle detection happens
    # before any runtime state is created.
    _ = topology
    return WorkflowGraph(workflow_run=workflow_run, tasks=tasks, edges=edges)


def example_notifications_workflow_definition() -> WorkflowDefinitionConfig:
    """Return the example workflow from the architecture docs."""

    return WorkflowDefinitionConfig.model_validate(
        {
            "name": "notifications_settings",
            "version": "1.0",
            "roles": ["manager", "backend", "frontend", "reviewer"],
            "stages": ["planning", "implementation", "integration", "review"],
            "entrypoint": "manager_plan",
            "policies": {"parallelism": "dependency-driven"},
            "task_templates": [
                {
                    "key": "manager_plan",
                    "title": "Manager plan",
                    "assigned_role": "manager",
                    "description_template": "Plan the notifications settings implementation.",
                    "hard_dependencies": [],
                    "soft_dependencies": [],
                    "required_artifacts": [],
                    "produced_artifacts": ["plan"],
                    "approval_requirements": [],
                    "memory_scopes": ["project"],
                    "route_hints": ["planner"],
                },
                {
                    "key": "backend_contract",
                    "title": "Backend contract",
                    "assigned_role": "backend",
                    "description_template": "Define backend API contract.",
                    "hard_dependencies": ["manager_plan"],
                    "soft_dependencies": [],
                    "required_artifacts": ["plan"],
                    "produced_artifacts": ["api_contract"],
                    "approval_requirements": [],
                    "memory_scopes": ["project"],
                    "route_hints": ["coding"],
                },
                {
                    "key": "backend_impl",
                    "title": "Backend implementation",
                    "assigned_role": "backend",
                    "description_template": "Implement backend API support.",
                    "hard_dependencies": ["backend_contract"],
                    "soft_dependencies": [],
                    "required_artifacts": ["api_contract"],
                    "produced_artifacts": ["backend_impl"],
                    "approval_requirements": [],
                    "memory_scopes": ["project"],
                    "route_hints": ["coding"],
                },
                {
                    "key": "frontend_ui",
                    "title": "Frontend UI",
                    "assigned_role": "frontend",
                    "description_template": "Build the notifications settings page.",
                    "hard_dependencies": ["manager_plan"],
                    "soft_dependencies": [],
                    "required_artifacts": ["plan"],
                    "produced_artifacts": ["frontend_ui"],
                    "approval_requirements": [],
                    "memory_scopes": ["project"],
                    "route_hints": ["coding"],
                },
                {
                    "key": "integration",
                    "title": "Integration",
                    "assigned_role": "backend",
                    "description_template": "Integrate backend and frontend work.",
                    "hard_dependencies": ["backend_impl", "frontend_ui"],
                    "soft_dependencies": [],
                    "required_artifacts": ["backend_impl", "frontend_ui"],
                    "produced_artifacts": ["integration_report"],
                    "approval_requirements": [],
                    "memory_scopes": ["project"],
                    "route_hints": ["integration"],
                },
                {
                    "key": "review",
                    "title": "Review",
                    "assigned_role": "reviewer",
                    "description_template": "Review the integration results.",
                    "hard_dependencies": ["integration"],
                    "soft_dependencies": [],
                    "required_artifacts": ["integration_report"],
                    "produced_artifacts": ["review_notes"],
                    "approval_requirements": ["review_signoff"],
                    "memory_scopes": ["project"],
                    "route_hints": ["review"],
                },
            ],
            "completion_rules": {"require_review": True},
        }
    )


def example_notifications_workflow_graph(
    *,
    project_id: str = "proj_notifications",
    team_id: str = "team_notifications",
    workflow_run_id: str = "workflow_notifications_run",
) -> WorkflowGraph:
    """Build the example workflow graph used in tests."""

    return build_workflow_graph(
        example_notifications_workflow_definition(),
        project_id=project_id,
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        workflow_definition_id="notifications_settings:1.0",
    )


def _validate_dependency_references(task_templates: dict[str, TaskTemplateConfig]) -> None:
    for template in task_templates.values():
        for dependency_key in (*template.hard_dependencies, *template.soft_dependencies):
            if dependency_key not in task_templates:
                raise ValueError(
                    f"task {template.key!r} references unknown dependency {dependency_key!r}"
                )


def _validate_acyclic(task_templates: dict[str, TaskTemplateConfig]) -> None:
    graph = {
        key: set(template.hard_dependencies) | set(template.soft_dependencies)
        for key, template in task_templates.items()
    }
    temp_mark: set[str] = set()
    permanent_mark: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> None:
        if node in permanent_mark:
            return
        if node in temp_mark:
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            raise ValueError(f"workflow graph contains a cycle: {' -> '.join(cycle)}")
        temp_mark.add(node)
        path.append(node)
        for dependency in graph[node]:
            visit(dependency)
        path.pop()
        temp_mark.remove(node)
        permanent_mark.add(node)

    for node in graph:
        visit(node)


def _topological_order(task_templates: dict[str, TaskTemplateConfig]) -> list[str]:
    graph = {
        key: set(template.hard_dependencies) | set(template.soft_dependencies)
        for key, template in task_templates.items()
    }
    indegree: dict[str, int] = {key: 0 for key in graph}
    downstream: dict[str, set[str]] = defaultdict(set)
    for node, dependencies in graph.items():
        for dependency in dependencies:
            indegree[node] += 1
            downstream[dependency].add(node)

    queue = deque([key for key, degree in indegree.items() if degree == 0])
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for child in sorted(downstream.get(node, set())):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(task_templates):
        raise ValueError("workflow graph contains a cycle")
    return ordered


class _SafeTemplateDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render_template(template: str, values: Mapping[str, Any]) -> str:
    if not values:
        return template
    rendered_values = _SafeTemplateDict(
        {
            key: value if isinstance(value, str) else json.dumps(value, sort_keys=True)
            for key, value in values.items()
        }
    )
    return template.format_map(rendered_values)
