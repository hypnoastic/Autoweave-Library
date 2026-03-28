from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
from typer.testing import CliRunner

from apps.cli import main as cli_main
from autoweave.local_runtime import build_local_runtime
from autoweave.artifacts.filesystem import FilesystemArtifactStore
from autoweave.artifacts.registry import InMemoryArtifactRegistry
from autoweave.context.service import InMemoryContextService
from autoweave.graph.projection import SQLiteGraphProjectionBackend
from autoweave.memory.store import InMemoryMemoryStore
from autoweave.models import MemoryEntryRecord, MemoryLayer
from autoweave.settings import CANONICAL_VERTEX_CREDENTIALS, LocalEnvironmentSettings
from autoweave.storage.coordination import RedisClient, RedisIdempotencyStore, RedisLeaseManager
from autoweave.storage.durable import SQLiteWorkflowRepository
from autoweave.storage.wiring import LocalStorageWiring, RedisWireSpec, StorageConnectionTargets
from autoweave.workers.runtime import OpenHandsAgentServerClient, OpenHandsStreamEvent


runner = CliRunner()


def _write_docs(root: Path) -> None:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "autoweave_high_level_architecture.md",
        "autoweave_implementation_spec.md",
        "autoweave_diagrams_source.md",
    ):
        (docs_dir / name).write_text(f"# {name}\n", encoding="utf-8")


def _write_env_files(root: Path) -> None:
    (root / ".env").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=dotenv-project",
                "VERTEXAI_LOCATION=global",
                "VERTEXAI_SERVICE_ACCOUNT_FILE=legacy_vertex_key.json",
                "GOOGLE_APPLICATION_CREDENTIALS=legacy_vertex_key.json",
                "POSTGRES_URL=postgresql://autoweave:secret@ep-autoweave.us-east-2.aws.neon.tech/autoweave?sslmode=require",
                "REDIS_URL=redis://127.0.0.1:6379/0",
                "NEO4J_URL=neo4j+s://autoweave.databases.neo4j.io",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=neo4j-secret",
                "ARTIFACT_STORE_URL=var/artifacts",
                "OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:3001",
                "OPENHANDS_AGENT_SERVER_API_KEY=dotenv-key",
                "OPENHANDS_WORKER_TIMEOUT_SECONDS=90",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=local-project",
                "OPENHANDS_AGENT_SERVER_API_KEY=local-key",
                "ARTIFACT_STORE_URL=var/local-artifacts",
            ]
        ),
        encoding="utf-8",
    )


def _write_vertex_key(root: Path) -> Path:
    key_path = root / "legacy_vertex_key.json"
    key_path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "autoweave-local",
                "client_email": "autoweave@example.com",
            }
        ),
        encoding="utf-8",
    )
    return key_path


def _prepare_local_root(root: Path) -> None:
    _write_docs(root)
    _write_env_files(root)
    _write_vertex_key(root)
    from apps.cli.bootstrap import bootstrap_repository

    bootstrap_repository(root)


def _prepare_template_only_root(root: Path) -> None:
    _write_docs(root)
    _write_env_files(root)
    _write_vertex_key(root)


def _test_storage_wiring(settings: LocalEnvironmentSettings) -> LocalStorageWiring:
    artifact_root = settings.artifact_store_path()
    state_root = settings.project_root / "var" / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    workflow_repository = SQLiteWorkflowRepository(state_root / "autoweave.sqlite3")
    artifact_store = FilesystemArtifactStore(artifact_root)
    artifact_registry = InMemoryArtifactRegistry(workflow_repository, payload_store=artifact_store)
    memory_store = InMemoryMemoryStore()
    redis_target = settings.redis_target()
    return LocalStorageWiring(
        settings=settings,
        targets=StorageConnectionTargets(
            postgres=settings.postgres_target(),
            neo4j=settings.neo4j_target(),
            redis=redis_target,
            openhands=settings.openhands_target(),
            artifact_root=artifact_root,
        ),
        workflow_repository=workflow_repository,
        artifact_store=artifact_store,
        artifact_registry=artifact_registry,
        memory_store=memory_store,
        context_service=InMemoryContextService(
            workflow_repository=workflow_repository,
            artifact_registry=artifact_registry,
            memory_store=memory_store,
        ),
        graph_projection=SQLiteGraphProjectionBackend(state_root / "autoweave_projection.sqlite3"),
        lease_manager=RedisLeaseManager(client=RedisClient(settings.redis_url)),
        idempotency_store=RedisIdempotencyStore(client=RedisClient(settings.redis_url)),
        redis_wire=RedisWireSpec(
            database=redis_target.database,
            host=redis_target.host,
            port=redis_target.port,
        ),
    )


