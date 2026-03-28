"""CLI entrypoint for AutoWeave."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import typer

from apps.cli.bootstrap import bootstrap_repository, migrate_repository, repository_root
from apps.cli.validation import ValidationResult, validate_repository
from autoweave.celery_queue import CeleryWorkflowDispatcher, create_autoweave_celery_app
from autoweave.local_runtime import build_local_runtime
from autoweave.monitoring import serve_dashboard
from autoweave.settings import LocalEnvironmentSettings

app = typer.Typer(help="AutoWeave terminal control plane.")


def _echo_validation_result(root_path: Path, result: ValidationResult) -> None:
    typer.echo("validation=ok" if result.ok else "validation=failed")
    for path in result.missing:
        typer.echo(f"missing={path.relative_to(root_path)}")
    for issue in result.invalid:
        typer.echo(f"invalid={issue}")
    for warning in result.warnings:
        typer.echo(f"warning={warning}")


def _echo_migration_result(root_path: Path, *, created: tuple[Path, ...], updated: tuple[Path, ...], dry_run: bool) -> None:
    action = "would_update" if dry_run else "updated"
    typer.echo(f"created={len(created)}")
    for path in created:
        typer.echo(f"created_path={path.relative_to(root_path)}")
    typer.echo(f"{action}={len(updated)}")
    for path in updated:
        typer.echo(f"{action}_path={path.relative_to(root_path)}")


def _resolve_celery_worker_pool(configured_pool: str | None) -> str:
    normalized = str(configured_pool or "").strip().lower()
    if normalized and normalized != "auto":
        return normalized
    return "solo" if sys.platform == "darwin" else "prefork"


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
        _echo_validation_result(root_path, result)
        raise typer.Exit(code=0)

    typer.echo("validation=failed")
    for path in result.missing:
        typer.echo(f"missing={path.relative_to(root_path)}")
    for issue in result.invalid:
        typer.echo(f"invalid={issue}")
    for warning in result.warnings:
        typer.echo(f"warning={warning}")
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


@app.command("migrate-project")
def migrate_project(
    root: Path | None = typer.Option(None, "--root", help="Project root to migrate"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show which packaged template-managed files would be refreshed"),
) -> None:
    """Refresh packaged AutoWeave project-managed files to the latest library templates."""
    root_path = repository_root(root)
    result = migrate_repository(root_path, dry_run=dry_run)
    _echo_migration_result(root_path, created=result.created, updated=result.updated, dry_run=dry_run)


@app.command("create-agent")
def create_agent(
    name: str = typer.Argument(..., help="Name of the new agent"),
    role: str | None = typer.Option(None, "--role", help="Template role to base this agent on (e.g., manager, backend, frontend, reviewer)"),
    root: Path | None = typer.Option(None, "--root", help="Repository root"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing agent files"),
) -> None:
    """Create a new agent bundle with soul, playbook, config, and skills."""
    from apps.cli.bootstrap import create_agent as create_agent_bundle
    root_path = repository_root(root)
    result = create_agent_bundle(root_path, name=name, role=role, overwrite=overwrite)
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
    queue: bool = typer.Option(False, "--queue", help="Enqueue workflow execution onto Celery instead of running inline"),
    max_steps: int = typer.Option(8, "--max-steps", min=1, help="Maximum runnable tasks to advance in one invocation"),
) -> None:
    """Run the current workflow from a user request instead of the fixed sample brief."""
    root_path = repository_root(root)
    repo_result = validate_repository(root_path)
    _echo_validation_result(root_path, repo_result)
    if queue:
        try:
            dispatcher = CeleryWorkflowDispatcher(root=root_path)
        except RuntimeError as exc:
            typer.echo(f"celery_error={exc}")
            raise typer.Exit(code=1)
        celery_health = dispatcher.worker_health()
        typer.echo(f"celery_health={celery_health}")
        if not celery_health.startswith("ok"):
            raise typer.Exit(code=1)
        receipt = dispatcher.enqueue_new_workflow(request=request, dispatch=dispatch, max_steps=max_steps)
        for line in receipt.summary_lines():
            typer.echo(line)
        if not repo_result.ok:
            raise typer.Exit(code=1)
        return
    with build_local_runtime(root=root_path) as runtime:
        report = runtime.run_workflow(request=request, dispatch=dispatch, max_steps=max_steps)

    for line in report.summary_lines():
        typer.echo(line)
    if dispatch and report.workflow_status == "failed" and not report.open_human_questions:
        raise typer.Exit(code=1)
    if not repo_result.ok:
        raise typer.Exit(code=1)


@app.command("worker")
def worker(
    root: Path | None = typer.Option(None, "--root", help="Project root that owns the Celery-backed AutoWeave queues"),
    concurrency: int = typer.Option(1, "--concurrency", min=1, help="Celery worker concurrency"),
    loglevel: str = typer.Option("info", "--loglevel", help="Celery worker log level"),
    queues: str | None = typer.Option(None, "--queues", help="Comma-separated queue names; defaults to project runtime config"),
    pool: str | None = typer.Option(None, "--pool", help="Celery worker pool; defaults to runtime config or a local-safe platform default"),
) -> None:
    """Run a real Celery worker for queued AutoWeave workflow execution."""
    root_path = repository_root(root)
    os.environ["AUTOWEAVE_PROJECT_ROOT"] = str(root_path)
    try:
        dispatcher = CeleryWorkflowDispatcher(root=root_path)
        celery_app = create_autoweave_celery_app(root=root_path)
    except RuntimeError as exc:
        typer.echo(f"celery_error={exc}")
        raise typer.Exit(code=1)
    queue_names = [item.strip() for item in (queues.split(",") if queues else dispatcher.queue_names) if item.strip()]
    configured_pool = pool or getattr(dispatcher.runtime_config, "celery_worker_pool", "auto")
    selected_pool = _resolve_celery_worker_pool(configured_pool)
    typer.echo(f"celery_queues={','.join(queue_names)}")
    typer.echo(f"celery_pool={selected_pool}")
    celery_app.worker_main(
        [
            "worker",
            "--loglevel",
            loglevel,
            "--pool",
            selected_pool,
            "--concurrency",
            str(concurrency),
            "--queues",
            ",".join(queue_names),
        ]
    )


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


@app.command("cleanup-local-state")
def cleanup_local_state(
    root: Path | None = typer.Option(None, "--root", help="Project root to clean"),
    workflow_run_id: list[str] | None = typer.Option(
        None,
        "--workflow-run-id",
        help="Specific workflow run ID to purge; repeat for multiple runs",
    ),
    all_runs: bool = typer.Option(
        False,
        "--all-runs",
        help="Purge every canonical workflow run instead of only stale demo runs",
    ),
    drop_generated: bool = typer.Option(
        True,
        "--drop-generated/--keep-generated",
        help="Delete local generated residue such as artifacts, workspaces, tmp, dist, and caches",
    ),
) -> None:
    """Purge stale canonical runs and local generated runtime residue."""

    root_path = repository_root(root)
    with build_local_runtime(root=root_path) as runtime:
        selected_run_ids = _select_cleanup_run_ids(
            runtime,
            workflow_run_ids=workflow_run_id or [],
            all_runs=all_runs,
        )
        report = runtime.purge_workflow_runs(
            selected_run_ids,
            clear_projection_namespace=all_runs and runtime.settings.autoweave_graph_backend == "neo4j",
        )
        runtime_settings = runtime.settings

    deleted_generated_paths = (
        _cleanup_generated_paths(root_path, runtime_settings, all_runs=all_runs) if drop_generated else ()
    )

    for line in report.summary_lines():
        typer.echo(line)
    typer.echo(f"deleted_generated_paths={len(deleted_generated_paths)}")
    for path in deleted_generated_paths:
        typer.echo(f"deleted_generated_path={path}")


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
AUTOWEAVE_CANONICAL_BACKEND=auto
AUTOWEAVE_GRAPH_BACKEND=auto
AUTOWEAVE_AUTONOMY_LEVEL=medium
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

# AutoWeave
.env.local
config/secrets/
var/
workspaces/
workspace/
tmp/
dist/
.pytest_cache/
""",
        encoding="utf-8",
    )
    typer.echo(f"Initialized git repository in {path}")

    typer.echo("\nProject setup complete. Next steps:")
    typer.echo("1. Fill in the placeholder values in .env.local")
    typer.echo(f"2. Copy your Vertex service-account JSON to {path / 'config/secrets/vertex_service_account.json'}")
    typer.echo(f"3. Run 'autoweave bootstrap --root {path}'")
    typer.echo(f"4. Run 'autoweave validate --root {path}'")


