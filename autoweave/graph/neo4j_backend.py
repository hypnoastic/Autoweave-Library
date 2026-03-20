"""Neo4j-backed projection/query adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

from autoweave.models import EventRecord


@dataclass(frozen=True)
class Neo4jGraphTarget:
    url: str
    username: str | None = None
    password: str | None = None
    database: str | None = None


class Neo4jGraphProjectionBackend:
    """Projects canonical events into Neo4j without mutating canonical truth."""

    def __init__(
        self,
        url: str | Any,
        *,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
        namespace: str = "autoweave",
    ) -> None:
        if not isinstance(url, str):
            target = Neo4jGraphTarget(
                url=str(getattr(url, "url")),
                username=getattr(url, "username", None),
                password=getattr(url, "password", None),
                database=database,
            )
        else:
            target = Neo4jGraphTarget(url=url, username=username, password=password, database=database)
        self.target = target
        self.namespace = namespace
        auth: tuple[str, str] | None = None
        if target.username is not None and target.password is not None:
            auth = (target.username, target.password)
        self._driver = GraphDatabase.driver(target.url, auth=auth)

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def project_event(self, event: EventRecord) -> None:
        payload = dict(event.payload_json)
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str):
            return
        entity_type = str(payload.get("entity_type", "Entity"))
        properties = {key: value for key, value in payload.items() if isinstance(value, str)}
        target_id = payload.get("target_id")
        relation = payload.get("relation")
        query = """
        MERGE (event:AutoWeaveEvent {namespace: $namespace, id: $event_id})
        SET event.workflow_run_id = $workflow_run_id,
            event.event_type = $event_type,
            event.source = $source
        MERGE (source:AutoWeaveEntity {namespace: $namespace, id: $entity_id})
        SET source.workflow_run_id = $workflow_run_id,
            source.entity_type = $entity_type
        SET source += $properties
        MERGE (event)-[:PROJECTS]->(source)
        WITH source
        FOREACH (_ IN CASE WHEN $target_id IS NULL THEN [] ELSE [1] END |
            MERGE (target:AutoWeaveEntity {namespace: $namespace, id: $target_id})
            SET target.workflow_run_id = $workflow_run_id
            MERGE (source)-[rel:RELATED {event_id: $event_id}]->(target)
            SET rel.kind = $relation
        )
        """
        with self._driver.session(database=self.target.database) as session:
            session.run(
                query,
                entity_id=entity_id,
                namespace=self.namespace,
                entity_type=entity_type,
                workflow_run_id=event.workflow_run_id,
                event_type=event.event_type,
                source=event.source,
                properties=properties,
                target_id=target_id if isinstance(target_id, str) else None,
                relation=str(relation) if isinstance(relation, str) else "related_to",
                event_id=event.id,
            ).consume()

    def query_related_entities(self, entity_id: str, depth: int = 1) -> list[dict[str, str]]:
        limit = max(depth, 1)
        query = """
        MATCH (entity:AutoWeaveEntity {namespace: $namespace, id: $entity_id})-[rel:RELATED]-(other:AutoWeaveEntity {namespace: $namespace})
        RETURN startNode(rel).id AS source_id,
               rel.kind AS relation,
               endNode(rel).id AS target_id,
               rel.event_id AS event_id
        LIMIT $limit
        """
        with self._driver.session(database=self.target.database) as session:
            result = session.run(query, entity_id=entity_id, namespace=self.namespace, limit=limit)
            return [
                {
                    "source_id": str(record["source_id"]),
                    "relation": str(record["relation"]),
                    "target_id": str(record["target_id"]),
                    "event_id": str(record["event_id"]),
                }
                for record in result
            ]

    def list_events(self) -> list[EventRecord]:
        query = """
        MATCH (event:AutoWeaveEvent {namespace: $namespace})
        RETURN event.id AS id,
               event.workflow_run_id AS workflow_run_id,
               event.event_type AS event_type,
               event.source AS source
        ORDER BY id
        """
        with self._driver.session(database=self.target.database) as session:
            result = session.run(query, namespace=self.namespace)
            return [
                EventRecord(
                    id=str(record["id"]),
                    workflow_run_id=str(record["workflow_run_id"]),
                    event_type=str(record["event_type"]),
                    source=str(record["source"]),
                )
                for record in result
            ]

    def clear_namespace(self) -> None:
        query = """
        MATCH (node)
        WHERE (node:AutoWeaveEntity OR node:AutoWeaveEvent) AND node.namespace = $namespace
        DETACH DELETE node
        """
        with self._driver.session(database=self.target.database) as session:
            session.run(query, namespace=self.namespace).consume()
