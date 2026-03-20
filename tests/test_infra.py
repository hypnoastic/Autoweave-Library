from __future__ import annotations

from pathlib import Path

import yaml

from autoweave.settings import LocalEnvironmentSettings


def test_compose_contains_required_local_services() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    openhands_command = services["openhands-agent-server"]["command"]
    runtime_command = services["autoweave-runtime"]["command"]

    assert set(services) == {"redis", "artifact-store", "openhands-agent-server", "autoweave-runtime"}
    assert services["redis"]["image"] == "redis:7.4-alpine"
    assert services["redis"]["ports"] == ["6379:6379"]
    assert services["artifact-store"]["volumes"] == ["./var/artifacts:/data"]
    assert services["autoweave-runtime"]["build"]["dockerfile"] == "Dockerfile"
    assert services["autoweave-runtime"]["image"] == "autoweave-runtime:local"
    assert services["autoweave-runtime"]["depends_on"]["openhands-agent-server"]["condition"] == "service_healthy"
    assert runtime_command == ["sh", "-lc", "sleep infinity"]
    assert services["openhands-agent-server"]["image"] == "ghcr.io/openhands/agent-server:latest-python"
    assert services["openhands-agent-server"]["ports"] == ["8000:8000"]
    assert openhands_command == ["--host", "0.0.0.0", "--port", "8000"]


def test_compose_env_names_align_with_local_settings_contract() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["openhands-agent-server"]
    runtime_service = compose["services"]["autoweave-runtime"]
    env = service["environment"]
    env_files = service["env_file"]
    runtime_env = runtime_service["environment"]

    assert env_files == [
        {"path": ".env", "required": False},
        {"path": ".env.local", "required": False},
    ]
    assert env["VERTEXAI_SERVICE_ACCOUNT_FILE"] == "./config/secrets/vertex_service_account.json"
    assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "./config/secrets/vertex_service_account.json"
    assert env["REDIS_URL"] == "redis://redis:6379/0"
    assert env["ARTIFACT_STORE_URL"] == "file:///data"
    assert env["OPENHANDS_AGENT_SERVER_BASE_URL"] == "http://127.0.0.1:8000"
    assert runtime_env["OPENHANDS_AGENT_SERVER_BASE_URL"] == "http://openhands-agent-server:8000"
    assert runtime_env["AUTOWEAVE_RUNTIME_ROOT"] == "/workspace"
    assert runtime_env["VERTEXAI_SERVICE_ACCOUNT_FILE"] == "./config/secrets/vertex_service_account.json"
    assert runtime_env["GOOGLE_APPLICATION_CREDENTIALS"] == "./config/secrets/vertex_service_account.json"


def test_compose_mounts_local_artifacts_and_workspace() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["openhands-agent-server"]
    runtime_service = compose["services"]["autoweave-runtime"]
    mounts = service["volumes"]
    runtime_mounts = runtime_service["volumes"]

    assert service["working_dir"] == "/workspace"
    assert "./var/artifacts:/data" in mounts
    assert "./:/workspace:rw" in mounts
    assert "./var/artifacts:/data" in runtime_mounts
    assert "./:/workspace:rw" in runtime_mounts
    assert runtime_service["working_dir"] == "/workspace"


def test_docker_assets_exist_for_runtime_container() -> None:
    assert Path("Dockerfile").exists()
    assert Path(".dockerignore").exists()
    assert "config/secrets/" in Path(".dockerignore").read_text(encoding="utf-8")


def test_compose_matches_settings_expectations() -> None:
    settings = LocalEnvironmentSettings.load(root=Path("."), materialize_vertex_credentials=False)

    assert settings.artifact_store_url.startswith("file://")
    assert str(settings.vertex_service_account_file).endswith("config/secrets/vertex_service_account.json")
    assert str(settings.google_application_credentials).endswith("config/secrets/vertex_service_account.json")