def _copy_file(source: Path, dest: Path) -> None:
    """Copy a file, creating the destination directory if it doesn't exist."""
    if not source.exists():
        raise FileNotFoundError(f"template file is missing: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, dest)
    typer.echo(f"Copied {source} to {dest}")


def _select_cleanup_run_ids(runtime, *, workflow_run_ids: list[str], all_runs: bool) -> tuple[str, ...]:
    if workflow_run_ids:
        return tuple(dict.fromkeys(run_id.strip() for run_id in workflow_run_ids if run_id and run_id.strip()))

    known_runs = runtime.storage.workflow_repository.list_workflow_runs()
    if all_runs:
        return tuple(run.id for run in known_runs)
    return tuple(
        run.id
        for run in known_runs
        if "_run_demo_" in run.id or run.id.endswith("_run_demo") or run.id == "team_1.0_run"
    )


def _cleanup_generated_paths(
    root: Path,
    settings: LocalEnvironmentSettings,
    *,
    all_runs: bool,
) -> tuple[Path, ...]:
    deleted_paths: list[Path] = []
    base_candidates = [
        root / ".DS_Store",
        root / ".pytest_cache",
        root / "dist",
        root / "tmp",
        root / "workspace",
    ]
    if all_runs:
        base_candidates.extend(
            [
                settings.artifact_store_path(),
                root / "workspaces",
                root / "var" / "observability",
                settings.state_dir(),
            ]
        )
    for candidate in base_candidates:
        _delete_path(candidate, deleted_paths)
    for candidate in sorted(root.rglob("__pycache__"), reverse=True):
        if ".venv" in candidate.parts:
            continue
        _delete_path(candidate, deleted_paths)
    return tuple(deleted_paths)


def _delete_path(path: Path, deleted_paths: list[Path]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    deleted_paths.append(path)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
