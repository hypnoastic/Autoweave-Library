from __future__ import annotations

import io
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from apps.cli.bootstrap import bootstrap_repository
from autoweave.local_runtime import LocalWorkflowRunReport
from autoweave.models import ArtifactRecord, ArtifactStatus, AttemptState, EventRecord, HumanRequestRecord, HumanRequestStatus, HumanRequestType, TaskAttemptRecord, TaskRecord, TaskState, WorkflowRunRecord, WorkflowRunStatus
from autoweave.monitoring.service import MonitoringService
from autoweave.monitoring.web import MonitoringDashboardApp


class _FakeArtifactStore:
    def read_manifest(self, artifact_id: str) -> dict[str, object]:
        if artifact_id == "artifact_plan":
            return {
                "payload": {
                    "plan": [
                        "backend_contract",
                        "frontend_ui",
                        "backend_impl",
                        "integration",
                        "review",
                    ]
                }
            }
        return {
            "payload": {
                "events": [
                    {
                        "kind": "MessageEvent",
                        "source": "agent",
                        "llm_message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Backend first, then frontend, then integration and review.",
                                }
                            ],
                        },
                    }
                ]
            }
        }


class _FakeRepository:
    def __init__(self, workflow_run: WorkflowRunRecord, task: TaskRecord, attempt: TaskAttemptRecord) -> None:
        self._workflow_run = workflow_run
        self._task = task
        self._attempt = attempt
        self._artifact = ArtifactRecord(
            id="artifact_plan",
            workflow_run_id=workflow_run.id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            produced_by_role="manager",
            artifact_type="workflow_plan",
            title="manager plan",
            summary="plan published",
            status=ArtifactStatus.FINAL,
            version=1,
            storage_uri="file:///tmp/manager-plan.json",
            checksum="",
        )
        self._replay_artifact = ArtifactRecord(
            workflow_run_id=workflow_run.id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            produced_by_role="manager",
            artifact_type="openhands_replay",
            title="manager replay",
            summary="conversation finished",
            status=ArtifactStatus.FINAL,
            version=1,
            storage_uri="file:///tmp/manager.json",
            checksum="",
        )
        self._event = EventRecord(
            workflow_run_id=workflow_run.id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            agent_role="manager",
            provider_name="VertexAI",
            model_name="gemini-3-flash-preview",
            route_reason="balanced",
            event_type="attempt.completed",
            source="orchestrator",
            payload_json={"message": "manager completed"},
            sequence_no=1,
        )
        self._human_request = HumanRequestRecord(
            workflow_run_id=workflow_run.id,
            task_id=task.id,
            task_attempt_id=attempt.id,
            request_type=HumanRequestType.CLARIFICATION,
            question="Which payment providers should be enabled?",
            context_summary="Checkout details missing",
            status=HumanRequestStatus.OPEN,
        )

    def list_workflow_runs(self) -> list[WorkflowRunRecord]:
        return [self._workflow_run]

    def list_tasks_for_run(self, workflow_run_id: str) -> list[TaskRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._task]

    def list_attempts_for_run(self, workflow_run_id: str) -> list[TaskAttemptRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._attempt]

    def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._human_request]

    def list_approval_requests_for_run(self, workflow_run_id: str) -> list[object]:
        assert workflow_run_id == self._workflow_run.id
        return []

    def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._artifact, self._replay_artifact]

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._event]


