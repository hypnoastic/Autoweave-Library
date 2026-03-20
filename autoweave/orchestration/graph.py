"""Graph inspection helpers for orchestration."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from autoweave.models import TaskEdgeRecord, TaskRecord, WorkflowGraph


@dataclass(slots=True, frozen=True)
class DependencyView:
    hard_predecessors: dict[str, tuple[str, ...]]
    hard_successors: dict[str, tuple[str, ...]]
    topological_order: tuple[str, ...]


def build_dependency_view(graph: WorkflowGraph) -> DependencyView:
    hard_predecessors: dict[str, list[str]] = defaultdict(list)
    hard_successors: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if not edge.is_hard_dependency:
            continue
        hard_predecessors[edge.to_task_id].append(edge.from_task_id)
        hard_successors[edge.from_task_id].append(edge.to_task_id)

    ordered = _topological_order(graph.tasks, graph.edges)
    return DependencyView(
        hard_predecessors={task_id: tuple(parents) for task_id, parents in hard_predecessors.items()},
        hard_successors={task_id: tuple(children) for task_id, children in hard_successors.items()},
        topological_order=tuple(ordered),
    )


def _topological_order(tasks: list[TaskRecord], edges: list[TaskEdgeRecord]) -> list[str]:
    indegree: dict[str, int] = {task.id: 0 for task in tasks}
    successors: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not edge.is_hard_dependency:
            continue
        indegree[edge.to_task_id] += 1
        successors[edge.from_task_id].add(edge.to_task_id)
    queue = deque([task_id for task_id, degree in indegree.items() if degree == 0])
    ordered: list[str] = []
    while queue:
        task_id = queue.popleft()
        ordered.append(task_id)
        for child in sorted(successors.get(task_id, set())):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(tasks):
        raise ValueError("workflow graph contains a cycle")
    return ordered
