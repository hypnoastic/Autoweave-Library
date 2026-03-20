from __future__ import annotations

from pathlib import Path

from autoweave.settings import (
    CANONICAL_VERTEX_CREDENTIALS,
    DEFAULT_ARTIFACT_DIR,
    LocalEnvironmentSettings,
    find_project_root,
    redact_connection_url,
)


def _seed_repo(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "autoweave_high_level_architecture.md").write_text("# arch\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='autoweave'\nversion='0.0.0'\n", encoding="utf-8")


def test_find_project_root_walks_up_from_nested_path(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    nested = tmp_path / "autoweave" / "workers"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == tmp_path.resolve()


def test_settings_prefer_env_local_and_normalize_vertex_paths(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=from-dot-env",
                "VERTEXAI_LOCATION=us-central1",
                "POSTGRES_URL=postgresql://base.example/db",
                "REDIS_URL=redis://127.0.0.1:6380/2",
                "NEO4J_URL=neo4j+s://base.databases.neo4j.io",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=from-dot-env-local",
                "OPENHANDS_AGENT_SERVER_BASE_URL=http://127.0.0.1:8010",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")

    settings = LocalEnvironmentSettings.load(root=tmp_path)

    assert settings.vertexai_project == "from-dot-env-local"
    assert settings.vertexai_location == "us-central1"
    assert settings.vertex_service_account_file == (tmp_path / CANONICAL_VERTEX_CREDENTIALS).resolve()
    assert settings.google_application_credentials == (tmp_path / CANONICAL_VERTEX_CREDENTIALS).resolve()
    assert settings.loaded_env_files == (tmp_path / ".env", tmp_path / ".env.local")
    assert settings.openhands_agent_server_base_url == "http://127.0.0.1:8010"


def test_settings_default_local_paths_and_worker_environment(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=demo-project",
                "VERTEXAI_LOCATION=us-central1",
                "POSTGRES_URL=postgresql://user@host/db",
                "NEO4J_URL=neo4j+s://demo.databases.neo4j.io",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")

    settings = LocalEnvironmentSettings.load(root=tmp_path)
    settings.ensure_local_layout()

    worker_env = settings.worker_environment()
    assert worker_env["GOOGLE_APPLICATION_CREDENTIALS"] == str((tmp_path / CANONICAL_VERTEX_CREDENTIALS).resolve())
    assert settings.artifact_store_path() == (tmp_path / DEFAULT_ARTIFACT_DIR).resolve()
    assert (tmp_path / DEFAULT_ARTIFACT_DIR).exists()
    assert (tmp_path / "workspaces").exists()
    assert settings.redis_target().host == "127.0.0.1"
    assert settings.neo4j_target().uses_aura is True
    assert settings.postgres_target().host == "host"


def test_settings_resolve_file_dot_artifact_store_relative_to_repo(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=demo-project",
                "VERTEXAI_LOCATION=us-central1",
                "POSTGRES_URL=postgresql://user@host/db",
                "NEO4J_URL=neo4j+s://demo.databases.neo4j.io",
                "ARTIFACT_STORE_URL=file://./var/artifacts",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")

    settings = LocalEnvironmentSettings.load(root=tmp_path)

    assert settings.artifact_store_path() == (tmp_path / "var" / "artifacts").resolve()


def test_connection_targets_redact_embedded_credentials(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "VERTEXAI_PROJECT=demo-project",
                "VERTEXAI_LOCATION=us-central1",
                "POSTGRES_URL=postgresql://user:super-secret@host/db?sslmode=require",
                "REDIS_URL=redis://:redis-secret@127.0.0.1:6379/0",
                "NEO4J_URL=neo4j+s://demo.databases.neo4j.io",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=neo4j-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")

    settings = LocalEnvironmentSettings.load(root=tmp_path)
    postgres = settings.postgres_target().redacted_dump()
    redis = settings.redis_target().redacted_dump()
    neo4j = settings.neo4j_target().redacted_dump()

    assert postgres["url"] == "postgresql://user:***@host/db?sslmode=require"
    assert redis["url"] == "redis://***@127.0.0.1:6379/0"
    assert neo4j["password"] == "***"
    assert redact_connection_url("https://example.com/path") == "https://example.com/path"