class _FakeRuntime:
    def __init__(self, root: Path, recorder: list[tuple[str, dict[str, object]]] | None = None) -> None:
        self._recorder = recorder if recorder is not None else []
        workflow_run = WorkflowRunRecord(
            id="run_demo_1",
            project_id="local",
            team_id="local",
            workflow_definition_id="team:1.0",
            root_input_json={"user_request": "Build a boutique storefront"},
            status=WorkflowRunStatus.RUNNING,
        )
        task = TaskRecord(
            id="task_manager",
            workflow_run_id=workflow_run.id,
            task_key="manager_plan",
            title="Manager plan",
            description="Plan the work.",
            assigned_role="manager",
            state=TaskState.WAITING_FOR_HUMAN,
            input_json={"user_request": "Build a boutique storefront"},
            output_json={
                "plan": [
                    "backend_contract",
                    "frontend_ui",
                    "backend_impl",
                    "integration",
                    "review",
                ]
            },
            produced_artifact_types_json=["workflow_plan"],
        )
        attempt = TaskAttemptRecord(
            id="attempt_manager",
            task_id=task.id,
            attempt_number=1,
            agent_definition_id="manager-agent",
            workspace_id="attempt_manager",
            compiled_worker_config_json={
                "workspace_path": "/workspace/workspaces/attempt_manager",
                "model_name": "gemini-3-flash-preview",
            },
        )
        self.settings = SimpleNamespace(project_root=root)
        self.workflow_definition = SimpleNamespace(
            name="team",
            version="1.0",
            entrypoint="manager_plan",
            roles=["manager", "backend", "frontend", "reviewer"],
            task_templates=[
                SimpleNamespace(
                    key="manager_plan",
                    title="Manager plan",
                    assigned_role="manager",
                    hard_dependencies=[],
                    soft_dependencies=[],
                    produced_artifacts=["workflow_plan"],
                    required_artifacts=[],
                )
            ],
        )
        self.storage = SimpleNamespace(
            workflow_repository=_FakeRepository(workflow_run, task, attempt),
            artifact_store=_FakeArtifactStore(),
        )

    def __enter__(self) -> "_FakeRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run_workflow(self, *, request: str, dispatch: bool, max_steps: int) -> LocalWorkflowRunReport:
        self._recorder.append(
            (
                "start",
                {"request": request, "dispatch": dispatch, "max_steps": max_steps},
            )
        )
        return LocalWorkflowRunReport(
            workflow_run_id="run_demo_2",
            request=request,
            workflow_status="running",
            dispatched_task_keys=("manager_plan",),
            ready_task_keys=("backend_contract", "frontend_ui"),
            open_human_questions=(),
            open_approval_reasons=(),
            step_reports=(),
        )

    def answer_human_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        answer_text: str,
        answered_by: str,
        dispatch: bool,
        max_steps: int,
    ) -> LocalWorkflowRunReport:
        self._recorder.append(
            (
                "answer_human",
                {
                    "workflow_run_id": workflow_run_id,
                    "request_id": request_id,
                    "answer_text": answer_text,
                    "answered_by": answered_by,
                    "dispatch": dispatch,
                    "max_steps": max_steps,
                },
            )
        )
        return LocalWorkflowRunReport(
            workflow_run_id=workflow_run_id,
            request=answer_text,
            workflow_status="running",
            dispatched_task_keys=("manager_plan",),
            ready_task_keys=("backend_contract",),
            open_human_questions=(),
            open_approval_reasons=(),
            step_reports=(),
        )

    def resolve_approval_request(
        self,
        *,
        workflow_run_id: str,
        request_id: str,
        approved: bool,
        resolved_by: str,
        dispatch: bool,
        max_steps: int,
    ) -> LocalWorkflowRunReport:
        self._recorder.append(
            (
                "resolve_approval",
                {
                    "workflow_run_id": workflow_run_id,
                    "request_id": request_id,
                    "approved": approved,
                    "resolved_by": resolved_by,
                    "dispatch": dispatch,
                    "max_steps": max_steps,
                },
            )
        )
        return LocalWorkflowRunReport(
            workflow_run_id=workflow_run_id,
            request="approval",
            workflow_status="running",
            dispatched_task_keys=("review",),
            ready_task_keys=(),
            open_human_questions=(),
            open_approval_reasons=(),
            step_reports=(),
        )


