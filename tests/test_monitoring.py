from __future__ import annotations

import io
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from apps.cli.bootstrap import bootstrap_repository
from autoweave.local_runtime import LocalWorkflowRunReport
from autoweave.models import ArtifactRecord, ArtifactStatus, EventRecord, HumanRequestRecord, HumanRequestStatus, HumanRequestType, TaskAttemptRecord, TaskRecord, TaskState, WorkflowRunRecord, WorkflowRunStatus
from autoweave.monitoring.service import MonitoringService
from autoweave.monitoring.web import MonitoringDashboardApp


class _FakeArtifactStore:
    def read_manifest(self, artifact_id: str) -> dict[str, object]:
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
        return [self._artifact]

    def list_events(self, workflow_run_id: str) -> list[EventRecord]:
        assert workflow_run_id == self._workflow_run.id
        return [self._event]


class _FakeRuntime:
    def __init__(self, root: Path) -> None:
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
    assert payload["runs"][0]["manager_plan"].startswith("{")
    assert payload["runs"][0]["tasks"][0]["task_key"] == "manager_plan"
    assert payload["runs"][0]["tasks"][0]["latest_attempt_state"] == "queued"
    assert payload["runs"][0]["tasks"][0]["input_json"]["user_request"] == "Build a boutique storefront"
    assert payload["runs"][0]["run_steps"][0]["task_key"] == "manager_plan"
    assert payload["runs"][0]["human_requests"][0]["question"] == "Which payment providers should be enabled?"
    assert "Backend first, then frontend" in (payload["runs"][0]["manager_summary"] or "")


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
    assert "AutoWeave Monitor" in index.text
    assert "Prompt the manager entrypoint" in index.text
    assert state.status_code == 200
    assert state.json()["runs"][0]["id"] == "run_demo_1"
    assert state.json()["agents"][0]["role"] == "backend"
    assert launch.status_code == 202
    assert launch.json()["status"] in {"queued", "running", "completed"}