class _CountingWorkflowRepository:
    def __init__(self, inner: SQLiteWorkflowRepository) -> None:
        self.inner = inner
        self.save_graph_calls = 0
        self.save_workflow_run_calls = 0
        self.save_task_calls = 0
        self.save_runtime_state_calls = 0

    def save_graph(self, graph):
        self.save_graph_calls += 1
        return self.inner.save_graph(graph)

    def save_workflow_run(self, workflow_run):
        self.save_workflow_run_calls += 1
        return self.inner.save_workflow_run(workflow_run)

    def save_task(self, task):
        self.save_task_calls += 1
        return self.inner.save_task(task)

    def save_runtime_state(self, **kwargs):
        self.save_runtime_state_calls += 1
        graph = kwargs.get("graph")
        if graph is not None:
            self.save_graph_calls += 1
        else:
            self.save_workflow_run_calls += 1
            self.save_task_calls += len(list(kwargs.get("tasks", ())))
        return self.inner.save_runtime_state(**kwargs)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def _recording_transport(calls: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-1",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-1",
                    "execution_status": "finished",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "type": "progress",
                            "message": "worker started",
                            "outcome": "running",
                            "terminal": False,
                        },
                        {
                            "type": "complete",
                            "message": "task completed",
                            "outcome": "success",
                            "terminal": True,
                            "artifact": {
                                "artifact_type": "plan",
                                "title": "Manager plan",
                                "summary": "final notifications plan",
                                "status": "final",
                                "storage_uri": "file:///tmp/manager-plan.txt",
                                "checksum": "sha256:plan",
                                "metadata_json": {"content_type": "text/plain"},
                            },
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _finish_tool_transport(calls: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-finish",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-finish",
                },
            )
        if request.url.path == "/api/conversations/conversation-finish":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-finish",
                    "execution_status": "finished",
                    "persistence_dir": "workspace/conversations/conversation-finish",
                },
            )
        if request.url.path == "/api/conversations/conversation-finish/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "kind": "ActionEvent",
                            "tool_name": "finish",
                            "action": {
                                "kind": "FinishAction",
                                "message": "Completed the manager plan for the storefront.",
                            },
                        },
                        {
                            "kind": "ObservationEvent",
                            "tool_name": "finish",
                            "observation": {
                                "kind": "FinishObservation",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Completed the manager plan for the storefront.",
                                    }
                                ],
                            },
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _progress_only_transport(calls: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-progress",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-progress",
                },
            )
        if request.url.path == "/api/conversations/conversation-progress":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-progress",
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-progress",
                },
            )
        if request.url.path == "/api/conversations/conversation-progress/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "type": "progress",
                            "message": "worker still running",
                            "outcome": "running",
                            "terminal": False,
                        }
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _recoverable_agent_error_transport(calls: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-recovered-error",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-recovered-error",
                },
            )
        if request.url.path == "/api/conversations/conversation-recovered-error":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-recovered-error",
                    "execution_status": "finished",
                    "persistence_dir": "workspace/conversations/conversation-recovered-error",
                },
            )
        if request.url.path == "/api/conversations/conversation-recovered-error/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "kind": "AgentErrorEvent",
                            "tool_name": "file_editor",
                            "error": "invalid file_editor command",
                        },
                        {
                            "kind": "ActionEvent",
                            "tool_name": "finish",
                            "action": {
                                "kind": "FinishAction",
                                "message": "Recovered from a tool error and completed the plan.",
                            },
                        },
                        {
                            "kind": "ObservationEvent",
                            "tool_name": "finish",
                            "observation": {
                                "kind": "FinishObservation",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Recovered from a tool error and completed the plan.",
                                    }
                                ],
                            },
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def test_local_environment_settings_normalize_vertex_credentials(tmp_path: Path) -> None:
    _prepare_local_root(tmp_path)

    settings = LocalEnvironmentSettings.load(root=tmp_path, environ={})
    normalized_credentials = tmp_path / CANONICAL_VERTEX_CREDENTIALS

    assert settings.project_root == tmp_path
    assert settings.loaded_env_files == (tmp_path / ".env", tmp_path / ".env.local")
    assert settings.vertexai_project == "local-project"
    assert settings.vertexai_location == "global"
    assert settings.postgres_target().uses_neon is True
    assert settings.neo4j_target().uses_aura is True
    assert settings.vertex_service_account_file == normalized_credentials
    assert settings.google_application_credentials == normalized_credentials
    assert settings.worker_environment()["VERTEXAI_SERVICE_ACCOUNT_FILE"] == str(normalized_credentials)
    assert settings.worker_environment()["GOOGLE_APPLICATION_CREDENTIALS"] == str(normalized_credentials)
    assert normalized_credentials.exists()


def test_openhands_client_bootstrap_uses_httpx_and_api_key() -> None:
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    with OpenHandsAgentServerClient(
        base_url="http://127.0.0.1:3001",
        api_key="secret-key",
        bootstrap_path="/api/conversations",
        transport=transport,
    ) as client:
        health = client.health_probe()
        bootstrap = client.bootstrap_attempt(
            {
                "provider_name": "VertexAI",
                "model_name": "gemini-3-flash-preview",
                "task_id": "task-1",
                "task_attempt_id": "attempt-1",
                "task_role": "backend",
                "task_title": "Implement backend task",
                "task_description": "Build the backend API contract and implementation.",
                "route_reason": "role=backend",
                "workspace_path": "workspaces/task-1",
                "runtime_policy": {"reasoning_effort": "medium"},
            }
        )

    assert health.ok is True
    assert health.status_code == 200
    assert bootstrap.ok is True
    assert bootstrap.status_code == 201
    assert calls[0]["path"] == "/health"
    assert calls[0]["headers"]["authorization"] == "Bearer secret-key"
    assert calls[1]["path"] == "/api/conversations"
    assert calls[1]["body"]["workspace"]["working_dir"] == "workspaces/task-1"
    assert calls[1]["body"]["agent"]["llm"]["model"] == "vertex_ai/gemini-3-flash-preview"
    assert calls[1]["body"]["agent"]["llm"]["reasoning_effort"] == "medium"
    assert [tool["name"] for tool in calls[1]["body"]["agent"]["tools"]] == ["terminal", "file_editor", "task_tracker"]
    assert calls[1]["body"]["agent"]["tools"][0]["params"] == {}
    assert calls[1]["body"]["initial_message"]["content"][0]["text"].startswith("Task ID: task-1")
    assert "Task Input JSON:" not in calls[1]["body"]["initial_message"]["content"][0]["text"]


