"""Graph projection exports."""

from __future__ import annotations

from autoweave.graph.projection import (
    InMemoryGraphProjectionBackend,
    ProjectedNode,
    ProjectedRelation,
    SQLiteGraphProjectionBackend,
)

__all__ = [
    "InMemoryGraphProjectionBackend",
    "Neo4jGraphProjectionBackend",
    "ProjectedNode",
    "ProjectedRelation",
    "SQLiteGraphProjectionBackend",
]


def __getattr__(name: str):
    if name in {"Neo4jGraphProjectionBackend", "SQLiteGraphProjectionBackend"}:
        from autoweave.graph.neo4j_projection import Neo4jGraphProjectionBackend, SQLiteGraphProjectionBackend

        exports = {
            "Neo4jGraphProjectionBackend": Neo4jGraphProjectionBackend,
            "SQLiteGraphProjectionBackend": SQLiteGraphProjectionBackend,
        }
        return exports[name]
    raise AttributeError(name)