def _fake_runtime_factory(*, root=None, environ=None, transport=None, bootstrap_path="/api/conversations"):
    return _FakeRuntime(Path(root or "."))


def test_monitoring_service_snapshot_exposes_canonical_state(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)
    service = MonitoringService(root=tmp_path, runtime_factory=_fake_runtime_factory)

    payload = service.snapshot(limit=3)

    assert payload["project_root"] == str(tmp_path)
    assert payload["agents"][0]["role"] == "backend"
    assert "api_contracts.md" in payload["agents"][0]["skill_files"]
    assert payload["workflow_blueprint"]["entrypoint"] == "manager_plan"
    assert payload["runs"][0]["id"] == "run_demo_1"
    assert payload["runs"][0]["graph_revision"] == 1
    assert payload["runs"][0]["workflow_request"] == "Build a boutique storefront"
    assert payload["runs"][0]["operator_status"] == "waiting_for_human"
    assert payload["runs"][0]["operator_summary"] == "waiting on 1 human answer(s)"
    assert payload["runs"][0]["execution_status"] == "waiting_for_human"
    assert payload["runs"][0]["execution_summary"] == "no active worker; waiting on 1 human answer(s)"
    assert payload["runs"][0]["active_attempt_count"] == 0
    assert '"backend_contract"' in (payload["runs"][0]["manager_plan"] or "")
    assert "Backend first, then frontend" in (payload["runs"][0]["manager_summary"] or "")
    assert '"backend_contract"' in (payload["runs"][0]["manager_outcome"] or "")
    assert payload["runs"][0]["tasks"][0]["task_key"] == "manager_plan"
    assert payload["runs"][0]["tasks"][0]["latest_attempt_state"] == "queued"
    assert payload["runs"][0]["tasks"][0]["attempt_display_state"] == "awaiting_human"
    assert payload["runs"][0]["tasks"][0]["has_active_worker"] is False
    assert payload["runs"][0]["tasks"][0]["worker_status"] == "waiting_for_human"
    assert payload["runs"][0]["tasks"][0]["input_json"]["user_request"] == "Build a boutique storefront"
    assert payload["runs"][0]["run_steps"][0]["task_key"] == "manager_plan"
    assert payload["runs"][0]["human_requests"][0]["question"] == "Which payment providers should be enabled?"
    assert payload["runs"][0]["task_state_counts"]["waiting_for_human"] == 1
    assert payload["runs"][0]["attempt_state_counts"]["queued"] == 1


def test_monitoring_service_launches_background_workflow_job(tmp_path: Path) -> None:
    service = MonitoringService(root=tmp_path, runtime_factory=_fake_runtime_factory)

    job = service.launch_workflow(request="Build a storefront", dispatch=True, max_steps=4)

    for _ in range(50):
        jobs = service.jobs()
        current = next(item for item in jobs if item["id"] == job["id"])
        if current["status"] != "running":
            break
        time.sleep(0.01)

    assert current["status"] == "completed"
    assert current["workflow_run_id"] == "run_demo_2"
    assert "workflow_run_id=run_demo_2" in "\n".join(current["summary_lines"])


def test_monitoring_dashboard_wsgi_app_serves_state_and_launch(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)
    service = MonitoringService(root=tmp_path, runtime_factory=_fake_runtime_factory)
    app = MonitoringDashboardApp(service)
    client = httpx.Client(transport=httpx.WSGITransport(app=app), base_url="http://monitor.local")

    index = client.get("/")
    state = client.get("/api/state")
    launch = client.post("/api/run", json={"request": "Build a storefront", "max_steps": 3, "dispatch": True})

    assert index.status_code == 200
    assert "AutoWeave Operator Console" in index.text
    assert "Workflow Runs" in index.text
    assert "Tasks / DAG" in index.text
    assert "Observability / Events" in index.text
    assert "Settings / Config" in index.text
    assert "Active workers" in index.text
    assert state.status_code == 200
    assert state.json()["status"] == "ok"
    assert state.json()["selected_run_id"] == "run_demo_1"
    assert state.json()["runs"][0]["id"] == "run_demo_1"
    assert state.json()["runs"][0]["operator_status"] == "waiting_for_human"
    assert state.json()["runs"][0]["execution_status"] == "waiting_for_human"
    assert state.json()["agents"][0]["role"] == "backend"
    assert launch.status_code == 202
    assert launch.json()["status"] in {"queued", "running", "completed"}