def test_local_runtime_bootstrap_composes_and_dispatches(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        doctor = runtime.doctor()
        example = runtime.run_example(dispatch=True)

    normalized_credentials = tmp_path / CANONICAL_VERTEX_CREDENTIALS

    assert runtime.worker_adapter.service_account_file == normalized_credentials
    assert runtime.openhands_client.bootstrap_path == "/api/conversations"
    assert runtime.settings.artifact_store_path() == tmp_path / "var" / "local-artifacts"
    assert doctor.ready_task_keys == ("manager_plan",)
    assert doctor.openhands_health.ok is True
    assert doctor.vertex_worker_env["GOOGLE_APPLICATION_CREDENTIALS"] == str(normalized_credentials)
    assert "autoweave:secret" not in doctor.postgres_target
    assert '"password": "***"' in doctor.neo4j_target
    assert example.ready_task_keys == ("manager_plan",)
    assert example.route_model_name == "gemini-3.1-pro-preview"
    assert example.bootstrap_call is not None and example.bootstrap_call.ok is True
    assert example.openhands_health.ok is True
    assert example.launch_payload["env"]["GOOGLE_APPLICATION_CREDENTIALS"] == str(normalized_credentials)
    assert example.launch_payload["runtime_policy"]["reasoning_effort"] == "none"
    assert example.launch_payload["workspace_path"] == f"/workspace/workspaces/{example.launch_payload['task_attempt_id']}"
    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"
    assert example.workflow_status == "running"
    assert example.stream_event_types == ("progress", "complete")
    assert len(example.artifact_ids) == 2
    manifests = [runtime.storage.artifact_store.read_manifest(artifact_id) for artifact_id in example.artifact_ids]
    assert {manifest["artifact"]["artifact_type"] for manifest in manifests} == {"plan", "openhands_replay"}
    assert any(manifest["payload"] == "final notifications plan" for manifest in manifests)
    replay_manifest = next(manifest for manifest in manifests if manifest["artifact"]["artifact_type"] == "openhands_replay")
    assert replay_manifest["payload"]["conversation_id"] == "conversation-1"
    assert replay_manifest["payload"]["execution_status"] == "finished"
    persisted_task = runtime.storage.workflow_repository.get_task(example.launch_payload["task_id"])
    persisted_attempt = runtime.storage.workflow_repository.get_attempt(example.launch_payload["task_attempt_id"])
    persisted_graph = runtime.storage.workflow_repository.get_graph(example.workflow_run_id)
    assert persisted_task.state.value == "completed"
    assert persisted_attempt.state.value == "succeeded"
    assert persisted_graph.workflow_run.status.value == "running"
    assert calls[2]["body"]["agent"]["llm"]["reasoning_effort"] == "none"
    assert calls[2]["body"]["agent"]["llm"]["model"] == "vertex_ai/gemini-3.1-pro-preview"
    assert '"user_request": "build a clothing storefront"' not in calls[2]["body"]["initial_message"]["content"][0]["text"]
    assert [entry["path"] for entry in calls] == [
        "/health",
        "/health",
        "/api/conversations",
        "/api/conversations/conversation-1",
        "/api/conversations/conversation-1",
        "/api/conversations/conversation-1/events/search",
        "/api/conversations/conversation-1",
    ]


def test_local_runtime_treats_finish_tool_events_as_success(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _finish_tool_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"
    assert example.stream_event_types == ("complete",)
    manifests = [runtime.storage.artifact_store.read_manifest(artifact_id) for artifact_id in example.artifact_ids]
    assert {manifest["artifact"]["artifact_type"] for manifest in manifests} == {"openhands_replay", "workflow_plan"}
    assert any(manifest["payload"] == "Completed the manager plan for the storefront." for manifest in manifests)


def test_local_runtime_ignores_recovered_agent_error_when_conversation_finishes_successfully(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recoverable_agent_error_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"
    assert example.failure_reason is None
    assert example.stream_event_types == ("diagnostic", "complete")
    manifests = [runtime.storage.artifact_store.read_manifest(artifact_id) for artifact_id in example.artifact_ids]
    replay_manifest = next(manifest for manifest in manifests if manifest["artifact"]["artifact_type"] == "openhands_replay")
    assert replay_manifest["payload"]["execution_status"] == "finished"


def test_local_runtime_retries_poll_timeout_before_failing(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _progress_only_transport(calls)
    wait_calls: list[float] = []

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_wait_for_conversation(self, conversation_id: str, *, timeout_seconds: float, poll_interval_seconds: float = 1.0):
        wait_calls.append(timeout_seconds)
        if len(wait_calls) == 1:
            return replace(
                type(self).get_conversation(self, conversation_id),
                ok=False,
                error=f"conversation poll timed out after {timeout_seconds:.1f}s",
            )
        return replace(
            type(self).get_conversation(self, conversation_id),
            ok=True,
            error=None,
            response_json={"id": conversation_id, "execution_status": "finished"},
        )

    monkeypatch.setattr(OpenHandsAgentServerClient, "wait_for_conversation", fake_wait_for_conversation)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"
    assert example.stream_event_types == ("progress", "complete")
    assert len(wait_calls) == 2
    assert wait_calls[0] == runtime.settings.autoweave_openhands_poll_timeout_seconds
    assert wait_calls[1] == 10.0


def test_local_runtime_run_workflow_propagates_request_and_advances_multiple_tasks(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a small ecommerce website for clothing brands. Ask for clarification if checkout or product constraints are missing.",
            dispatch=True,
            max_steps=4,
        )

    assert report.workflow_status == "running"
    assert report.dispatched_task_keys[0] == "manager_plan"
    assert set(report.dispatched_task_keys[1:3]) == {"backend_contract", "frontend_ui"}
    assert report.dispatched_task_keys[3] == "backend_impl"
    assert report.dispatched_task_keys.index("backend_contract") < report.dispatched_task_keys.index("backend_impl")
    assert report.open_human_questions == ()
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    assert len(conversation_calls) == 4
    first_prompt = conversation_calls[0]["body"]["initial_message"]["content"][0]["text"]
    assert "Task Input JSON:" in first_prompt
    assert '"user_request": "Build a small ecommerce website for clothing brands. Ask for clarification if checkout or product constraints are missing."' in first_prompt
    downstream_prompts = [call["body"]["initial_message"]["content"][0]["text"] for call in conversation_calls[1:]]
    assert all(
        '"user_request": "Build a small ecommerce website for clothing brands. Ask for clarification if checkout or product constraints are missing."' in prompt
        for prompt in downstream_prompts
    )
    assert any('"upstream_artifacts"' in prompt for prompt in downstream_prompts)


def test_local_runtime_persists_memory_and_injects_it_into_downstream_prompts(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a bookings app with a manager plan and downstream implementation.",
            dispatch=True,
            max_steps=2,
        )
        memory_entries = runtime.storage.workflow_repository.list_memory_entries("workflow_run", report.workflow_run_id)

    assert any("Manager plan: task completed" == entry.content for entry in memory_entries)
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    assert len(conversation_calls) == 2
    downstream_prompt = conversation_calls[1]["body"]["initial_message"]["content"][0]["text"]
    assert '"memory_context"' in downstream_prompt
    assert "Manager plan: task completed" in downstream_prompt


def test_local_runtime_projects_lifecycle_events_into_graph_backend(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)
        projected_events = runtime.storage.graph_projection.list_events()
        related_entities = runtime.storage.graph_projection.query_related_entities(example.launch_payload["task_id"], depth=8)

    assert projected_events
    assert any(event.event_type == "attempt.opened" for event in projected_events)
    assert any(relation["relation"] == "HAS_ATTEMPT" for relation in related_entities)


def test_local_runtime_dispatches_newly_ready_backend_work_while_frontend_branch_is_still_running(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)
    timeline: dict[str, float] = {}
    timeline_lock = threading.Lock()

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_collect(self, *, task, attempt, bootstrap_call, stream_events):
        with timeline_lock:
            timeline[f"{task.task_key}_start"] = time.monotonic()
        if task.task_key == "frontend_ui":
            time.sleep(0.2)
        with timeline_lock:
            timeline[f"{task.task_key}_end"] = time.monotonic()
        return (
            [
                OpenHandsStreamEvent(event_type="progress", message=f"{task.task_key} running", outcome="running"),
                OpenHandsStreamEvent(
                    event_type="complete",
                    message=f"{task.task_key} completed",
                    outcome="success",
                    terminal=True,
                ),
            ],
            (),
        )

    monkeypatch.setattr("autoweave.local_runtime.LocalRuntime._collect_openhands_stream", fake_collect)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a small ecommerce website for clothing brands. Ask for clarification if checkout or product constraints are missing.",
            dispatch=True,
            max_steps=4,
        )

    assert report.dispatched_task_keys[0] == "manager_plan"
    assert set(report.dispatched_task_keys[1:3]) == {"backend_contract", "frontend_ui"}
    assert report.dispatched_task_keys[3] == "backend_impl"
    assert "frontend_ui_start" in timeline
    assert "frontend_ui_end" in timeline
    assert "backend_contract_end" in timeline
    assert "backend_impl_start" in timeline
    assert timeline["backend_contract_end"] < timeline["frontend_ui_end"]
    assert timeline["backend_impl_start"] < timeline["frontend_ui_end"]


def test_local_runtime_run_workflow_stops_on_human_input_request(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a small clothing ecommerce site.",
            dispatch=True,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "HUMAN_INPUT_REQUIRED: Which payment providers and shipping regions should the first release support?",
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                ),
            },
        )

    assert report.dispatched_task_keys == ("manager_plan",)
    assert report.workflow_status == "running"
    assert report.open_human_questions == (
        "Which payment providers and shipping regions should the first release support?",
    )
    assert report.step_reports[0].attempt_state == "needs_input"
    assert report.step_reports[0].task_state == "waiting_for_human"


def test_local_runtime_promotes_manager_semantic_clarification_to_waiting_for_human(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a modern booking app.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Before I proceed, I need clarification. "
                                        "What exact thing is being booked? "
                                        "Should payment be collected upfront?"
                                    ),
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                ),
            },
        )

    assert report.dispatched_task_keys == ("manager_plan",)
    assert report.open_human_questions == (
        "What exact thing is being booked?\nShould payment be collected upfront?",
    )
    assert report.step_reports[0].attempt_state == "needs_input"
    assert report.step_reports[0].task_state == "waiting_for_human"


