from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from apps.cli.bootstrap import AGENT_ROLES, bootstrap_repository
from apps.cli.main import app
from apps.cli.validation import validate_repository
from autoweave.config_models import RuntimeConfig
from autoweave.local_runtime import build_local_runtime
from autoweave.models import MemoryEntryRecord, MemoryLayer
from autoweave.templates import sample_project


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


def _write_local_runtime_env(root: Path) -> None:
    (root / "config" / "secrets").mkdir(parents=True, exist_ok=True)
    (root / "config" / "secrets" / "vertex_service_account.json").write_text("{}", encoding="utf-8")
    (root / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=demo-project",
                "VERTEXAI_LOCATION=global",
                "VERTEXAI_SERVICE_ACCOUNT_FILE=./config/secrets/vertex_service_account.json",
                "GOOGLE_APPLICATION_CREDENTIALS=./config/secrets/vertex_service_account.json",
                "POSTGRES_URL=postgresql://demo:demo@127.0.0.1:5432/autoweave",
                "REDIS_URL=redis://127.0.0.1:6379/0",
                "NEO4J_URL=neo4j://127.0.0.1:7687",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=secret",
                "ARTIFACT_STORE_URL=file://./var/artifacts",
                "OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8000",
                "AUTOWEAVE_CANONICAL_BACKEND=sqlite",
                "AUTOWEAVE_GRAPH_BACKEND=sqlite",
                "AUTOWEAVE_STATE_DIR=var/state",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_bootstrap_command_creates_sample_agents_and_configs(tmp_path: Path) -> None:
    result = runner.invoke(app, ["bootstrap", "--root", str(tmp_path)])

    assert result.exit_code == 0
    for role in AGENT_ROLES:
        assert (tmp_path / "agents" / role / "autoweave.yaml").exists()
        for skill_file in sample_project.AGENT_SKILL_FILES[role]:
            skill_path = tmp_path / "agents" / role / skill_file
            assert skill_path.exists()
            if skill_path.name != "README.md":
                skill_text = skill_path.read_text(encoding="utf-8")
                assert "## Do" in skill_text or "## When to use" in skill_text
    assert (tmp_path / "configs" / "workflows" / "team.workflow.yaml").exists()
    assert "created:" in result.stdout


def test_validate_repository_passes_for_bootstrapped_layout(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    result = validate_repository(tmp_path)

    assert result.ok
    assert not result.missing
    assert not result.invalid
    assert not result.warnings


def test_validate_repository_uses_packaged_defaults_when_agents_and_configs_are_missing(tmp_path: Path) -> None:
    _write_docs(tmp_path)

    result = validate_repository(tmp_path)

    assert result.ok
    assert not result.missing
    assert not result.invalid
    assert any("using packaged template defaults for agents/manager/autoweave.yaml" == warning for warning in result.warnings)
    assert any("using packaged template defaults for configs/workflows/team.workflow.yaml" == warning for warning in result.warnings)


def test_bootstrap_writes_role_specific_agent_metadata(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    manager_autoweave = yaml.safe_load((tmp_path / "agents" / "manager" / "autoweave.yaml").read_text(encoding="utf-8"))
    reviewer_autoweave = yaml.safe_load((tmp_path / "agents" / "reviewer" / "autoweave.yaml").read_text(encoding="utf-8"))
    manager_playbook = yaml.safe_load((tmp_path / "agents" / "manager" / "playbook.yaml").read_text(encoding="utf-8"))

    assert manager_autoweave["specialization"] == "workflow-decomposition"
    assert manager_autoweave["primary_skills"] == ["workflow_decomposition", "stakeholder_alignment"]
    assert reviewer_autoweave["specialization"] == "quality-and-release"
    assert "DAG task list" in manager_playbook["goals"][0]


def test_bootstrap_overwrite_refreshes_existing_sample_files(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    stale_path = tmp_path / "agents" / "manager" / "soul.md"
    stale_path.write_text("stale\n", encoding="utf-8")

    result = runner.invoke(app, ["bootstrap", "--root", str(tmp_path), "--overwrite"])

    assert result.exit_code == 0
    assert "updated:" in result.stdout
    assert "turns a user brief into a dependency-aware DAG" in stale_path.read_text(encoding="utf-8")


def test_validate_command_reports_invalid_workflow_entrypoint(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    workflow_path = tmp_path / "configs" / "workflows" / "team.workflow.yaml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    workflow["entrypoint"] = "not_a_real_task"
    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")

    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "validation=failed" in result.stdout
    assert "invalid=workflow entrypoint is not defined in task_templates" in result.stdout


def test_validate_command_detects_missing_docs(tmp_path: Path) -> None:
    bootstrap_repository(tmp_path)

    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "missing=docs/autoweave_high_level_architecture.md" in result.stdout
    assert "missing=docs/autoweave_implementation_spec.md" in result.stdout
    assert "missing=docs/autoweave_diagrams_source.md" in result.stdout


def test_validate_command_succeeds_with_packaged_defaults_when_project_files_are_not_materialized(tmp_path: Path) -> None:
    _write_docs(tmp_path)

    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "validation=ok" in result.stdout
    assert "warning=using packaged template defaults for agents/manager/autoweave.yaml" in result.stdout


def test_bootstrap_vertex_defaults_prefer_gemini_3_and_keep_legacy_profiles(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    vertex_config = yaml.safe_load((tmp_path / "configs" / "runtime" / "vertex.yaml").read_text(encoding="utf-8"))
    profiles = {profile["name"]: profile["model"] for profile in vertex_config["profile_definitions"]}

    assert profiles["planner"] == "gemini-3.1-pro-preview"
    assert profiles["balanced"] == "gemini-3-flash-preview"
    assert profiles["fast"] == "gemini-3-flash-preview"
    assert profiles["legacy_planner"] == "gemini-2.5-pro"
    assert profiles["legacy_fast"] == "gemini-2.5-flash"
    assert "gemini-3-pro-preview" not in {profiles["planner"], profiles["balanced"], profiles["fast"]}


def test_bootstrap_runtime_defaults_enable_celery_dispatch(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    runtime_config = yaml.safe_load((tmp_path / "configs" / "runtime" / "runtime.yaml").read_text(encoding="utf-8"))

    assert runtime_config["execution_backend"] == "celery"
    assert runtime_config["celery_queue_names"] == ["dispatch"]
    assert runtime_config["celery_result_expires_seconds"] == 3600


def test_module_entrypoint_invokes_main(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "apps.cli.main", "status", "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert f"root={tmp_path}" in result.stdout
    assert "ok=True" in result.stdout


def test_ui_command_prints_url_and_calls_dashboard_server(tmp_path: Path, monkeypatch) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    captured: dict[str, object] = {}

    def fake_serve_dashboard(*, root: Path, host: str, port: int, environ=None) -> None:
        captured["root"] = root
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("apps.cli.main.serve_dashboard", fake_serve_dashboard)

    result = runner.invoke(app, ["ui", "--root", str(tmp_path), "--host", "127.0.0.1", "--port", "9876"])

    assert result.exit_code == 0
    assert "ui_url=http://127.0.0.1:9876" in result.stdout
    assert captured == {"root": tmp_path, "host": "127.0.0.1", "port": 9876}


def test_new_project_does_not_copy_live_vertex_credentials(tmp_path: Path) -> None:
    repo_source = tmp_path / "repo-source"
    project_path = tmp_path / "new-project"
    _write_docs(repo_source)
    (repo_source / "config" / "secrets").mkdir(parents=True, exist_ok=True)
    (repo_source / "config" / "secrets" / "vertex_service_account.json").write_text(
        '{"type":"service_account"}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["new-project", str(project_path), "--repo-source", str(repo_source)])

    assert result.exit_code == 0
    assert (project_path / ".env.local").exists()
    assert not (project_path / "config" / "secrets" / "vertex_service_account.json").exists()
    assert "Copy your Vertex service-account JSON" in result.stdout
    env_text = (project_path / ".env.local").read_text(encoding="utf-8")
    assert "AUTOWEAVE_CANONICAL_BACKEND=auto" in env_text
    assert "AUTOWEAVE_GRAPH_BACKEND=auto" in env_text
    assert "AUTOWEAVE_AUTONOMY_LEVEL=medium" in env_text
    gitignore_text = (project_path / ".gitignore").read_text(encoding="utf-8")
    assert "workspaces/" in gitignore_text
    assert "dist/" in gitignore_text


def test_migrate_project_refreshes_packaged_template_managed_files(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    workflow_path = tmp_path / "configs" / "workflows" / "team.workflow.yaml"
    runtime_path = tmp_path / "configs" / "runtime" / "runtime.yaml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    for task in workflow["task_templates"]:
        if task["key"] == "review":
            task["approval_requirements"] = ["human_review"]
    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    runtime["execution_backend"] = "inline"
    runtime_path.write_text(yaml.safe_dump(runtime, sort_keys=False), encoding="utf-8")

    result = runner.invoke(app, ["migrate-project", "--root", str(tmp_path)])

    assert result.exit_code == 0
    migrated_workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    migrated_runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    review_task = next(task for task in migrated_workflow["task_templates"] if task["key"] == "review")
    assert review_task["approval_requirements"] == []
    assert migrated_runtime["execution_backend"] == "celery"
    assert migrated_runtime["celery_worker_pool"] == "auto"
    assert migrated_runtime["require_release_signoff"] is True
    assert "updated_path=configs/workflows/team.workflow.yaml" in result.stdout
    assert "updated_path=configs/runtime/runtime.yaml" in result.stdout


def test_run_workflow_queue_uses_celery_dispatcher(tmp_path: Path, monkeypatch) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    class _FakeReceipt:
        def summary_lines(self) -> list[str]:
            return [
                "workflow_run_id=queued_run",
                "dispatch_backend=celery",
                "celery_task_id=celery-123",
                "celery_queue=dispatch",
            ]

    class _FakeDispatcher:
        def __init__(self, *, root=None, environ=None):
            self.root = root
            self.environ = environ

        def worker_health(self) -> str:
            return "ok (workers=1; queues=dispatch)"

        def enqueue_new_workflow(self, *, request: str, dispatch: bool, max_steps: int):
            assert request == "Build a queued storefront"
            assert dispatch is True
            assert max_steps == 4
            return _FakeReceipt()

    monkeypatch.setattr("apps.cli.main.CeleryWorkflowDispatcher", _FakeDispatcher)

    result = runner.invoke(
        app,
        [
            "run-workflow",
            "--root",
            str(tmp_path),
            "--request",
            "Build a queued storefront",
            "--dispatch",
            "--queue",
            "--max-steps",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert "celery_health=ok (workers=1; queues=dispatch)" in result.stdout
    assert "workflow_run_id=queued_run" in result.stdout
    assert "celery_task_id=celery-123" in result.stdout


def test_worker_command_invokes_celery_worker_main(tmp_path: Path, monkeypatch) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    captured: dict[str, object] = {}

    class _FakeDispatcher:
        def __init__(self, *, root=None, environ=None):
            self.queue_names = ("dispatch",)
            self.runtime_config = RuntimeConfig(execution_backend="celery", celery_worker_pool="auto")

    class _FakeCeleryApp:
        def worker_main(self, argv: list[str]) -> None:
            captured["argv"] = argv

    monkeypatch.setattr("apps.cli.main.CeleryWorkflowDispatcher", _FakeDispatcher)
    monkeypatch.setattr("apps.cli.main.create_autoweave_celery_app", lambda root=None: _FakeCeleryApp())

    result = runner.invoke(app, ["worker", "--root", str(tmp_path), "--concurrency", "2", "--loglevel", "warning"])

    assert result.exit_code == 0
    assert "celery_queues=dispatch" in result.stdout
    assert f"celery_pool={'solo' if sys.platform == 'darwin' else 'prefork'}" in result.stdout
    assert captured["argv"] == [
        "worker",
        "--loglevel",
        "warning",
        "--pool",
        "solo" if sys.platform == "darwin" else "prefork",
        "--concurrency",
        "2",
        "--queues",
        "dispatch",
    ]


def test_cleanup_local_state_purges_runs_and_generated_paths(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)
    _write_local_runtime_env(tmp_path)

    with build_local_runtime(root=tmp_path) as runtime:
        report = runtime.run_workflow(request="cleanup demo run", dispatch=False)
        run_id = report.workflow_run_id
        workflow_run = runtime.storage.workflow_repository.list_workflow_runs()[0]
        first_task = runtime.storage.workflow_repository.list_tasks_for_run(run_id)[0]
        runtime.storage.workflow_repository.save_memory_entry(
            MemoryEntryRecord(
                project_id=workflow_run.project_id,
                scope_type="project",
                scope_id=workflow_run.project_id,
                memory_layer=MemoryLayer.SEMANTIC,
                content="cleanup stale project memo",
                metadata_json={
                    "workflow_run_id": run_id,
                    "task_id": first_task.id,
                },
            )
        )

    (tmp_path / "var" / "artifacts" / run_id / "extra").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspaces" / "attempt-orphaned").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dist").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pytest_cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "autoweave" / "__pycache__").mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["cleanup-local-state", "--root", str(tmp_path), "--all-runs"])

    assert result.exit_code == 0
    assert "purged_runs=1" in result.stdout
    assert run_id in result.stdout
    assert not (tmp_path / "var" / "artifacts").exists()
    assert not (tmp_path / "workspaces").exists()
    assert not (tmp_path / "tmp").exists()
    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert not (tmp_path / "autoweave" / "__pycache__").exists()

    with build_local_runtime(root=tmp_path) as runtime:
        remaining_runs = runtime.storage.workflow_repository.list_workflow_runs()
        assert remaining_runs == []
        assert runtime.storage.workflow_repository.list_memory_entries("project", workflow_run.project_id) == []


def test_create_agent_command_creates_agent_directory(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    result = runner.invoke(app, ["create-agent", "test_engineer", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "agents" / "test_engineer" / "soul.md").exists()
    assert (tmp_path / "agents" / "test_engineer" / "playbook.yaml").exists()
    assert (tmp_path / "agents" / "test_engineer" / "autoweave.yaml").exists()
    assert (tmp_path / "agents" / "test_engineer" / "skills" / "README.md").exists()
    assert "created:" in result.stdout
