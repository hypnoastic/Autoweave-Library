from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from apps.cli.bootstrap import AGENT_ROLES, bootstrap_repository
from apps.cli.main import app
from apps.cli.validation import validate_repository


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
    assert (tmp_path / "configs" / "workflows" / "team.workflow.yaml").exists()
    assert "created:" in result.stdout


def test_validate_repository_passes_for_bootstrapped_layout(tmp_path: Path) -> None:
    _write_docs(tmp_path)
    bootstrap_repository(tmp_path)

    result = validate_repository(tmp_path)

    assert result.ok
    assert not result.missing
    assert not result.invalid


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