def test_local_runtime_ignores_user_echo_when_detecting_manager_semantic_clarification(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a modern booking app.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "user",
                        "llm_message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Resolved Clarifications:\n"
                                        "- What exact thing is being booked? -> Private study rooms.\n"
                                        "Task Input JSON:\n"
                                        '{"clarification_answers":{"What exact thing is being booked?":"Private study rooms."}}'
                                    ),
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                    {
                        "kind": "ObservationEvent",
                        "tool_name": "finish",
                        "observation": {
                            "kind": "FinishObservation",
                            "content": [{"type": "text", "text": "Planned the booking app using the resolved clarification."}],
                        },
                    },
                ),
            },
        )

    assert report.open_human_questions == ()
    assert report.step_reports[0].task_state == "completed"


def test_local_runtime_high_autonomy_keeps_manager_moving_on_non_blocking_semantic_questions(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(
        root=tmp_path,
        environ={"AUTOWEAVE_AUTONOMY_LEVEL": "high"},
        transport=transport,
    ) as runtime:
        report = runtime.run_workflow(
            request="Build a modern booking app.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Before I proceed, I need clarification. "
                                        "What exact thing is being booked? "
                                        "Should payment be collected upfront?"
                                    ),
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                    {
                        "kind": "ObservationEvent",
                        "tool_name": "finish",
                        "observation": {
                            "kind": "FinishObservation",
                            "content": [{"type": "text", "text": "Planned the booking app with default assumptions."}],
                        },
                    },
                ),
            },
        )

    assert report.dispatched_task_keys == ("manager_plan",)
    assert report.open_human_questions == ()
    assert report.step_reports[0].task_state == "completed"
    prompt = next(call for call in calls if call["path"] == "/api/conversations")["body"]["initial_message"]["content"][0]["text"]
    assert '"autonomy_level": "high"' in prompt


def test_local_runtime_can_resume_after_human_answer(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        initial = runtime.run_workflow(
            request="Build a small clothing ecommerce site and ask for missing checkout details.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "HUMAN_INPUT_REQUIRED: Which payment providers and shipping regions should the first release support?",
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                ),
            },
        )
        request = runtime.storage.workflow_repository.list_human_requests_for_run(initial.workflow_run_id)[0]
        resumed = runtime.answer_human_request(
            workflow_run_id=initial.workflow_run_id,
            request_id=request.id,
            answer_text="Use Stripe only and ship within the US.",
            answered_by="operator",
            dispatch=True,
            max_steps=1,
        )
        updated_request = runtime.storage.workflow_repository.get_human_request(request.id)

    assert initial.open_human_questions == (
        "Which payment providers and shipping regions should the first release support?",
    )
    assert updated_request.status.value == "answered"
    assert updated_request.answer_text == "Use Stripe only and ship within the US."
    assert resumed.dispatched_task_keys == ("manager_plan",)
    assert resumed.open_human_questions == ()
    assert resumed.step_reports[0].task_key == "manager_plan"
    assert resumed.step_reports[0].task_state == "completed"
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    assert len(conversation_calls) == 2
    resumed_prompt = conversation_calls[1]["body"]["initial_message"]["content"][0]["text"]
    assert "latest_human_answer" in resumed_prompt
    assert "clarification_answers" in resumed_prompt
    assert "Use Stripe only and ship within the US." in resumed_prompt


