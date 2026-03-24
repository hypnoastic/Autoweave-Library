"""CLI entrypoint for AutoWeave."""

from __future__ import annotations

from pathlib import Path


import shutil
import subprocess
import typer

from apps.cli.bootstrap import bootstrap_repository, repository_root
from apps.cli.validation import ValidationResult, validate_repository
from autoweave.local_runtime import build_local_runtime
from autoweave.monitoring import serve_dashboard

app = typer.Typer(help="AutoWeave terminal control plane.")


def _echo_validation_result(root_path: Path, result: ValidationResult) -> None:
    typer.echo("validation=ok" if result.ok else "validation=failed")
    for path in result.missing:
        typer.echo(f"missing={path.relative_to(root_path)}")
    for issue in result.invalid:
        typer.echo(f"invalid={issue}")


@app.command("status")
def status(root: Path | None = typer.Option(None, "--root", help="Repository root to inspect")) -> None:
    """Show a minimal repository status summary."""
    root_path = repository_root(root)
    result = validate_repository(root_path)
    typer.echo(f"root={root_path}")
    typer.echo(f"ok={result.ok}")
    typer.echo(f"missing={len(result.missing)}")
    typer.echo(f"invalid={len(result.invalid)}")


@app.command("validate")
def validate(root: Path | None = typer.Option(None, "--root", help="Repository root to inspect")) -> None:
    """Validate docs, configs, and sample agent fixtures."""
    root_path = repository_root(root)
    result = validate_repository(root_path)
    if result.ok:
        typer.echo("validation=ok")
        raise typer.Exit(code=0)

    typer.echo("validation=failed")
    for path in result.missing:
        typer.echo(f"missing={path.relative_to(root_path)}")
    for issue in result.invalid:
        typer.echo(f"invalid={issue}")
    raise typer.Exit(code=1)


