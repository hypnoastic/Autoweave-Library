from __future__ import annotations

import json
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
from autoweave.settings import CANONICAL_VERTEX_CREDENTIALS, LocalEnvironmentSettings
from autoweave.storage.coordination import RedisClient, RedisIdempotencyStore, RedisLeaseManager
from autoweave.storage.durable import SQLiteWorkflowRepository
from autoweave.storage.wiring import LocalStorageWiring, RedisWireSpec, StorageConnectionTargets
from autoweave.workers.runtime import OpenHandsAgentServerClient


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
    assert "Use Stripe only and ship within the US." in resumed_prompt


def test_local_runtime_waits_for_approval_and_can_resume_after_resolution(tmp_path: Path, monkeypatch) -> None:
    _prepare_local_root(tmp_path)
    calls: list[dict[str, object]] = []
    transport = _recording_transport(calls)

    monkeypatch.setattr("autoweave.local_runtime.build_local_storage_wiring", _test_storage_wiring)
    with build_local_runtime(root=tmp_path, environ={}, transport=transport) as runtime:
        initial = runtime.run_workflow(
            request="Build a small clothing ecommerce site with frontend, backend, integration, and review.",
            dispatch=True,
            max_steps=8,
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

    assert initial.open_approval_reasons == ("Approval required before dispatch: human_review",)
    assert any(step.task_key == "review" and step.task_state == "waiting_for_approval" for step in initial.step_reports)
    assert updated_request.status.value == "approved"
    assert resumed.dispatched_task_keys == ("review",)
    assert resumed.step_reports[0].task_key == "review"
    assert resumed.step_reports[0].task_state == "completed"
    assert resumed.workflow_status == "completed"
    conversation_calls = [call for call in calls if call["path"] == "/api/conversations"]
    assert len(conversation_calls) == 6
    assert conversation_calls[-1]["body"]["agent"]["llm"]["model"] == "vertex_ai/gemini-3-flash-preview"


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

    assert example.task_state == "failed"
    assert example.attempt_state == "errored"
    assert example.stream_event_types == ("progress", "empty_response", "empty_response", "error")
    assert example.failure_reason is not None
    assert "worker_empty_response_loop" in example.failure_reason


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
