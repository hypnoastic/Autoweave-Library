"""Canonical local-development settings and path normalization."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse, urlunparse

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

CANONICAL_VERTEX_CREDENTIALS = Path("config/secrets/vertex_service_account.json")
DEFAULT_ARTIFACT_DIR = Path("var/artifacts")
DEFAULT_OBSERVABILITY_DIR = Path("var/observability")
DEFAULT_WORKSPACES_DIR = Path("workspaces")


def find_project_root(start: Path | None = None) -> Path:
    """Locate the repository root from the current working directory."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "docs").exists():
            return candidate
    return current


def resolve_repo_path(root: Path, value: str | Path) -> Path:
    """Resolve an absolute or repo-relative path."""

    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def redact_connection_url(url: str) -> str:
    """Remove embedded credentials from a connection URL."""

    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or (parsed.username is None and parsed.password is None):
        return url

    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"

    if parsed.password is not None:
        username = parsed.username or ""
        userinfo = f"{username}:***" if username else "***"
    else:
        userinfo = parsed.username or ""
    netloc = f"{userinfo}@{hostname}" if userinfo else hostname
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def load_env_map(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    """Load `.env`, `.env.local`, then explicit environment overrides."""

    values: dict[str, str] = {}
    loaded_files: list[Path] = []
    for filename in (".env", ".env.local"):
        path = root / filename
        if not path.exists():
            continue
        file_values = {key: value for key, value in dotenv_values(path).items() if value is not None}
        values.update(file_values)
        loaded_files.append(path)
    overlay = environ if environ is not None else os.environ
    values.update({key: value for key, value in overlay.items() if value is not None})
    return values, tuple(loaded_files)


def get_env_value(env_map: Mapping[str, str], key: str, default: str = "") -> str:
    """Return an env value, treating blank strings as unset."""

    value = env_map.get(key)
    if value is None:
        return default
    stripped = value.strip()
    return stripped if stripped else default


def ensure_vertex_credentials_layout(root: Path) -> Path:
    """Materialize the canonical Vertex service-account location for local development."""

    target = root / CANONICAL_VERTEX_CREDENTIALS
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target

    candidates = sorted(path for path in root.glob("*.json") if path.is_file())
    if not candidates:
        return target
    shutil.copy2(candidates[0], target)
    return target


class PostgresTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    host: str
    port: int | None = None
    database: str | None = None
    sslmode: str | None = None
    uses_neon: bool = False

    @classmethod
    def from_url(cls, url: str) -> "PostgresTarget":
        parsed = urlparse(url)
        query: dict[str, str] = {}
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    query[key] = value
        database = parsed.path.lstrip("/") or None
        return cls(
            url=url,
            host=parsed.hostname or "",
            port=parsed.port,
            database=database,
            sslmode=query.get("sslmode"),
            uses_neon="neon.tech" in (parsed.hostname or ""),
        )

    def redacted_dump(self) -> dict[str, object]:
        payload = self.model_dump()
        payload["url"] = redact_connection_url(self.url)
        return payload


class Neo4jTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    uses_aura: bool = False

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> "Neo4jTarget":
        parsed = urlparse(url)
        default_port = 7687 if parsed.scheme.startswith("neo4j") or parsed.scheme.startswith("bolt") else 443
        return cls(
            url=url,
            scheme=parsed.scheme,
            host=parsed.hostname or "",
            port=parsed.port or default_port,
            username=username,
            password=password,
            uses_aura=".databases.neo4j.io" in (parsed.hostname or ""),
        )

    def redacted_dump(self) -> dict[str, object]:
        payload = self.model_dump()
        payload["url"] = redact_connection_url(self.url)
        if payload.get("password"):
            payload["password"] = "***"
        return payload


class RedisTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    host: str
    port: int
    database: int = 0

    @classmethod
    def from_url(cls, url: str) -> "RedisTarget":
        parsed = urlparse(url)
        database = int(parsed.path.lstrip("/") or "0")
        return cls(url=url, host=parsed.hostname or "127.0.0.1", port=parsed.port or 6379, database=database)

    def redacted_dump(self) -> dict[str, object]:
        payload = self.model_dump()
        payload["url"] = redact_connection_url(self.url)
        return payload


class OpenHandsTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_key: str | None = None

    @property
    def health_url(self) -> str:
        return self.base_url.rstrip("/") + "/health"

    def redacted_dump(self) -> dict[str, object]:
        payload = self.model_dump()
        if payload.get("api_key"):
            payload["api_key"] = "***"
        return payload


class LocalEnvironmentSettings(BaseModel):
    """Resolved local-development settings with normalized local paths."""

    model_config = ConfigDict(extra="forbid")

    project_root: Path
    loaded_env_files: tuple[Path, ...] = ()

    vertexai_project: str
    vertexai_location: str
    vertex_service_account_file: Path
    google_application_credentials: Path

    postgres_url: str
    redis_url: str = "redis://127.0.0.1:6379/0"
    neo4j_url: str
    neo4j_username: str | None = None
    neo4j_password: str | None = None

    artifact_store_url: str
    openhands_agent_server_base_url: str = "http://127.0.0.1:8000"
    openhands_agent_server_api_key: str | None = None
    openhands_worker_timeout_seconds: int = 1800

    autoweave_default_workflow: Path = Field(default=Path("configs/workflows/team.workflow.yaml"))
    autoweave_runtime_config: Path = Field(default=Path("configs/runtime/runtime.yaml"))
    autoweave_storage_config: Path = Field(default=Path("configs/runtime/storage.yaml"))
    autoweave_vertex_config: Path = Field(default=Path("configs/runtime/vertex.yaml"))
    autoweave_observability_config: Path = Field(default=Path("configs/runtime/observability.yaml"))

    autoweave_canonical_backend: str = "sqlite"
    autoweave_graph_backend: str = "sqlite"
    autoweave_postgres_schema: str = "autoweave"
    autoweave_state_dir: Path = Field(default=Path("var/state"))

    autoweave_max_active_attempts: int = 8
    autoweave_heartbeat_interval_seconds: int = 15
    autoweave_lease_ttl_seconds: int = 60
    autoweave_openhands_poll_timeout_seconds: int = 90
    autoweave_openhands_poll_interval_seconds: int = 1

    @classmethod
    def load(
        cls,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        materialize_vertex_credentials: bool = True,
    ) -> "LocalEnvironmentSettings":
        project_root = find_project_root(root)
        env_map, loaded_files = load_env_map(project_root, environ=environ)

        credentials_path = ensure_vertex_credentials_layout(project_root) if materialize_vertex_credentials else project_root / CANONICAL_VERTEX_CREDENTIALS
        vertex_value = get_env_value(env_map, "VERTEXAI_SERVICE_ACCOUNT_FILE", str(CANONICAL_VERTEX_CREDENTIALS))
        google_value = get_env_value(env_map, "GOOGLE_APPLICATION_CREDENTIALS", vertex_value)

        artifact_store_url = get_env_value(env_map, "ARTIFACT_STORE_URL", f"file://{(project_root / DEFAULT_ARTIFACT_DIR).resolve()}")

        settings = cls(
            project_root=project_root,
            loaded_env_files=loaded_files,
            vertexai_project=get_env_value(env_map, "VERTEXAI_PROJECT"),
            vertexai_location=get_env_value(env_map, "VERTEXAI_LOCATION"),
            vertex_service_account_file=resolve_repo_path(project_root, vertex_value),
            google_application_credentials=resolve_repo_path(project_root, google_value),
            postgres_url=get_env_value(env_map, "POSTGRES_URL"),
            redis_url=get_env_value(env_map, "REDIS_URL", "redis://127.0.0.1:6379/0"),
            neo4j_url=get_env_value(env_map, "NEO4J_URL"),
            neo4j_username=get_env_value(env_map, "NEO4J_USERNAME") or None,
            neo4j_password=get_env_value(env_map, "NEO4J_PASSWORD") or None,
            artifact_store_url=artifact_store_url,
            openhands_agent_server_base_url=get_env_value(env_map, "OPENHANDS_AGENT_SERVER_BASE_URL", "http://127.0.0.1:8000"),
            openhands_agent_server_api_key=get_env_value(env_map, "OPENHANDS_AGENT_SERVER_API_KEY") or None,
            openhands_worker_timeout_seconds=int(get_env_value(env_map, "OPENHANDS_WORKER_TIMEOUT_SECONDS", "1800")),
            autoweave_default_workflow=Path(get_env_value(env_map, "AUTOWEAVE_DEFAULT_WORKFLOW", "configs/workflows/team.workflow.yaml")),
            autoweave_runtime_config=Path(get_env_value(env_map, "AUTOWEAVE_RUNTIME_CONFIG", "configs/runtime/runtime.yaml")),
            autoweave_storage_config=Path(get_env_value(env_map, "AUTOWEAVE_STORAGE_CONFIG", "configs/runtime/storage.yaml")),
            autoweave_vertex_config=Path(get_env_value(env_map, "AUTOWEAVE_VERTEX_CONFIG", "configs/runtime/vertex.yaml")),
            autoweave_observability_config=Path(get_env_value(env_map, "AUTOWEAVE_OBSERVABILITY_CONFIG", "configs/runtime/observability.yaml")),
            autoweave_canonical_backend=get_env_value(env_map, "AUTOWEAVE_CANONICAL_BACKEND", "sqlite"),
            autoweave_graph_backend=get_env_value(env_map, "AUTOWEAVE_GRAPH_BACKEND", "sqlite"),
            autoweave_postgres_schema=get_env_value(env_map, "AUTOWEAVE_POSTGRES_SCHEMA", "autoweave"),
            autoweave_state_dir=Path(get_env_value(env_map, "AUTOWEAVE_STATE_DIR", "var/state")),
            autoweave_max_active_attempts=int(get_env_value(env_map, "AUTOWEAVE_MAX_ACTIVE_ATTEMPTS", "8")),
            autoweave_heartbeat_interval_seconds=int(get_env_value(env_map, "AUTOWEAVE_HEARTBEAT_INTERVAL_SECONDS", "15")),
            autoweave_lease_ttl_seconds=int(get_env_value(env_map, "AUTOWEAVE_LEASE_TTL_SECONDS", "60")),
            autoweave_openhands_poll_timeout_seconds=int(
                get_env_value(env_map, "AUTOWEAVE_OPENHANDS_POLL_TIMEOUT_SECONDS", "90")
            ),
            autoweave_openhands_poll_interval_seconds=int(
                get_env_value(env_map, "AUTOWEAVE_OPENHANDS_POLL_INTERVAL_SECONDS", "1")
            ),
        )
        # Always normalize the worker-side credential path to the canonical local file.
        if credentials_path.exists():
            settings.vertex_service_account_file = credentials_path.resolve()
            settings.google_application_credentials = credentials_path.resolve()
        return settings

    def ensure_local_layout(self) -> None:
        (self.project_root / DEFAULT_ARTIFACT_DIR).mkdir(parents=True, exist_ok=True)
        (self.project_root / DEFAULT_OBSERVABILITY_DIR).mkdir(parents=True, exist_ok=True)
        (self.project_root / DEFAULT_WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self.state_dir().mkdir(parents=True, exist_ok=True)
        (self.project_root / CANONICAL_VERTEX_CREDENTIALS).parent.mkdir(parents=True, exist_ok=True)

    def resolve_config_path(self, path: Path) -> Path:
        return resolve_repo_path(self.project_root, path)

    def artifact_store_path(self) -> Path:
        parsed = urlparse(self.artifact_store_url)
        if parsed.scheme in {"", "file"}:
            if parsed.scheme == "file" and parsed.netloc and parsed.path:
                if parsed.netloc in {".", "localhost"}:
                    return (self.project_root / parsed.path.lstrip("/")).resolve()
                return Path("//" + parsed.netloc + parsed.path).resolve()
            return resolve_repo_path(self.project_root, parsed.path or str(DEFAULT_ARTIFACT_DIR))
        raise ValueError(f"unsupported artifact store scheme: {parsed.scheme}")

    def state_dir(self) -> Path:
        return resolve_repo_path(self.project_root, self.autoweave_state_dir)

    def worker_environment(self) -> dict[str, str]:
        return {
            "VERTEXAI_PROJECT": self.vertexai_project,
            "VERTEXAI_LOCATION": self.vertexai_location,
            "VERTEXAI_SERVICE_ACCOUNT_FILE": str(self.vertex_service_account_file),
            "GOOGLE_APPLICATION_CREDENTIALS": str(self.google_application_credentials),
        }

    def postgres_target(self) -> PostgresTarget:
        return PostgresTarget.from_url(self.postgres_url)

    def neo4j_target(self) -> Neo4jTarget:
        return Neo4jTarget.from_url(
            self.neo4j_url,
            username=self.neo4j_username,
            password=self.neo4j_password,
        )

    def redis_target(self) -> RedisTarget:
        return RedisTarget.from_url(self.redis_url)

    def openhands_target(self) -> OpenHandsTarget:
        return OpenHandsTarget(
            base_url=self.openhands_agent_server_base_url,
            api_key=self.openhands_agent_server_api_key,
        )