@app.command("bootstrap")
def bootstrap(
    root: Path | None = typer.Option(None, "--root", help="Repository root to bootstrap"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite the sample project files from packaged templates"),
) -> None:
    """Create missing sample agents and config fixtures."""
    root_path = repository_root(root)
    result = bootstrap_repository(root_path, overwrite=overwrite)
    if result.created:
        typer.echo("created:")
        for path in result.created:
            typer.echo(f"- {path.relative_to(root_path)}")
    else:
        typer.echo("created=0")
    if result.updated:
        typer.echo("updated:")
        for path in result.updated:
            typer.echo(f"- {path.relative_to(root_path)}")


@app.command("doctor")
def doctor(root: Path | None = typer.Option(None, "--root", help="Repository root to inspect")) -> None:
    """Inspect local env, configs, and the OpenHands bootstrap path."""
    root_path = repository_root(root)
    repo_result = validate_repository(root_path)
    _echo_validation_result(root_path, repo_result)
    with build_local_runtime(root=root_path) as runtime:
        report = runtime.doctor()

    for line in report.summary_lines():
        typer.echo(line)
    if not repo_result.ok:
        raise typer.Exit(code=1)


@app.command("run-example")
def run_example(
    root: Path | None = typer.Option(None, "--root", help="Repository root to inspect"),
    dispatch: bool = typer.Option(False, "--dispatch/--dry-run", help="Send the example bootstrap request to OpenHands"),
) -> None:
    """Run the notifications example against the composed local runtime."""
    root_path = repository_root(root)
    repo_result = validate_repository(root_path)
    _echo_validation_result(root_path, repo_result)
    with build_local_runtime(root=root_path) as runtime:
        report = runtime.run_example(dispatch=dispatch)

    for line in report.summary_lines():
        typer.echo(line)
    if dispatch and report.bootstrap_call is not None and not report.bootstrap_call.ok:
        raise typer.Exit(code=1)
    if dispatch and report.attempt_state not in {"succeeded", "paused", "needs_input"}:
        raise typer.Exit(code=1)
    if not repo_result.ok:
        raise typer.Exit(code=1)


@app.command("run-workflow")
def run_workflow(
    root: Path | None = typer.Option(None, "--root", help="Repository root to inspect"),
    request: str = typer.Option(..., "--request", help="User request to seed into the workflow entrypoint"),
    dispatch: bool = typer.Option(False, "--dispatch/--dry-run", help="Dispatch runnable tasks to OpenHands"),
    max_steps: int = typer.Option(8, "--max-steps", min=1, help="Maximum runnable tasks to advance in one invocation"),
) -> None:
    """Run the current workflow from a user request instead of the fixed sample brief."""
    root_path = repository_root(root)
    repo_result = validate_repository(root_path)
    _echo_validation_result(root_path, repo_result)
    with build_local_runtime(root=root_path) as runtime:
        report = runtime.run_workflow(request=request, dispatch=dispatch, max_steps=max_steps)

    for line in report.summary_lines():
        typer.echo(line)
    if dispatch and report.workflow_status == "failed" and not report.open_human_questions:
        raise typer.Exit(code=1)
    if not repo_result.ok:
        raise typer.Exit(code=1)


@app.command("ui")
def ui(
    root: Path | None = typer.Option(None, "--root", help="Project root to monitor"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the local monitoring UI to"),
    port: int = typer.Option(8765, "--port", min=1, max=65535, help="Port for the local monitoring UI"),
) -> None:
    """Launch the lightweight local monitoring UI."""
    root_path = repository_root(root)
    repo_result = validate_repository(root_path)
    _echo_validation_result(root_path, repo_result)
    typer.echo(f"ui_url=http://{host}:{port}")
    if not repo_result.ok:
        raise typer.Exit(code=1)
    serve_dashboard(root=root_path, host=host, port=port)


@app.command("new-project")
def new_project(
    path: Path = typer.Argument(..., help="Directory to initialize the new project in"),
    repo_source: Path = typer.Option(
        None, "--repo-source", help="Path to an AutoWeave repo to use as a template"
    ),
) -> None:
    """Initialize a new AutoWeave project."""
    if repo_source is None:
        repo_source = Path.cwd()

    if not path.exists():
        path.mkdir(parents=True)
        typer.echo(f"Created project directory: {path}")

    # Create directories
    for subdir in ["docs", "config/secrets"]:
        (path / subdir).mkdir(parents=True, exist_ok=True)

    # Copy files
    files_to_copy = [
        "docs/autoweave_high_level_architecture.md",
        "docs/autoweave_implementation_spec.md",
        "docs/autoweave_diagrams_source.md",
        "config/secrets/vertex_service_account.json",
    ]
    for file in files_to_copy:
        _copy_file(repo_source / file, path / file)

    # Create .env.local
    (path / ".env.local").write_text(
        """VERTEXAI_PROJECT=
VERTEXAI_LOCATION=global
VERTEXAI_SERVICE_ACCOUNT_FILE=./config/secrets/vertex_service_account.json
GOOGLE_APPLICATION_CREDENTIALS=./config/secrets/vertex_service_account.json
POSTGRES_URL=
REDIS_URL=redis://127.0.0.1:6379/0
NEO4J_URL=
NEO4J_USERNAME=
NEO4J_PASSWORD=
ARTIFACT_STORE_URL=file://./var/artifacts
OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8000
AUTOWEAVE_VERTEX_PROFILE_OVERRIDE=
""",
        encoding="utf-8",
    )
    typer.echo(f"Created .env.local in {path}")

    # Initialize git
    subprocess.run(["git", "init"], cwd=path, check=True)
    (path / ".gitignore").write_text(
        """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/

# Docker
.dockerignore
docker-compose.yml

# AutoWeave
.env.local
config/secrets/
var/
""",
        encoding="utf-8",
    )
    typer.echo(f"Initialized git repository in {path}")

    typer.echo("\nProject setup complete. Next steps:")
    typer.echo("1. Fill in the placeholder values in .env.local")
    typer.echo(f"2. Run 'autoweave bootstrap --root {path}'")
    typer.echo(f"3. Run 'autoweave validate --root {path}'")


def _copy_file(source: Path, dest: Path) -> None:
    """Copy a file, creating the destination directory if it doesn't exist."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, dest)
    typer.echo(f"Copied {source} to {dest}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