def test_local_runtime_reuses_answered_semantic_clarification_without_reopening_human_loop(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    event_search_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal event_search_count
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-1",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-1",
                    "execution_status": "finished",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1/events/search":
            event_search_count += 1
            if event_search_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "type": "message",
                                "message": "Before I proceed, I need clarification. What exact thing is being booked?",
                                "terminal": False,
                            }
                        ],
                        "next_page_id": None,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "type": "progress",
                            "message": "worker started",
                            "outcome": "running",
                            "terminal": False,
                        },
                        {
                            "type": "complete",
                            "message": "task completed",
                            "outcome": "success",
                            "terminal": True,
                            "artifact": {
                                "artifact_type": "workflow_plan",
                                "title": "Manager plan",
                                "summary": "manager plan completed",
                                "status": "final",
                                "storage_uri": "file:///tmp/manager-plan.txt",
                                "checksum": "sha256:plan",
                                "metadata_json": {"content_type": "text/plain"},
                            },
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        initial = runtime.run_workflow(
            request="Build a modern booking app.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "type": "message",
                        "message": "Before I proceed, I need clarification. What exact thing is being booked?",
                        "terminal": False,
                    },
                ),
            },
        )
        request = runtime.storage.workflow_repository.list_human_requests_for_run(initial.workflow_run_id)[0]
        resumed = runtime.answer_human_request(
            workflow_run_id=initial.workflow_run_id,
            request_id=request.id,
            answer_text="Private study rooms are being booked.",
            answered_by="operator",
            dispatch=True,
            max_steps=3,
        )
        requests = runtime.storage.workflow_repository.list_human_requests_for_run(initial.workflow_run_id)

    assert initial.open_human_questions == ("What exact thing is being booked?",)
    assert resumed.open_human_questions == ()
    assert resumed.dispatched_task_keys[:2] == ("manager_plan", "manager_plan")
    assert any(report.task_key == "manager_plan" and report.task_state == "completed" for report in resumed.step_reports)
    assert len(requests) == 1
    assert requests[0].status.value == "answered"
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    manager_calls = [
        call
        for call in conversation_calls
        if "Role: manager" in str(call["body"]["initial_message"]["content"][0]["text"])
        and "Title: Manager plan" in str(call["body"]["initial_message"]["content"][0]["text"])
    ]
    assert len(manager_calls) >= 3
    reused_prompt = manager_calls[-2]["body"]["initial_message"]["content"][0]["text"]
    retry_prompt = manager_calls[-1]["body"]["initial_message"]["content"][0]["text"]
    assert "Resolved Clarifications:" in reused_prompt
    assert "Do not ask the same questions again" in reused_prompt
    assert "clarification_answers" in reused_prompt
    assert "Private study rooms are being booked." in reused_prompt
    assert "Resolved Clarifications:" in retry_prompt
    assert "clarification_answers" in retry_prompt
    assert "Private study rooms are being booked." in retry_prompt


def test_local_runtime_fails_after_duplicate_answered_clarification_loop_limit(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    event_search_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal event_search_count
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": {key.lower(): value for key, value in request.headers.items()},
                "body": body,
            }
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(
                201,
                json={
                    "id": "conversation-1",
                    "workspace": body.get("workspace", {}),
                    "agent": body.get("agent", {}),
                    "execution_status": "running",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1":
            return httpx.Response(
                200,
                json={
                    "id": "conversation-1",
                    "execution_status": "finished",
                    "persistence_dir": "workspace/conversations/conversation-1",
                },
            )
        if request.url.path == "/api/conversations/conversation-1/events/search":
            event_search_count += 1
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "type": "message",
                            "message": "Before I proceed, I need clarification. What exact thing is being booked?",
                            "terminal": False,
                        }
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        runtime.runtime_config.clarification_retry_limit = 2
        initial = runtime.run_workflow(
            request="Build a modern booking app.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "type": "message",
                        "message": "Before I proceed, I need clarification. What exact thing is being booked?",
                        "terminal": False,
                    },
                ),
            },
        )
        request = runtime.storage.workflow_repository.list_human_requests_for_run(initial.workflow_run_id)[0]
        resumed = runtime.answer_human_request(
            workflow_run_id=initial.workflow_run_id,
            request_id=request.id,
            answer_text="Private study rooms are being booked.",
            answered_by="operator",
            dispatch=True,
            max_steps=3,
        )
        task = runtime.storage.workflow_repository.get_task_by_key(initial.workflow_run_id, "manager_plan")
        events = runtime.storage.workflow_repository.list_events(initial.workflow_run_id)

    assert initial.open_human_questions == ("What exact thing is being booked?",)
    assert resumed.workflow_status == "failed"
    assert resumed.open_human_questions == ()
    assert resumed.step_reports[-1].task_key == "manager_plan"
    assert resumed.step_reports[-1].task_state == "failed"
    assert resumed.step_reports[-1].failure_reason == "duplicate_answered_clarification_loop: What exact thing is being booked?"
    assert task.state.value == "failed"
    assert any(event.event_type == "attempt.duplicate_answered_clarification_loop" for event in events)


