from __future__ import annotations

from pathlib import Path

import pytest

from autoweave.compiler.loader import CanonicalConfigLoader
from autoweave.compiler.openhands import OpenHandsConfigCompiler
from autoweave.config_models import RuntimeConfig, VertexConfig, VertexProfileConfig
from autoweave.exceptions import ConfigurationError
from autoweave.models import TaskAttemptRecord, TaskRecord
from autoweave.routing.policy import RouteAuditLog, RouteFailureLedger, VertexModelRouter
from autoweave.workers.runtime import (
    OpenHandsRemoteWorkerAdapter,
    OpenHandsStreamEvent,
    WorkspacePolicy,
    build_openhands_conversation_request,
    extract_openhands_stream_events,
    normalize_openhands_stream_event,
    resolve_openhands_reasoning_effort,
    stream_event_to_artifact,
    build_vertex_worker_env,
)


def _vertex_config() -> VertexConfig:
    return VertexConfig(
        profile_definitions=[
            VertexProfileConfig(name="economy", model="vertex_ai/gemini-flash", timeout_seconds=30, budget_class="low"),
            VertexProfileConfig(
                name="balanced",
                model="vertex_ai/gemini-pro",
                timeout_seconds=60,
                budget_class="balanced",
            ),
            VertexProfileConfig(
                name="strong",
                model="vertex_ai/gemini-pro-plus",
                timeout_seconds=120,
                budget_class="high",
            ),
        ],
        fallback_order=["economy", "balanced", "strong"],
    )


def _task(role: str = "backend") -> TaskRecord:
    return TaskRecord(
        workflow_run_id="workflow_run_1",
        task_key=f"{role}_task",
        title=f"{role} task",
        description=f"{role} implementation",
        assigned_role=role,
        input_json={"user_request": "build a clothing storefront"},
    )


def _attempt(task: TaskRecord, attempt_number: int = 1) -> TaskAttemptRecord:
    return TaskAttemptRecord(
        task_id=task.id,
        attempt_number=attempt_number,
        agent_definition_id="agent_backend",
    )


def test_route_decision_is_recorded_and_explained() -> None:
    router = VertexModelRouter(_vertex_config(), audit_log=RouteAuditLog())
    task = _task()
    attempt = _attempt(task)

    route = router.select_route(task=task, attempt=attempt, hints=["backend"])

    assert route.provider_name == "VertexAI"
    assert route.model_name == "vertex_ai/gemini-pro"
    assert "role=backend" in route.route_reason
    assert "hints=backend" in route.route_reason
    assert router.audit_log.records == [route]


def test_repeated_failures_escalate_route_profile() -> None:
    ledger = RouteFailureLedger()
    router = VertexModelRouter(_vertex_config(), ledger=ledger)
    task = _task(role="backend")
    attempt = _attempt(task)

    initial_route = router.select_route(task=task, attempt=attempt, hints=[])
    router.record_failure(attempt.id)
    router.record_failure(attempt.id)
    escalated_route = router.select_route(task=task, attempt=attempt, hints=[])

    assert initial_route.model_name == "vertex_ai/gemini-pro"
    assert escalated_route.model_name == "vertex_ai/gemini-pro-plus"
    assert escalated_route.route_reason != initial_route.route_reason
    assert ledger.failure_count(attempt.id) == 2
    assert len(router.audit_log.records) == 2


def test_router_can_force_named_profile_override() -> None:
    router = VertexModelRouter(_vertex_config(), preferred_profile="economy")
    task = _task(role="manager")
    attempt = _attempt(task)

    route = router.select_route(task=task, attempt=attempt, hints=["planning"])

    assert route.model_name == "vertex_ai/gemini-flash"
    assert "forced_profile=economy" in route.route_reason


