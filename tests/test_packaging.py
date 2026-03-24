from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from venv import EnvBuilder


def _copy_docs(source_root: Path, target_root: Path) -> None:
    docs_src = source_root / "docs"
    docs_dst = target_root / "docs"
    docs_dst.mkdir(parents=True, exist_ok=True)
    for name in (
        "autoweave_high_level_architecture.md",
        "autoweave_implementation_spec.md",
        "autoweave_diagrams_source.md",
    ):
        shutil.copy2(docs_src / name, docs_dst / name)


def _copy_vertex_credentials(source_root: Path, target_root: Path) -> None:
    src = source_root / "config" / "secrets" / "vertex_service_account.json"
    dst = target_root / "config" / "secrets" / "vertex_service_account.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _make_venv(venv_dir: Path) -> Path:
    EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"


def test_packaged_fresh_install_demo(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "venv"
    fresh_project = tmp_path / "fresh-project"
    fresh_project.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(dist_dir),
            str(repo_root),
        ],
        check=True,
    )

    wheel = next(dist_dir.glob("autoweave-*.whl"))
    python = _make_venv(venv_dir)
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True)

    _copy_docs(repo_root, fresh_project)
    _copy_vertex_credentials(repo_root, fresh_project)

    helper = fresh_project / "demo_helper.py"
    helper.write_text(
        textwrap.dedent(
            """
            import json
            import pathlib
            import sys
            from dataclasses import dataclass

            import httpx
            from typer.testing import CliRunner

            from autoweave.templates import sample_project
            from apps.cli import main as cli_main

            root = pathlib.Path(sys.argv[1])
            calls = []

            def handler(request: httpx.Request) -> httpx.Response:
                body = {}
                if request.content:
                    body = json.loads(request.content.decode("utf-8"))
                calls.append({"method": request.method, "path": request.url.path, "body": body})
                if request.url.path == "/health":
                    return httpx.Response(200, json={"status": "ok"})
                if request.url.path == "/api/conversations":
                    return httpx.Response(200, json={"id": "conversation-local", "status": "ok"})
                return httpx.Response(404, json={"error": "not found"})

            mock_transport = httpx.MockTransport(handler)

            @dataclass
            class FakeReport:
                label: str

                def summary_lines(self):
                    return [f"{self.label}=ok"]

            @dataclass
            class FakeServiceCall:
                ok: bool = True

                error: str | None = None

            @dataclass
            class FakeExampleReport:
                bootstrap_call: FakeServiceCall | None
                attempt_state: str = "succeeded"

                def summary_lines(self):
                    return ["bootstrap_call=ok"]

            class FakeRuntime:
                def __init__(self, transport, bootstrap_path):
                    self.transport = transport or mock_transport
                    self.bootstrap_path = bootstrap_path

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def doctor(self):
                    with httpx.Client(transport=self.transport, base_url="http://127.0.0.1:8000") as client:
                        client.get("/health")
                    return FakeReport("openhands_health")

                def run_example(self, dispatch=False):
                    if dispatch:
                        with httpx.Client(transport=self.transport, base_url="http://127.0.0.1:8000") as client:
                            client.post(self.bootstrap_path, json={"task": "demo"})
                    return FakeExampleReport(bootstrap_call=FakeServiceCall())

            def fake_build_local_runtime(*, root=None, environ=None, transport=None, bootstrap_path="/api/conversations"):
                return FakeRuntime(transport, bootstrap_path)

            cli_main.build_local_runtime = fake_build_local_runtime
            cli_main.serve_dashboard = lambda **kwargs: None

            runner = CliRunner()
            env = {
                "VERTEXAI_PROJECT": "packaged-demo",
                "VERTEXAI_LOCATION": "global",
                "VERTEXAI_SERVICE_ACCOUNT_FILE": "./config/secrets/vertex_service_account.json",
                "GOOGLE_APPLICATION_CREDENTIALS": "./config/secrets/vertex_service_account.json",
                "POSTGRES_URL": "postgresql://user:secret@db.example.com/autoweave",
                "REDIS_URL": "redis://127.0.0.1:6379/0",
                "NEO4J_URL": "neo4j+s://demo.databases.neo4j.io",
                "NEO4J_USERNAME": "neo4j",
                "NEO4J_PASSWORD": "secret",
                "ARTIFACT_STORE_URL": "file://./var/artifacts",
                "OPENHANDS_AGENT_SERVER_BASE_URL": "http://127.0.0.1:8000",
                "OPENHANDS_WORKER_TIMEOUT_SECONDS": "30",
            }

            bootstrap = runner.invoke(cli_main.app, ["bootstrap", "--root", str(root)], env=env)
            validate = runner.invoke(cli_main.app, ["validate", "--root", str(root)], env=env)
            doctor = runner.invoke(cli_main.app, ["doctor", "--root", str(root)], env=env)
            run_example = runner.invoke(cli_main.app, ["run-example", "--root", str(root), "--dispatch"], env=env)
            ui = runner.invoke(cli_main.app, ["ui", "--root", str(root), "--port", "8765"], env=env)

            manager_skill = root / "agents" / "manager" / "skills" / "workflow_decomposition.md"
            reviewer_skill = root / "agents" / "reviewer" / "skills" / "qa_validation.md"

            assert bootstrap.exit_code == 0, bootstrap.output
            assert validate.exit_code == 0, validate.output
            assert doctor.exit_code == 0, doctor.output
            assert run_example.exit_code == 0, run_example.output
            assert ui.exit_code == 0, ui.output
            assert "created:" in bootstrap.output
            assert "validation=ok" in validate.output
            assert "openhands_health=ok" in doctor.output
            assert "bootstrap_call=ok" in run_example.output
            assert "ui_url=http://127.0.0.1:8765" in ui.output
            assert manager_skill.exists()
            assert reviewer_skill.exists()
            assert "## Do" in manager_skill.read_text(encoding="utf-8")
            assert "## Do" in reviewer_skill.read_text(encoding="utf-8")
            assert sample_project.AGENT_ROLES == ("manager", "backend", "frontend", "reviewer")
            assert sample_project.WORKFLOW_FILE.as_posix() == "configs/workflows/team.workflow.yaml"
            assert any(call["path"] == "/api/conversations" for call in calls)
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update({"PYTHONPATH": ""})
    subprocess.run(
        [str(python), str(helper), str(fresh_project)],
        check=True,
        capture_output=True,
        text=True,
        cwd=fresh_project,
        env=env,
    )