def test_local_runtime_waits_for_worker_requested_approval_and_can_resume_after_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        initial = runtime.run_workflow(
            request="Build a small clothing ecommerce site with a gated plan.",
            dispatch=True,
            max_steps=1,
            stream_events_by_task={
                "manager_plan": (
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "APPROVAL_REQUIRED: Approve the manager plan before I dispatch the downstream implementation work.",
                                }
                            ],
                            "tool_calls": None,
                        },
                    },
                ),
            },
        )
        approval_request = runtime.storage.workflow_repository.list_approval_requests_for_run(initial.workflow_run_id)[0]
        resumed = runtime.resolve_approval_request(
            workflow_run_id=initial.workflow_run_id,
            request_id=approval_request.id,
            approved=True,
            resolved_by="operator",
            dispatch=True,
            max_steps=1,
        )
        updated_request = runtime.storage.workflow_repository.get_approval_request(approval_request.id)

    assert initial.open_approval_reasons == ("Approve the manager plan before I dispatch the downstream implementation work.",)
    assert initial.step_reports[0].attempt_state == "paused"
    assert initial.step_reports[0].task_state == "waiting_for_approval"
    assert updated_request.status.value == "approved"
    assert resumed.dispatched_task_keys == ("manager_plan",)
    assert resumed.step_reports[0].task_key == "manager_plan"
    assert resumed.step_reports[0].task_state == "completed"
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    assert len(conversation_calls) == 2


def test_local_runtime_adds_single_review_rework_branch_without_second_review(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_collect(self, *, task, attempt, bootstrap_call, stream_events):
        if task.task_key == "review":
            return (
                [
                    OpenHandsStreamEvent(event_type="progress", message="review running", outcome="running"),
                    OpenHandsStreamEvent(
                        event_type="complete",
                        message="REVIEW_DECISION: REVISE. Changes requested for validation gaps and UX polish.",
                        artifact={
                            "artifact_type": "review_notes",
                            "title": "Review notes",
                            "summary": (
                                "REVIEW_DECISION: REVISE\n"
                                "Backend: tighten validation.\n"
                                "Frontend: simplify loading states.\n"
                                "Integration: verify seeded data flow."
                            ),
                            "status": "final",
                            "metadata_json": {"content_type": "text/plain"},
                        },
                        outcome="success",
                        terminal=True,
                    ),
                ],
                (),
            )
        return (
            [
                OpenHandsStreamEvent(event_type="progress", message=f"{task.task_key} running", outcome="running"),
                OpenHandsStreamEvent(
                    event_type="complete",
                    message=f"{task.task_key} completed",
                    outcome="success",
                    terminal=True,
                ),
            ],
            (),
        )

    monkeypatch.setattr("autoweave.local_runtime.LocalRuntime._collect_openhands_stream", fake_collect)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a serious booking app with one review pass and then rework if needed.",
            dispatch=True,
            max_steps=10,
        )
        graph = runtime.storage.workflow_repository.get_graph(report.workflow_run_id)

    task_keys = [task.task_key for task in graph.tasks]
    assert report.workflow_status == "running"
    assert report.dispatched_task_keys.count("review") == 1
    assert "manager_rework" in task_keys
    assert "backend_rework" in task_keys
    assert "frontend_rework" in task_keys
    assert "integration_rework" in task_keys
    assert "release_signoff" in task_keys
    release_signoff = next(task for task in graph.tasks if task.task_key == "release_signoff")
    assert release_signoff.state.value == "created"
    assert "review" in report.dispatched_task_keys
    assert "integration_rework" in report.dispatched_task_keys