def test_compiler_builds_worker_config_with_vertex_env_and_no_login(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(task)
    route = VertexModelRouter(_vertex_config()).select_route(task=task, attempt=attempt, hints=["backend"])
    compiler = OpenHandsConfigCompiler(
        vertex_config=_vertex_config(),
        service_account_file=tmp_path / "vertex.json",
        workspace_policy=WorkspacePolicy(root_dir=tmp_path / "workspaces"),
    )

    compiled = compiler.compile_attempt_config(
        task=task,
        attempt=attempt,
        route=route,
        runtime_policy={
            "vertex_project": "autoweave-dev",
            "vertex_location": "us-central1",
            "permission_mode": "workspace-write",
            "tool_groups": ["context", "artifacts"],
        },
    )

    assert compiled["provider_name"] == "VertexAI"
    assert compiled["model_name"] == route.model_name
    assert compiled["interactive_login"] is False
    assert compiled["env"]["VERTEXAI_PROJECT"] == "autoweave-dev"
    assert compiled["env"]["VERTEXAI_LOCATION"] == "us-central1"
    assert compiled["env"]["VERTEXAI_SERVICE_ACCOUNT_FILE"] == str(tmp_path / "vertex.json")
    assert compiled["env"]["GOOGLE_APPLICATION_CREDENTIALS"] == str(tmp_path / "vertex.json")
    assert compiled["workspace_path"].endswith(str(tmp_path / "workspaces" / attempt.id))
    assert compiled["task_input_json"] == {"user_request": "build a clothing storefront"}


def test_vertex_env_mapping_requires_canonical_settings(tmp_path: Path) -> None:
    env = build_vertex_worker_env(
        project="autoweave-dev",
        location="us-central1",
        service_account_file=tmp_path / "vertex.json",
    )

    assert env == {
        "VERTEXAI_PROJECT": "autoweave-dev",
        "VERTEXAI_LOCATION": "us-central1",
        "VERTEXAI_SERVICE_ACCOUNT_FILE": str(tmp_path / "vertex.json"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "vertex.json"),
    }

    with pytest.raises(ConfigurationError):
        build_vertex_worker_env(project="", location="us-central1", service_account_file=tmp_path / "vertex.json")


def test_workspace_policy_isolated_and_resume_stable(tmp_path: Path) -> None:
    policy = WorkspacePolicy(root_dir=tmp_path / "workspaces")

    first = policy.workspace_path_for_attempt("attempt_1")
    second = policy.workspace_path_for_attempt("attempt_1")
    third = policy.workspace_path_for_attempt("attempt_2")
    reservation = policy.reserve(attempt_id="attempt_1", resumed_from_attempt_id="attempt_1")

    assert first == second
    assert first != third
    assert reservation.workspace_path == first
    assert reservation.reused_existing_workspace is True
    assert reservation.resumed_from_attempt_id == "attempt_1"


def test_config_loader_reads_yaml_model(tmp_path: Path) -> None:
    yaml_path = tmp_path / "vertex.yaml"
    yaml_path.write_text(
        """
provider_name: VertexAI
profile_definitions:
  - name: economy
    model: vertex_ai/gemini-flash
    timeout_seconds: 30
    budget_class: low
fallback_order: [economy]
""".strip()
    )

    loader = CanonicalConfigLoader(root_dir=tmp_path)
    loaded = loader.load_vertex_config("vertex.yaml")

    assert loaded.provider_name == "VertexAI"
    assert loaded.profile_definitions[0].name == "economy"


def test_runtime_config_accepts_declared_celery_queues(tmp_path: Path) -> None:
    yaml_path = tmp_path / "runtime.yaml"
    yaml_path.write_text(
        """
celery_queue_names:
  - dispatch
  - workers
default_concurrency: 4
retry_policy:
  max_attempts: 3
""".strip(),
        encoding="utf-8",
    )

    loader = CanonicalConfigLoader(root_dir=tmp_path)
    loaded = loader.load_runtime_config("runtime.yaml")

    assert isinstance(loaded, RuntimeConfig)
    assert loaded.celery_queue_names == ["dispatch", "workers"]
    assert loaded.default_concurrency == 4


def test_remote_worker_adapter_builds_launch_payload(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(task)
    router = VertexModelRouter(_vertex_config())
    route = router.select_route(task=task, attempt=attempt, hints=["backend"])
    adapter = OpenHandsRemoteWorkerAdapter(
        vertex_config=_vertex_config(),
        workspace_policy=WorkspacePolicy(root_dir=tmp_path / "workspaces"),
        service_account_file=tmp_path / "vertex.json",
    )

    payload = adapter.compile_launch_payload(
        task=task,
        attempt=attempt,
        route_reason=route.route_reason,
        route_model_name=route.model_name,
        runtime_policy={
            "vertex_project": "autoweave-dev",
            "vertex_location": "us-central1",
        },
    )

    assert payload["interactive_login"] is False
    assert payload["workspace_path"].endswith(str(tmp_path / "workspaces" / attempt.id))
    assert payload["task_input_json"] == {"user_request": "build a clothing storefront"}


def test_openhands_request_includes_task_input_json_block() -> None:
    request = build_openhands_conversation_request(
        {
            "provider_name": "VertexAI",
            "model_name": "gemini-3-flash-preview",
            "task_id": "task-1",
            "task_attempt_id": "attempt-1",
            "task_role": "manager",
            "task_title": "Manager plan",
            "task_description": "Plan the requested workflow.",
            "task_input_json": {"user_request": "build a clothing ecommerce site"},
            "route_reason": "role=manager",
            "workspace_path": "/workspace/workspaces/attempt-1",
            "runtime_policy": {"reasoning_effort": "none"},
        }
    )

    text = request["initial_message"]["content"][0]["text"]
    assert "Task Input JSON:" in text
    assert '"user_request": "build a clothing ecommerce site"' in text


def test_human_input_marker_is_normalized_to_requires_human() -> None:
    event = normalize_openhands_stream_event(
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "HUMAN_INPUT_REQUIRED: What product categories should the first release support?"}],
                "tool_calls": None,
            },
        }
    )

    assert event.event_type == "clarification"
    assert event.requires_human is True
    assert event.terminal is True
    assert event.message == "What product categories should the first release support?"


