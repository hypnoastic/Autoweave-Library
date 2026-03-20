"""Neo4j-backed projection and graph query support."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from neo4j import Driver, GraphDatabase

from autoweave.models import EventRecord
from autoweave.settings import Neo4jTarget


@dataclass(frozen=True)
class ProjectedRelation:
    source_id: str
    relation: str
    target_id: str
    event_id: str


@dataclass
class ProjectedNode:
    node_id: str
    labels: set[str] = field(default_factory=set)
    properties: dict[str, str] = field(default_factory=dict)


class Neo4jGraphProjectionBackend:
    """Neo4j projection backend that stays downstream of Postgres truth."""

    def __init__(
        self,
        target_or_url: str | Neo4jTarget | Driver,
        *,
        username: str | None = None,
        password: str | None = None,
        namespace: str = "autoweave",
        driver: Driver | None = None,
    ) -> None:
        self.namespace = namespace
        self._driver = driver or self._build_driver(target_or_url, username=username, password=password)

    def close(self) -> None:
        self._driver.close()

    def clear_namespace(self) -> None:
        with self._driver.session() as session:
            session.execute_write(self._clear_namespace_tx, self.namespace)

    def project_event(self, event: EventRecord) -> None:
        with self._driver.session() as session:
            session.execute_write(self._project_event_tx, event.model_dump(mode="json"), self.namespace)

    def query_related_entities(self, entity_id: str, depth: int = 1) -> list[dict[str, str]]:
        with self._driver.session() as session:
            return session.execute_read(self._query_related_entities_tx, entity_id, self.namespace, max(depth, 1))

    def list_events(self) -> list[EventRecord]:
        with self._driver.session() as session:
            rows = session.execute_read(self._list_events_tx, self.namespace)
        return [EventRecord.model_validate_json(row["data_json"]) for row in rows]

    @staticmethod
    def _build_driver(
        target_or_url: str | Neo4jTarget | Driver,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> Driver:
        if isinstance(target_or_url, Driver):
            return target_or_url
        if isinstance(target_or_url, Neo4jTarget):
            target = target_or_url
            auth = None
            if target.username or target.password:
                auth = (target.username, target.password)
            return GraphDatabase.driver(target.url, auth=auth)
        auth = None
        if username or password:
            auth = (username, password)
        return GraphDatabase.driver(target_or_url, auth=auth)

    @staticmethod
    def _clear_namespace_tx(tx: Any, namespace: str) -> None:
        tx.run("MATCH (n {namespace: $namespace}) DETACH DELETE n", namespace=namespace)

    @staticmethod
    def _project_event_tx(tx: Any, event_json: dict[str, Any], namespace: str) -> None:
        payload = dict(event_json.get("payload_json") or {})
        string_props = {
            key: value
            for key, value in payload.items()
            if isinstance(value, str)
            and key not in {"entity_id", "entity_type", "relation", "target_id", "target_entity_type"}
        }
        event_record_json = json.dumps(event_json, sort_keys=True)
        tx.run(
            """
            MERGE (event:AutoWeaveEvent {event_id: $event_id, namespace: $namespace})
            SET event.workflow_run_id = $workflow_run_id,
                event.task_id = $task_id,
                event.task_attempt_id = $task_attempt_id,
                event.agent_id = $agent_id,
                event.agent_role = $agent_role,
                event.sandbox_id = $sandbox_id,
                event.provider_name = $provider_name,
                event.model_name = $model_name,
                event.route_reason = $route_reason,
                event.event_type = $event_type,
                event.source = $source,
                event.severity = $severity,
                event.sequence_no = $sequence_no,
                event.data_json = $data_json
            """,
            event_id=event_json["id"],
            namespace=namespace,
            workflow_run_id=event_json["workflow_run_id"],
            task_id=event_json.get("task_id"),
            task_attempt_id=event_json.get("task_attempt_id"),
            agent_id=event_json.get("agent_id"),
            agent_role=event_json.get("agent_role"),
            sandbox_id=event_json.get("sandbox_id"),
            provider_name=event_json.get("provider_name"),
            model_name=event_json.get("model_name"),
            route_reason=event_json.get("route_reason"),
            event_type=event_json["event_type"],
            source=event_json["source"],
            severity=event_json["severity"],
            sequence_no=int(event_json.get("sequence_no", 0)),
            data_json=event_record_json,
        )
        entity_id = payload.get("entity_id")
        relation = payload.get("relation")
        target_id = payload.get("target_id")
        if isinstance(entity_id, str):
            tx.run(
                """
                MERGE (source:AutoWeaveEntity {entity_id: $entity_id, namespace: $namespace})
                SET source.entity_type = coalesce($entity_type, source.entity_type, 'Entity')
                SET source += $string_props
                WITH source
                MATCH (event:AutoWeaveEvent {event_id: $event_id, namespace: $namespace})
                MERGE (event)-[:PROJECTED_ENTITY {namespace: $namespace}]->(source)
                """,
                entity_id=entity_id,
                namespace=namespace,
                entity_type=payload.get("entity_type"),
                string_props=string_props,
                event_id=event_json["id"],
            )
        if isinstance(entity_id, str) and isinstance(relation, str) and isinstance(target_id, str):
            relation_record = json.dumps(
                {
                    "event_id": event_json["id"],
                    "namespace": namespace,
                    "relation": relation,
                    "target_id": target_id,
                },
                sort_keys=True,
            )
            tx.run(
                """
                MERGE (source:AutoWeaveEntity {entity_id: $entity_id, namespace: $namespace})
                SET source.entity_type = coalesce($entity_type, source.entity_type, 'Entity')
                SET source += $source_props
                MERGE (target:AutoWeaveEntity {entity_id: $target_id, namespace: $namespace})
                SET target.entity_type = coalesce($target_entity_type, target.entity_type, 'Entity')
                WITH source, target
                MERGE (source)-[rel:RELATED_ENTITY {event_id: $event_id, namespace: $namespace}]->(target)
                SET rel.relation = $relation,
                    rel.data_json = $data_json
                """,
                entity_id=entity_id,
                namespace=namespace,
                entity_type=payload.get("entity_type"),
                source_props=string_props,
                target_id=target_id,
                target_entity_type=payload.get("target_entity_type"),
                event_id=event_json["id"],
                relation=relation,
                data_json=relation_record,
            )

    @staticmethod
    def _query_related_entities_tx(tx: Any, entity_id: str, namespace: str, depth: int) -> list[dict[str, str]]:
        query = """
            MATCH (source:AutoWeaveEntity {namespace: $namespace})-[rel:RELATED_ENTITY {namespace: $namespace}]-(target:AutoWeaveEntity {namespace: $namespace})
            WHERE source.entity_id = $entity_id OR target.entity_id = $entity_id
            RETURN source.entity_id AS source_id,
                   rel.relation AS relation,
                   target.entity_id AS target_id,
                   rel.event_id AS event_id
            ORDER BY rel.event_id
            LIMIT $depth
        """
        result = tx.run(query, entity_id=entity_id, namespace=namespace, depth=max(depth, 1))
        return [record.data() for record in result]

    @staticmethod
    def _list_events_tx(tx: Any, namespace: str) -> list[dict[str, Any]]:
        query = """
            MATCH (event:AutoWeaveEvent {namespace: $namespace})
            RETURN event.data_json AS data_json
            ORDER BY event.sequence_no, event.event_id
        """
        result = tx.run(query, namespace=namespace)
        return [record.data() for record in result]


SQLiteGraphProjectionBackend = Neo4jGraphProjectionBackend
