"""Storage and coordination exports."""

from autoweave.storage.coordination import (
    InMemoryIdempotencyStore,
    InMemoryLeaseManager,
    RedisClient,
    RedisIdempotencyStore,
    RedisLeaseManager,
)
from autoweave.storage.repositories import InMemoryRepositoryIndex, InMemoryWorkflowRepository, WorkflowSnapshot
from autoweave.storage.tasks import CleanupWorkspaceTask, DispatchWorkflowTask, ProjectGraphTask

__all__ = [
    "CleanupWorkspaceTask",
    "DispatchWorkflowTask",
    "InMemoryIdempotencyStore",
    "InMemoryLeaseManager",
    "InMemoryRepositoryIndex",
    "InMemoryWorkflowRepository",
    "LocalStorageWiring",
    "RedisClient",
    "RedisIdempotencyStore",
    "RedisLeaseManager",
    "ProjectGraphTask",
    "RedisWireSpec",
    "StorageConnectionTargets",
    "PostgresWorkflowRepository",
    "build_local_storage_wiring",
    "WorkflowSnapshot",
    "SQLiteWorkflowRepository",
]


def __getattr__(name: str):
    if name in {"PostgresWorkflowRepository", "SQLiteWorkflowRepository"}:
        from autoweave.storage.durable import SQLiteWorkflowRepository
        from autoweave.storage.postgres import PostgresWorkflowRepository

        exports = {
            "PostgresWorkflowRepository": PostgresWorkflowRepository,
            "SQLiteWorkflowRepository": SQLiteWorkflowRepository,
        }
        return exports[name]
    if name in {
        "LocalStorageWiring",
        "RedisWireSpec",
        "StorageConnectionTargets",
        "build_local_storage_wiring",
    }:
        from autoweave.storage.wiring import (
            LocalStorageWiring,
            RedisWireSpec,
            StorageConnectionTargets,
            build_local_storage_wiring,
        )

        exports = {
            "LocalStorageWiring": LocalStorageWiring,
            "RedisWireSpec": RedisWireSpec,
            "StorageConnectionTargets": StorageConnectionTargets,
            "build_local_storage_wiring": build_local_storage_wiring,
        }
        return exports[name]
    raise AttributeError(name)
