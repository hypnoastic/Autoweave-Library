"""Local runtime wiring for storage, artifacts, graph, and context services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from autoweave.artifacts.filesystem import FilesystemArtifactStore
from autoweave.artifacts.registry import InMemoryArtifactRegistry
from autoweave.context.service import InMemoryContextService
from autoweave.memory.store import InMemoryMemoryStore
from autoweave.settings import LocalEnvironmentSettings, Neo4jTarget, OpenHandsTarget, PostgresTarget, RedisTarget
from autoweave.storage.coordination import RedisClient, RedisIdempotencyStore, RedisLeaseManager


@dataclass(frozen=True)
class RedisWireSpec:
    """Keyspace helpers that remain wire-compatible with Redis deployments."""

    database: int
    host: str
    port: int
    key_prefix: str = ""

    def lease_key(self, attempt_id: str) -> str:
        return self._prefix(f"lease:attempt:{attempt_id}")

    def heartbeat_key(self, attempt_id: str) -> str:
        return self._prefix(f"heartbeat:attempt:{attempt_id}")

    def dispatch_key(self, workflow_run_id: str) -> str:
        return self._prefix(f"dispatch:workflow:{workflow_run_id}")

    def stream_key(self, workflow_run_id: str) -> str:
        return self._prefix(f"stream:workflow:{workflow_run_id}")

    def idempotency_key(self, action_key: str) -> str:
        return self._prefix(f"idempotency:{action_key}")

    def _prefix(self, key: str) -> str:
        if not self.key_prefix:
            return key
        normalized = self.key_prefix.rstrip(":")
        return f"{normalized}:{key}"


@dataclass(frozen=True)
class StorageConnectionTargets:
    postgres: PostgresTarget
    neo4j: Neo4jTarget
    redis: RedisTarget
    openhands: OpenHandsTarget
    artifact_root: Path


@dataclass
class LocalStorageWiring:
    settings: LocalEnvironmentSettings
    targets: StorageConnectionTargets
    workflow_repository: object
    artifact_store: FilesystemArtifactStore
    artifact_registry: InMemoryArtifactRegistry
    memory_store: InMemoryMemoryStore
    context_service: InMemoryContextService
    graph_projection: object
    lease_manager: RedisLeaseManager
    idempotency_store: RedisIdempotencyStore[str]
    redis_wire: RedisWireSpec


def build_local_storage_wiring(settings: LocalEnvironmentSettings) -> LocalStorageWiring:
    from autoweave.graph.neo4j_projection import Neo4jGraphProjectionBackend
    from autoweave.graph.projection import SQLiteGraphProjectionBackend
    from autoweave.storage.durable import SQLiteWorkflowRepository
    from autoweave.storage.postgres import PostgresWorkflowRepository

    settings.ensure_local_layout()
    artifact_root = resolve_artifact_root(settings)
    if settings.autoweave_canonical_backend == "postgres":
        workflow_repository = PostgresWorkflowRepository(
            settings.postgres_url,
            schema=settings.autoweave_postgres_schema,
        )
    else:
        workflow_repository = SQLiteWorkflowRepository(settings.state_dir() / "autoweave.sqlite3")
    artifact_store = FilesystemArtifactStore(artifact_root)
    artifact_registry = InMemoryArtifactRegistry(workflow_repository, payload_store=artifact_store)
    memory_store = InMemoryMemoryStore()
    if settings.autoweave_graph_backend == "neo4j":
        graph_projection = Neo4jGraphProjectionBackend(
            settings.neo4j_url,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
            namespace=settings.autoweave_postgres_schema,
        )
    else:
        graph_projection = SQLiteGraphProjectionBackend(settings.state_dir() / "autoweave_projection.sqlite3")
    redis_client = RedisClient(settings.redis_url)
    lease_manager = RedisLeaseManager(client=redis_client)
    idempotency_store = RedisIdempotencyStore(client=redis_client)
    redis_target = settings.redis_target()

    return LocalStorageWiring(
        settings=settings,
        targets=StorageConnectionTargets(
            postgres=settings.postgres_target(),
            neo4j=settings.neo4j_target(),
            redis=redis_target,
            openhands=settings.openhands_target(),
            artifact_root=artifact_root,
        ),
        workflow_repository=workflow_repository,
        artifact_store=artifact_store,
        artifact_registry=artifact_registry,
        memory_store=memory_store,
        context_service=InMemoryContextService(
            workflow_repository=workflow_repository,
            artifact_registry=artifact_registry,
            memory_store=memory_store,
        ),
        graph_projection=graph_projection,
        lease_manager=lease_manager,
        idempotency_store=idempotency_store,
        redis_wire=RedisWireSpec(
            database=redis_target.database,
            host=redis_target.host,
            port=redis_target.port,
        ),
    )


def resolve_artifact_root(settings: LocalEnvironmentSettings) -> Path:
    """Resolve file:// and path-style artifact URLs into a local filesystem path."""

    parsed = urlparse(settings.artifact_store_url)
    if parsed.scheme == "file":
        if parsed.netloc in {"", None}:
            if parsed.path.startswith("/"):
                return Path(parsed.path).expanduser().resolve()
            relative = parsed.path
            if relative:
                return (settings.project_root / relative).resolve()
            return (settings.project_root / "var" / "artifacts").resolve()
        if parsed.netloc in {".", "localhost"}:
            relative = parsed.path.lstrip("/")
            return (settings.project_root / relative).resolve()
        return Path(f"//{parsed.netloc}{parsed.path}").expanduser().resolve()
    if parsed.scheme:
        raise ValueError(f"unsupported artifact store scheme: {parsed.scheme}")
    return (settings.project_root / settings.artifact_store_url).resolve()
