"""Minimal PEP 517 backend for offline wheel builds.

This backend avoids a dependency on setuptools so the package can be built and
installed in constrained local environments without network access.
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
PROJECT = PYPROJECT["project"]
NAME = str(PROJECT["name"])
VERSION = str(PROJECT["version"])
DIST_INFO = f"{NAME.replace('-', '_')}-{VERSION}.dist-info"
WHEEL_NAME = f"{NAME.replace('-', '_')}-{VERSION}-py3-none-any.whl"


@dataclass(frozen=True)
class WheelFile:
    arcname: str
    data: bytes


def get_requires_for_build_wheel(config_settings=None):  # noqa: D401, ANN001
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):  # noqa: D401, ANN001
    metadata_dir = Path(metadata_directory) / DIST_INFO
    metadata_dir.mkdir(parents=True, exist_ok=True)
    _write_metadata_files(metadata_dir)
    return DIST_INFO


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):  # noqa: D401, ANN001
    wheel_path = Path(wheel_directory) / WHEEL_NAME
    files = _collect_wheel_files()

    record_lines: list[str] = []
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for wheel_file in files:
            archive.writestr(wheel_file.arcname, wheel_file.data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(wheel_file.data).digest()).decode("ascii").rstrip("=")
            record_lines.append(f"{wheel_file.arcname},sha256={digest},{len(wheel_file.data)}")

        record_name = f"{DIST_INFO}/RECORD"
        record_data = ("\n".join(record_lines + [f"{record_name},,"]) + "\n").encode("utf-8")
        archive.writestr(record_name, record_data)

    return wheel_path.name


def build_sdist(sdist_directory, config_settings=None):  # noqa: D401, ANN001
    sdist_path = Path(sdist_directory) / f"{NAME}-{VERSION}.tar.gz"
    with tempfile.TemporaryDirectory() as tmpdir:
        staging = Path(tmpdir) / f"{NAME}-{VERSION}"
        staging.mkdir(parents=True, exist_ok=True)
        for relative in ("autoweave", "apps", "configs", "agents", "docs"):
            source = ROOT / relative
            if source.exists():
                _copy_tree(source, staging / relative)
        for relative in ("pyproject.toml", "context.md", "AGENTS.md", "README.md", "build_backend.py"):
            source = ROOT / relative
            if source.exists():
                (staging / relative).write_bytes(source.read_bytes())
        import tarfile

        with tarfile.open(sdist_path, "w:gz") as archive:
            archive.add(staging, arcname=f"{NAME}-{VERSION}")
    return sdist_path.name


def _collect_wheel_files() -> list[WheelFile]:
    files: list[WheelFile] = []
    for package_root in ("autoweave", "apps"):
        root = ROOT / package_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            files.append(WheelFile(arcname=str(path.relative_to(ROOT)), data=path.read_bytes()))

    files.extend(
        [
            WheelFile(
                arcname=f"{DIST_INFO}/METADATA",
                data=_metadata_content().encode("utf-8"),
            ),
            WheelFile(
                arcname=f"{DIST_INFO}/WHEEL",
                data=(
                    "Wheel-Version: 1.0\n"
                    "Generator: build_backend\n"
                    "Root-Is-Purelib: true\n"
                    "Tag: py3-none-any\n"
                ).encode("utf-8"),
            ),
            WheelFile(
                arcname=f"{DIST_INFO}/entry_points.txt",
                data=b"[console_scripts]\nautoweave = apps.cli.main:main\n",
            ),
        ]
    )
    return files


def _metadata_content() -> str:
    lines = [
        "Metadata-Version: 2.3",
        f"Name: {NAME}",
        f"Version: {VERSION}",
        f"Summary: {PROJECT.get('description', '')}",
    ]
    requires_python = PROJECT.get("requires-python")
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")
    for requirement in PROJECT.get("dependencies", []):
        lines.append(f"Requires-Dist: {requirement}")
    return "\n".join(lines) + "\n"


def _write_metadata_files(metadata_dir: Path) -> None:
    (metadata_dir / "METADATA").write_text(_metadata_content(), encoding="utf-8")
    (metadata_dir / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: build_backend\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    (metadata_dir / "entry_points.txt").write_text(
        "[console_scripts]\nautoweave = apps.cli.main:main\n",
        encoding="utf-8",
    )


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