def test_monitoring_service_snapshot_degrades_but_preserves_catalog(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)

    def failing_runtime_factory(**kwargs):
        raise RuntimeError("backend unavailable")

    service = MonitoringService(root=tmp_path, runtime_factory=failing_runtime_factory)

    payload = service.snapshot(limit=3)

    assert payload["status"] == "degraded"
    assert "backend unavailable" in str(payload["load_error"])
    assert payload["agents"][0]["role"] == "backend"
    assert payload["workflow_blueprint"]["entrypoint"] == "manager_plan"
    assert payload["runs"] == []


def test_monitoring_service_snapshot_returns_loading_until_background_refresh_finishes(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)

    class _SlowRuntime:
        def __enter__(self):
            time.sleep(0.5)
            self._runtime = _FakeRuntime(tmp_path)
            return self._runtime

        def __exit__(self, exc_type, exc, tb):
            return None

    service = MonitoringService(root=tmp_path, runtime_factory=lambda **kwargs: _SlowRuntime())

    started_at = time.monotonic()
    payload = service.snapshot(limit=3)
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.45
    assert payload["status"] == "loading"
    assert payload["refreshing"] is True
    assert payload["agents"] == []
    assert payload["runs"] == []

    for _ in range(50):
        payload = service.snapshot(limit=3)
        if payload["status"] == "ok":
            break
        time.sleep(0.02)

    assert payload["status"] == "ok"
    assert payload["runs"][0]["id"] == "run_demo_1"


def test_monitoring_service_snapshot_skips_runtime_for_clean_sqlite_state(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)

    def unexpected_runtime_factory(**kwargs):
        raise AssertionError("runtime should not be constructed for a clean local sqlite state")
    unexpected_runtime_factory.autoweave_skip_clean_sqlite = True

    service = MonitoringService(root=tmp_path, runtime_factory=unexpected_runtime_factory)

    payload = service.snapshot(limit=3)

    assert payload["status"] == "ok"
    assert payload["load_error"] is None
    assert payload["agents"][0]["role"] == "backend"
    assert payload["workflow_blueprint"]["entrypoint"] == "manager_plan"
    assert payload["runs"] == []


def test_monitoring_dashboard_wsgi_app_routes_chat_and_approval_actions(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)
    recorder: list[tuple[str, dict[str, object]]] = []

    def runtime_factory(*, root=None, environ=None, transport=None, bootstrap_path="/api/conversations", workflow_run_id=None):
        return _FakeRuntime(Path(root or "."), recorder=recorder)

    service = MonitoringService(root=tmp_path, runtime_factory=runtime_factory)
    app = MonitoringDashboardApp(service)
    client = httpx.Client(transport=httpx.WSGITransport(app=app), base_url="http://monitor.local")

    new_run = client.post("/api/chat", json={"message": "Build a storefront", "dispatch": True, "max_steps": 2})
    answer = client.post(
        "/api/chat",
        json={
            "message": "Use Stripe and US shipping only.",
            "workflow_run_id": "run_demo_1",
            "human_request_id": "human_request_1",
            "dispatch": True,
            "max_steps": 2,
        },
    )
    approval = client.post(
        "/api/approval",
        json={
            "workflow_run_id": "run_demo_1",
            "approval_request_id": "approval_request_1",
            "approved": True,
            "dispatch": True,
            "max_steps": 1,
        },
    )

    for _ in range(50):
        if len(service.jobs()) >= 3 and all(job["status"] != "running" for job in service.jobs()[:3]):
            break
        time.sleep(0.01)

    assert new_run.status_code == 202
    assert answer.status_code == 202
    assert approval.status_code == 202
    assert ("start", {"request": "Build a storefront", "dispatch": True, "max_steps": 2}) in recorder
    assert (
        "answer_human",
        {
            "workflow_run_id": "run_demo_1",
            "request_id": "human_request_1",
            "answer_text": "Use Stripe and US shipping only.",
            "answered_by": "operator",
            "dispatch": True,
            "max_steps": 2,
        },
    ) in recorder
    assert (
        "resolve_approval",
        {
            "workflow_run_id": "run_demo_1",
            "request_id": "approval_request_1",
            "approved": True,
            "resolved_by": "operator",
            "dispatch": True,
            "max_steps": 1,
        },
    ) in recorder