def test_local_runtime_review_requires_validation_evidence_for_approval(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        runtime.run_workflow(
            request="Build a booking app.",
            dispatch=False,
            max_steps=1,
        )
        review_task = runtime.orchestration.state.task("review")

        decision = runtime._review_decision(review_task, "REVIEW_DECISION: APPROVE. Looks good.")

    assert decision == "revise"


def test_local_runtime_requires_release_signoff_after_single_review_pass(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_collect(self, *, task, attempt, bootstrap_call, stream_events):
        if task.task_key == "review":
            return (
                [
                    OpenHandsStreamEvent(event_type="progress", message="review running", outcome="running"),
                    OpenHandsStreamEvent(
                        event_type="complete",
                        message=(
                            "REVIEW_DECISION: APPROVE. Validated in browser, build passed, "
                            "and API smoke test passed."
                        ),
                        artifact={
                            "artifact_type": "review_notes",
                            "title": "Review notes",
                            "summary": (
                                "REVIEW_DECISION: APPROVE\n"
                                "Validated in browser.\n"
                                "Build passed.\n"
                                "API smoke test passed."
                            ),
                            "status": "final",
                            "metadata_json": {"content_type": "text/plain"},
                        },
                        outcome="success",
                        terminal=True,
                    ),
                ],
                (),
            )
        return (
            [
                OpenHandsStreamEvent(event_type="progress", message=f"{task.task_key} running", outcome="running"),
                OpenHandsStreamEvent(
                    event_type="complete",
                    message=f"{task.task_key} completed with runnable validation",
                    outcome="success",
                    terminal=True,
                ),
            ],
            (),
        )

    monkeypatch.setattr("autoweave.local_runtime.LocalRuntime._collect_openhands_stream", fake_collect)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(
            request="Build a serious booking app and stop for final release signoff.",
            dispatch=True,
            max_steps=10,
        )
        graph = runtime.storage.workflow_repository.get_graph(report.workflow_run_id)
        approval_requests = runtime.storage.workflow_repository.list_approval_requests_for_run(report.workflow_run_id)

    release_signoff = next(task for task in graph.tasks if task.task_key == "release_signoff")
    assert report.workflow_status == "running"
    assert report.open_approval_reasons == ("Approval required before dispatch: release_signoff",)
    assert release_signoff.state.value == "waiting_for_approval"
    assert len(approval_requests) == 1
    assert approval_requests[0].approval_type == "release_signoff"


def test_local_runtime_purge_workflow_runs_clears_project_memory_store_entries(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.run_workflow(request="cleanup memory", dispatch=False, max_steps=1)
        workflow_run = runtime.storage.workflow_repository.list_workflow_runs()[0]
        task = runtime.storage.workflow_repository.list_tasks_for_run(report.workflow_run_id)[0]
        memory_entry = MemoryEntryRecord(
            project_id=workflow_run.project_id,
            scope_type="project",
            scope_id=workflow_run.project_id,
            memory_layer=MemoryLayer.SEMANTIC,
            content="stale project memory for cleanup",
            metadata_json={
                "workflow_run_id": report.workflow_run_id,
                "task_id": task.id,
            },
        )
        runtime.storage.workflow_repository.save_memory_entry(memory_entry)
        runtime.storage.memory_store.write(memory_entry)

        assert runtime.storage.context_service.list_memory_entries("project", workflow_run.project_id)

        cleanup = runtime.purge_workflow_runs([report.workflow_run_id])

        assert cleanup.purged_run_ids == (report.workflow_run_id,)
        assert runtime.storage.context_service.list_memory_entries("project", workflow_run.project_id) == []


def test_cli_doctor_and_run_example_use_composed_runtime(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    def fake_build_local_runtime(*, root=None, environ=None, transport=None, bootstrap_path="/api/conversations"):
        return build_local_runtime(
            root=root,
            environ={},
            transport=transport or fake_transport,
            bootstrap_path=bootstrap_path,
        )

    fake_transport = transport
    monkeypatch.setattr(cli_main, "build_local_runtime", fake_build_local_runtime)
    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    doctor_result = runner.invoke(cli_main.app, ["doctor", "--root", str(tmp_path)])
    run_result = runner.invoke(cli_main.app, ["run-example", "--root", str(tmp_path)])

    assert doctor_result.exit_code == 0
    assert "validation=ok" in doctor_result.stdout
    assert "openhands_health=ok" in doctor_result.stdout
    assert "ready_tasks=manager_plan" in doctor_result.stdout

    assert run_result.exit_code == 0
    assert "validation=ok" in run_result.stdout
    assert "openhands_health=ok" in run_result.stdout
    assert "launch_provider=VertexAI" in run_result.stdout
    assert "bootstrap_call=" not in run_result.stdout


def test_local_runtime_doctor_reports_real_celery_health_when_backend_is_enabled(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    class _FakeDispatcher:
        @classmethod
        def from_runtime(cls, runtime):
            return cls()

        def worker_health(self) -> str:
            return "ok (workers=1; queues=dispatch)"

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    monkeypatch.setattr("autoweave.celery_queue.CeleryWorkflowDispatcher", _FakeDispatcher)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        report = runtime.doctor()

    assert report.execution_backend == "celery"
    assert report.celery_health == "ok (workers=1; queues=dispatch)"


def test_cli_run_workflow_uses_composed_runtime(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    def fake_build_local_runtime(*, root=None, environ=None, transport=None, bootstrap_path="/api/conversations"):
        return build_local_runtime(
            root=root,
            environ={},
            transport=transport or fake_transport,
            bootstrap_path=bootstrap_path,
        )

    fake_transport = transport
    monkeypatch.setattr(cli_main, "build_local_runtime", fake_build_local_runtime)
    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    result = runner.invoke(
        cli_main.app,
        [
            "run-workflow",
            "--root",
            str(tmp_path),
            "--request",
            "Build a small clothing ecommerce website and ask if checkout details are missing.",
        ],
    )

    assert result.exit_code == 0
    assert "validation=ok" in result.stdout
    assert "workflow_run_id=" in result.stdout
    assert "request=Build a small clothing ecommerce website and ask if checkout details are missing." in result.stdout


def test_local_runtime_can_force_legacy_vertex_profile(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(
        root=tmp_path,
        environ={"AUTOWEAVE_VERTEX_PROFILE_OVERRIDE": "legacy_fast"},
        transport=transport,
    ) as runtime:
        example = runtime.run_example(dispatch=True)

    conversation_call = next(call for call in calls if call["path"] == "/api/conversations")
    assert runtime.router.preferred_profile == "legacy_fast"
    assert example.route_model_name == "gemini-2.5-flash"
    assert conversation_call["body"]["agent"]["llm"]["model"] == "vertex_ai/gemini-2.5-flash"


def test_local_runtime_marks_attempt_failed_when_openhands_errors(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        calls.append({"method": request.method, "path": request.url.path, "body": body})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(201, json={"id": "conversation-err", "execution_status": "running"})
        if request.url.path == "/api/conversations/conversation-err":
            return httpx.Response(200, json={"id": "conversation-err", "execution_status": "error"})
        if request.url.path == "/api/conversations/conversation-err/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "kind": "ConversationStateUpdateEvent",
                            "source": "environment",
                            "key": "execution_status",
                            "value": "running",
                        },
                        {
                            "kind": "ConversationErrorEvent",
                            "source": "environment",
                            "code": "LLMBadRequestError",
                            "detail": "vertex permission denied",
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=httpx.MockTransport(handler)) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.bootstrap_call is not None and example.bootstrap_call.ok is True
    assert example.task_state == "failed"
    assert example.attempt_state == "errored"
    assert example.stream_event_types == ("progress", "error")
    assert len(example.artifact_ids) == 1
    replay_manifest = runtime.storage.artifact_store.read_manifest(example.artifact_ids[0])
    assert replay_manifest["artifact"]["artifact_type"] == "openhands_replay"
    assert replay_manifest["payload"]["execution_status"] == "error"


def test_local_runtime_surfaces_empty_response_loop_with_precise_reason(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/conversations":
            return httpx.Response(201, json={"id": "conversation-stuck", "execution_status": "running"})
        if request.url.path == "/api/conversations/conversation-stuck":
            return httpx.Response(200, json={"id": "conversation-stuck", "execution_status": "stuck"})
        if request.url.path == "/api/conversations/conversation-stuck/events/search":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "kind": "ConversationStateUpdateEvent",
                            "source": "environment",
                            "key": "execution_status",
                            "value": "running",
                        },
                        {
                            "kind": "MessageEvent",
                            "source": "agent",
                            "llm_message": {
                                "role": "assistant",
                                "content": [],
                                "tool_calls": None,
                            },
                        },
                        {
                            "kind": "MessageEvent",
                            "source": "agent",
                            "llm_message": {
                                "role": "assistant",
                                "content": [],
                                "tool_calls": None,
                            },
                        },
                        {
                            "kind": "ConversationStateUpdateEvent",
                            "source": "environment",
                            "key": "execution_status",
                            "value": "stuck",
                        },
                    ],
                    "next_page_id": None,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=httpx.MockTransport(handler)) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.task_state == "blocked"
    assert example.attempt_state == "orphaned"
    assert example.stream_event_types[:4] == ("progress", "empty_response", "empty_response", "error")
    assert example.stream_event_types[-1] == "error"
    assert example.failure_reason is not None
    assert "worker_empty_response_loop" in example.failure_reason


def test_local_runtime_retries_empty_response_loop_before_succeeding(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_collect(self, *, task, attempt, bootstrap_call, stream_events):
        if attempt.attempt_number == 1:
            return (
                [
                    OpenHandsStreamEvent(event_type="progress", message="worker started", outcome="running"),
                    OpenHandsStreamEvent(event_type="empty_response", empty_response=True),
                    OpenHandsStreamEvent(event_type="empty_response", empty_response=True),
                    OpenHandsStreamEvent(
                        event_type="error",
                        message="worker_empty_response_loop: OpenHands emitted 2 empty assistant responses",
                        payload_json={"diagnostic_code": "worker_empty_response_loop"},
                        outcome="error",
                        terminal=True,
                    ),
                ],
                (),
            )
        return (
            [
                OpenHandsStreamEvent(event_type="progress", message="worker restarted", outcome="running"),
                OpenHandsStreamEvent(
                    event_type="complete",
                    message="Recovered on retry and completed the plan.",
                    outcome="success",
                    terminal=True,
                ),
            ],
            (),
        )

    monkeypatch.setattr("autoweave.local_runtime.LocalRuntime._collect_openhands_stream", fake_collect)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        runtime.runtime_config.retry_policy["max_attempts"] = 3
        runtime.runtime_config.retry_policy["backoff_seconds"] = 0
        example = runtime.run_example(dispatch=True)
        attempts = runtime.storage.workflow_repository.list_attempts_for_run(example.workflow_run_id)

    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"
    assert example.failure_reason is None
    assert example.stream_event_types == (
        "progress",
        "empty_response",
        "empty_response",
        "error",
        "progress",
        "complete",
    )
    assert [attempt.state.value for attempt in attempts] == ["orphaned", "succeeded"]


def test_local_runtime_refreshes_finished_conversation_before_marking_stale_running_task(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)
    original_get_conversation = OpenHandsAgentServerClient.get_conversation
    get_calls = {"count": 0}

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    def fake_wait_for_conversation(self, conversation_id: str, *, timeout_seconds: float, poll_interval_seconds: float = 1.0):
        response = original_get_conversation(self, conversation_id)
        return replace(
            response,
            response_json={
                **response.response_json,
                "execution_status": "running",
            },
        )

    def fake_get_conversation(self, conversation_id: str):
        response = original_get_conversation(self, conversation_id)
        get_calls["count"] += 1
        status = "running" if get_calls["count"] == 1 else "finished"
        return replace(
            response,
            response_json={
                **response.response_json,
                "execution_status": status,
            },
        )

    monkeypatch.setattr(OpenHandsAgentServerClient, "wait_for_conversation", fake_wait_for_conversation)
    monkeypatch.setattr(OpenHandsAgentServerClient, "get_conversation", fake_get_conversation)

    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)

    assert example.task_state == "completed"
    assert example.attempt_state == "succeeded"


def test_local_runtime_reuses_existing_canonical_graph_on_restart(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    with build_local_runtime(root=tmp_path, environ={}, transport=_recording_transport([])) as first_runtime:
        first_run_id = first_runtime.orchestration.state.graph.workflow_run.id

    with build_local_runtime(root=tmp_path, environ={}, transport=_recording_transport([])) as second_runtime:
        second_run_id = second_runtime.orchestration.state.graph.workflow_run.id

    assert first_run_id == second_run_id == "team_1.0_run"


def test_local_runtime_build_does_not_seed_canonical_run_without_execution(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    with build_local_runtime(root=tmp_path, environ={}, transport=_recording_transport([])) as runtime:
        assert runtime.orchestration.state.graph.workflow_run.id == "team_1.0_run"
        assert runtime.storage.workflow_repository.list_workflow_runs() == []


def test_local_runtime_can_boot_from_packaged_templates_without_materialized_project_files(
    tmp_path: Path, monkeypatch
) -> None:
    _prepare_template_only_root(tmp_path)
    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)

    with build_local_runtime(root=tmp_path, environ={}, transport=_recording_transport([])) as runtime:
        assert runtime.workflow_definition.entrypoint == "manager_plan"
        assert runtime.agent_definition("manager").role == "manager"
        assert runtime.storage.workflow_repository.list_workflow_runs() == []


def test_local_runtime_avoids_full_graph_resync_for_state_only_updates(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)
    repositories: list[_CountingWorkflowRepository] = []

    def counting_storage_wiring(settings: LocalEnvironmentSettings) -> LocalStorageWiring:
        bundle = _test_storage_wiring(settings)
        repository = _CountingWorkflowRepository(bundle.workflow_repository)
        repositories.append(repository)
        bundle.workflow_repository = repository
        bundle.context_service = InMemoryContextService(
            workflow_repository=repository,
            artifact_registry=bundle.artifact_registry,
            memory_store=bundle.memory_store,
        )
        return bundle

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", counting_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        example = runtime.run_example(dispatch=True)

    repository = repositories[0]
    assert example.attempt_state == "succeeded"
    assert repository.save_graph_calls == 1
    assert repository.save_runtime_state_calls >= 1
    assert repository.save_workflow_run_calls >= 1
    assert repository.save_task_calls >= 1


def test_local_runtime_suppresses_duplicate_dispatch(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        monkeypatch.setattr(runtime.storage.idempotency_store, "claim", lambda *args, **kwargs: False)
        example = runtime.run_example(dispatch=True)

    assert example.failure_reason == "duplicate_dispatch_suppressed"
    assert example.bootstrap_call is None
    assert example.task_state == "ready"
    assert example.attempt_state == "aborted"
    assert [call["path"] for call in calls] == ["/health"]


def test_local_runtime_blocks_when_dispatch_lease_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        monkeypatch.setattr(runtime.storage.lease_manager, "acquire", lambda *args, **kwargs: False)
        example = runtime.run_example(dispatch=True)

    assert example.failure_reason == "lease_unavailable"
    assert example.bootstrap_call is None
    assert example.task_state == "blocked"
    assert example.attempt_state == "aborted"
    assert [call["path"] for call in calls] == ["/health"]
