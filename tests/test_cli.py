from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from apps.cli.bootstrap import AGENT_ROLES, bootstrap_repository
from apps.cli.main import app
from apps.cli.validation import validate_repository
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