def test_monitoring_service_marks_blocked_runs_and_separates_manager_failure(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)
    workflow_run = WorkflowRunRecord(
        id="run_blocked_1",
        project_id="local",
        team_id="local",
        workflow_definition_id="team:1.0",
        root_input_json={"user_request": "Build a storefront"},
        status=WorkflowRunStatus.RUNNING,
    )
    task = TaskRecord(
        id="task_manager",
        workflow_run_id=workflow_run.id,
        task_key="manager_plan",
        title="Manager plan",
        description="Plan the work.",
        assigned_role="manager",
        state=TaskState.BLOCKED,
        block_reason="conversation poll timed out after 90.0s",
        input_json={"user_request": "Build a storefront"},
        produced_artifact_types_json=["workflow_plan"],
    )
    attempt = TaskAttemptRecord(
        id="attempt_manager",
        task_id=task.id,
        attempt_number=1,
        agent_definition_id="manager-agent",
        workspace_id="attempt_manager",
        state=AttemptState.ORPHANED,
        compiled_worker_config_json={
            "workspace_path": "/workspace/workspaces/attempt_manager",
            "model_name": "gemini-3-flash-preview",
        },
    )

    class _BlockedRepository(_FakeRepository):
        def __init__(self) -> None:
            super().__init__(workflow_run, task, attempt)

        def list_artifacts_for_run(self, workflow_run_id: str) -> list[ArtifactRecord]:
            assert workflow_run_id == self._workflow_run.id
            return [self._replay_artifact]

        def list_human_requests_for_run(self, workflow_run_id: str) -> list[HumanRequestRecord]:
            assert workflow_run_id == self._workflow_run.id
            return []

    class _BlockedRuntime(_FakeRuntime):
        def __init__(self, root: Path) -> None:
            self.settings = SimpleNamespace(project_root=root)
            self.workflow_definition = SimpleNamespace(
                name="team",
                version="1.0",
                entrypoint="manager_plan",
                roles=["manager"],
                task_templates=[
                    SimpleNamespace(
                        key="manager_plan",
                        title="Manager plan",
                        assigned_role="manager",
                        hard_dependencies=[],
                        soft_dependencies=[],
                        produced_artifacts=["workflow_plan"],
                        required_artifacts=[],
                    )
                ],
            )
            self.storage = SimpleNamespace(
                workflow_repository=_BlockedRepository(),
                artifact_store=_FakeArtifactStore(),
            )

        def __enter__(self) -> "_BlockedRuntime":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    service = MonitoringService(root=tmp_path, runtime_factory=lambda **kwargs: _BlockedRuntime(tmp_path))

    payload = service.snapshot(limit=3)

    run = payload["runs"][0]
    assert run["operator_status"] == "blocked"
    assert "blocked by manager_plan" == run["operator_summary"]
    assert run["execution_status"] == "blocked"
    assert run["execution_summary"] == "no active worker; blocked by manager_plan"
    assert run["manager_plan"] is None
    assert run["manager_outcome"] == "conversation poll timed out after 90.0s"