def test_openhands_stream_events_normalize_and_materialize_artifacts(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(task)

    stream_event = normalize_openhands_stream_event(
        {
            "type": "complete",
            "message": "done",
            "outcome": "success",
            "terminal": True,
            "artifact": {
                "artifact_type": "plan",
                "title": "Plan",
                "summary": "final plan",
                "status": "final",
                "storage_uri": "file:///tmp/plan.txt",
                "checksum": "sha256:abc",
            },
        }
    )
    extracted = extract_openhands_stream_events(
        {
            "events": [
                {
                    "event_type": stream_event.event_type,
                    "message": stream_event.message,
                    "payload_json": stream_event.payload_json,
                    "artifact": stream_event.artifact,
                    "outcome": stream_event.outcome,
                    "terminal": stream_event.terminal,
                }
            ]
        }
    )
    artifact = stream_event_to_artifact(stream_event, task=task, attempt=attempt)

    assert stream_event.event_type == "complete"
    assert stream_event.terminal is True
    assert extracted[0].message == "done"
    assert isinstance(stream_event, OpenHandsStreamEvent)
    assert artifact is not None
    assert artifact.artifact_type == "plan"
    assert artifact.status.value == "final"


def test_empty_openhands_message_event_is_marked_explicitly() -> None:
    stream_event = normalize_openhands_stream_event(
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [],
                "tool_calls": None,
            },
        }
    )

    assert stream_event.event_type == "empty_response"
    assert stream_event.empty_response is True
    assert stream_event.message == ""
    assert stream_event.payload_json["tool_call_count"] == 0


def test_empty_openhands_message_event_tracks_reasoning_only_payloads() -> None:
    stream_event = normalize_openhands_stream_event(
        {
            "kind": "MessageEvent",
            "source": "agent",
            "llm_message": {
                "role": "assistant",
                "content": [],
                "tool_calls": None,
                "reasoning_content": "internal reasoning only",
            },
        }
    )

    assert stream_event.event_type == "empty_response"
    assert stream_event.empty_response is True
    assert stream_event.payload_json["reasoning_content_present"] is True


def test_openhands_vertex_reasoning_defaults_to_none() -> None:
    request = build_openhands_conversation_request(
        {
            "provider_name": "VertexAI",
            "model_name": "gemini-3-flash-preview",
            "task_id": "task-1",
            "task_attempt_id": "attempt-1",
            "task_role": "manager",
            "task_title": "Manager plan",
            "task_description": "Plan the work.",
            "route_reason": "role=manager",
            "workspace_path": "/workspace/workspaces/attempt-1",
            "runtime_policy": {},
        }
    )

    assert request["agent"]["llm"]["reasoning_effort"] == "none"
    assert request["agent"]["llm"]["model"] == "vertex_ai/gemini-3-flash-preview"


def test_openhands_reasoning_override_is_respected() -> None:
    assert resolve_openhands_reasoning_effort(provider_name="VertexAI", runtime_policy={}) == "none"
    assert (
        resolve_openhands_reasoning_effort(
            provider_name="VertexAI",
            runtime_policy={"reasoning_effort": "medium"},
        )
        == "medium"
    )
