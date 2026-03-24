"""Bootstrap helpers for the AutoWeave repository layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autoweave.templates import sample_project

DOC_FILES = (
    Path("docs/autoweave_high_level_architecture.md"),
    Path("docs/autoweave_implementation_spec.md"),
    Path("docs/autoweave_diagrams_source.md"),
)

AGENT_ROLES = sample_project.AGENT_ROLES
AGENT_FILES = sample_project.AGENT_FILES
RUNTIME_FILES = sample_project.RUNTIME_FILES
WORKFLOW_FILE = sample_project.WORKFLOW_FILE
ROUTING_FILE = sample_project.ROUTING_FILE


@dataclass(frozen=True)
class BootstrapResult:
    created: tuple[Path, ...]
    updated: tuple[Path, ...] = ()


def repository_root(root: Path | None = None) -> Path:
    return (Path.cwd() if root is None else root).resolve()


def expected_repository_files(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = list(DOC_FILES) + [WORKFLOW_FILE, ROUTING_FILE, *RUNTIME_FILES]
    for role in AGENT_ROLES:
        role_dir = Path("agents") / role
        paths.extend(role_dir / filename for filename in AGENT_FILES)
        paths.extend(role_dir / skill_file for skill_file in sample_project.AGENT_SKILL_FILES.get(role, ()))
    return tuple(root / relative for relative in paths)


def bootstrap_repository(root: Path, *, overwrite: bool = False) -> BootstrapResult:
    created: list[Path] = []
    updated: list[Path] = []

    for role in AGENT_ROLES:
        role_created, role_updated = _write_agent_bundle(root, role, overwrite=overwrite)
        created.extend(role_created)
        updated.extend(role_updated)

    bundle_created, bundle_updated = _write_text_file(
        root / WORKFLOW_FILE,
        sample_project.render_workflow_yaml(),
        overwrite=overwrite,
    )
    created.extend(bundle_created)
    updated.extend(bundle_updated)
    bundle_created, bundle_updated = _write_text_file(
        root / ROUTING_FILE,
        sample_project.render_model_profiles_yaml(),
        overwrite=overwrite,
    )
    created.extend(bundle_created)
    updated.extend(bundle_updated)
    for path, content in sample_project.render_runtime_files().items():
        bundle_created, bundle_updated = _write_text_file(root / path, content, overwrite=overwrite)
        created.extend(bundle_created)
        updated.extend(bundle_updated)

    return BootstrapResult(created=tuple(created), updated=tuple(updated))


def _write_agent_bundle(root: Path, role: str, *, overwrite: bool) -> tuple[list[Path], list[Path]]:
    role_dir = root / "agents" / role
    files = {
        role_dir / "soul.md": sample_project.render_agent_soul(role),
        role_dir / "playbook.yaml": sample_project.render_agent_playbook(role),
        role_dir / "autoweave.yaml": sample_project.render_agent_autoweave(role),
    }
    for relative_path, content in sample_project.render_agent_skill_files(role).items():
        files[role_dir / relative_path] = content
    created: list[Path] = []
    updated: list[Path] = []
    for path, content in files.items():
        file_created, file_updated = _write_text_file(path, content, overwrite=overwrite)
        created.extend(file_created)
        updated.extend(file_updated)
    return created, updated


def _write_text_file(path: Path, content: str, *, overwrite: bool) -> tuple[list[Path], list[Path]]:
    if path.exists() and not overwrite:
        return [], []
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    if existed:
        return [], [path]
    return [path], []
