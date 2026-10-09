"""人员一跳关系的图谱查询与 PersonGraph 组装。"""

import math
from collections.abc import Iterable, Mapping

from graphiti_core import Graphiti

GRAPH_QUERY_TIMEOUT_SECONDS = 5
PERSON_GRAPH_MAX_EDGES = 100
EVENT_GRAPH_MAX_EDGES = 140
OMITTED_GRAPH_PROPERTY_KEYS = {"embedding", "name_embedding", "fact_embedding"}
MAX_INLINE_VECTOR_LENGTH = 32


def _empty_person_subgraph(person_id: str) -> dict[str, object]:
    return {"center_person_id": person_id, "nodes": [], "edges": []}


def _empty_event_subgraph(event_id: str) -> dict[str, object]:
    return {"center_person_id": event_id, "nodes": [], "edges": [], "source": "neo4j"}


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return _json_safe_properties(value)
    if isinstance(value, list | tuple | set):
        values = list(value)
        if len(values) > MAX_INLINE_VECTOR_LENGTH and all(
            isinstance(item, int | float) for item in values
        ):
            return f"<vector:{len(values)}>"
        return [_json_safe_value(item) for item in values]
    return str(value)


def _json_safe_properties(properties: object | None) -> dict[str, object]:
    if not isinstance(properties, Mapping):
        return {}
    return {
        str(key): _json_safe_value(value)
        for key, value in properties.items()
        if str(key) not in OMITTED_GRAPH_PROPERTY_KEYS
    }


def _json_safe_list(value: object | None) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [_json_safe_value(item) for item in value]
    return [_json_safe_value(value)]


def _append_node(
    nodes: list[dict[str, object]],
    seen_node_ids: set[str],
    *,
    node_id: str | None,
    label: object,
    node_type: object,
    risk_level: object,
    labels: object | None = None,
    properties: object | None = None,
) -> None:
    if not node_id or node_id in seen_node_ids:
        return

    seen_node_ids.add(node_id)
    nodes.append(
        {
            "id": node_id,
            "label": _json_safe_value(label),
            "type": _json_safe_value(node_type),
            "risk_level": _json_safe_value(risk_level),
            "labels": _json_safe_list(labels),
            "properties": _json_safe_properties(properties),
        }
    )


def _build_person_subgraph(
    *, person_id: str, records: Iterable[dict[str, object]]
) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_node_ids: set[str] = set()
    seen_edges: set[object] = set()
    canonical_person_id: str | None = None

    for record in records:
        if canonical_person_id is None:
            center_id = record.get("center_id")
            canonical_person_id = str(center_id) if center_id else person_id

        _append_node(
            nodes,
            seen_node_ids,
            node_id=str(record["center_id"]) if record.get("center_id") else None,
            label=record.get("center_label"),
            node_type=record.get("center_type"),
            risk_level=record.get("center_risk_level"),
        )
        _append_node(
            nodes,
            seen_node_ids,
            node_id=str(record["neighbor_id"]) if record.get("neighbor_id") else None,
            label=record.get("neighbor_label"),
            node_type=record.get("neighbor_type"),
            risk_level=record.get("neighbor_risk_level"),
        )

        edge_source = record.get("edge_source")
        edge_target = record.get("edge_target")
        if not edge_source or not edge_target:
            continue

        edge_id = record.get("edge_id")
        edge_key: object = edge_id or (
            str(edge_source),
            str(edge_target),
            record.get("edge_label"),
        )
        if edge_key in seen_edges:
            continue

        seen_edges.add(edge_key)
        edges.append(
            {
                "id": str(edge_id) if edge_id else "",
                "source": str(edge_source),
                "target": str(edge_target),
                "label": _json_safe_value(record.get("edge_label")),
                "type": _json_safe_value(record.get("edge_type")),
                "properties": _json_safe_properties(record.get("edge_properties")),
            }
        )

    return {
        "center_person_id": canonical_person_id or person_id,
        "nodes": nodes,
        "edges": edges,
    }


async def fetch_person_subgraph(
    *,
    graphiti: Graphiti,
    person_id: str,
    group_id: str,
    max_edges: int = PERSON_GRAPH_MAX_EDGES,
) -> dict[str, object]:
    normalized_person_id = person_id.strip().upper()
    if not normalized_person_id:
        return _empty_person_subgraph(person_id)

    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (center:Entity)
        WHERE center.id_number = $person_id
          AND center.group_id = $group_id
        WITH center
        ORDER BY center.uuid
        LIMIT 1
        CALL {
            WITH center
            OPTIONAL MATCH (center)-[rel:RELATES_TO]-(neighbor:Entity)
            WHERE rel.group_id = $group_id
              AND neighbor.group_id = $group_id
            RETURN rel, neighbor
            LIMIT $max_edges
        }
        RETURN
            coalesce(toString(center.id_number), center.uuid) AS center_id,
            coalesce(center.name, center.summary, center.id_number, center.uuid) AS center_label,
            coalesce(center.type, head(labels(center)), 'Entity') AS center_type,
            center.risk_level AS center_risk_level,
            coalesce(toString(neighbor.id_number), neighbor.uuid) AS neighbor_id,
            coalesce(neighbor.name, neighbor.summary, neighbor.id_number, neighbor.uuid) AS neighbor_label,
            coalesce(neighbor.type, head(labels(neighbor)), 'Entity') AS neighbor_type,
            neighbor.risk_level AS neighbor_risk_level,
            rel.uuid AS edge_id,
            coalesce(toString(startNode(rel).id_number), startNode(rel).uuid) AS edge_source,
            coalesce(toString(endNode(rel).id_number), endNode(rel).uuid) AS edge_target,
            coalesce(rel.name, type(rel)) AS edge_label
        """,
        person_id=normalized_person_id,
        group_id=group_id,
        max_edges=max_edges,
        routing_="r",
        timeout_=GRAPH_QUERY_TIMEOUT_SECONDS,
    )

    if not records:
        return _empty_person_subgraph(person_id)

    return _build_person_subgraph(person_id=person_id, records=records)


def _append_edge(
    edges: list[dict[str, object]],
    seen_edges: set[object],
    *,
    edge_id: object,
    source: object,
    target: object,
    label: object,
    edge_type: object,
    properties: object,
) -> None:
    if not source or not target:
        return
    edge_key: object = edge_id or (str(source), str(target), label or edge_type)
    if edge_key in seen_edges:
        return
    seen_edges.add(edge_key)
    edges.append(
        {
            "id": str(edge_id) if edge_id else "",
            "source": str(source),
            "target": str(target),
            "label": _json_safe_value(label or edge_type),
            "type": _json_safe_value(edge_type),
            "properties": _json_safe_properties(properties),
        }
    )


def _build_event_subgraph(
    *, event_id: str, records: Iterable[dict[str, object]], max_edges: int
) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_node_ids: set[str] = set()
    seen_edges: set[object] = set()
    center_id: str | None = None

    for record in records:
        if center_id is None and record.get("episode_id"):
            center_id = str(record["episode_id"])

        _append_node(
            nodes,
            seen_node_ids,
            node_id=str(record["episode_id"]) if record.get("episode_id") else None,
            label=record.get("episode_label"),
            node_type="Event",
            risk_level=record.get("episode_risk_level"),
            labels=record.get("episode_labels"),
            properties=record.get("episode_properties"),
        )
        _append_node(
            nodes,
            seen_node_ids,
            node_id=str(record["entity_id"]) if record.get("entity_id") else None,
            label=record.get("entity_label"),
            node_type=record.get("entity_type"),
            risk_level=record.get("entity_risk_level"),
            labels=record.get("entity_labels"),
            properties=record.get("entity_properties"),
        )
        _append_node(
            nodes,
            seen_node_ids,
            node_id=str(record["neighbor_id"]) if record.get("neighbor_id") else None,
            label=record.get("neighbor_label"),
            node_type=record.get("neighbor_type"),
            risk_level=record.get("neighbor_risk_level"),
            labels=record.get("neighbor_labels"),
            properties=record.get("neighbor_properties"),
        )

        if len(edges) < max_edges:
            _append_edge(
                edges,
                seen_edges,
                edge_id=record.get("mention_edge_id"),
                source=record.get("mention_source"),
                target=record.get("mention_target"),
                label=record.get("mention_label"),
                edge_type=record.get("mention_type"),
                properties=record.get("mention_properties"),
            )
        if len(edges) < max_edges:
            _append_edge(
                edges,
                seen_edges,
                edge_id=record.get("rel_edge_id"),
                source=record.get("rel_source"),
                target=record.get("rel_target"),
                label=record.get("rel_label"),
                edge_type=record.get("rel_type"),
                properties=record.get("rel_properties"),
            )

    return {
        "center_person_id": center_id or event_id,
        "nodes": nodes,
        "edges": edges,
        "source": "neo4j",
    }


async def fetch_event_subgraph(
    *,
    graphiti: Graphiti,
    event_id: str,
    event_content: str,
    group_id: str,
    max_edges: int = EVENT_GRAPH_MAX_EDGES,
) -> dict[str, object]:
    content = event_content.strip()
    if not content:
        return _empty_event_subgraph(event_id)

    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (episode:Episodic)
        WHERE episode.group_id = $group_id
          AND episode.content = $event_content
        WITH episode
        ORDER BY episode.created_at DESC, episode.uuid
        LIMIT 1
        OPTIONAL MATCH (episode)-[mention:MENTIONS]-(entity:Entity {group_id: $group_id})
        OPTIONAL MATCH (entity)-[rel:RELATES_TO]-(neighbor:Entity {group_id: $group_id})
        WHERE rel IS NULL OR rel.group_id = $group_id
        RETURN
            coalesce(episode.uuid, elementId(episode)) AS episode_id,
            coalesce(
                episode.name,
                episode.source_description,
                substring(episode.content, 0, 48),
                episode.uuid,
                elementId(episode)
            ) AS episode_label,
            labels(episode) AS episode_labels,
            properties(episode) AS episode_properties,
            episode.risk_level AS episode_risk_level,

            coalesce(toString(entity.id_number), entity.uuid, elementId(entity)) AS entity_id,
            coalesce(entity.name, entity.summary, entity.id_number, entity.uuid, elementId(entity)) AS entity_label,
            coalesce(entity.type, head(labels(entity)), 'Entity') AS entity_type,
            labels(entity) AS entity_labels,
            properties(entity) AS entity_properties,
            entity.risk_level AS entity_risk_level,

            coalesce(toString(neighbor.id_number), neighbor.uuid, elementId(neighbor)) AS neighbor_id,
            coalesce(neighbor.name, neighbor.summary, neighbor.id_number, neighbor.uuid, elementId(neighbor)) AS neighbor_label,
            coalesce(neighbor.type, head(labels(neighbor)), 'Entity') AS neighbor_type,
            labels(neighbor) AS neighbor_labels,
            properties(neighbor) AS neighbor_properties,
            neighbor.risk_level AS neighbor_risk_level,

            coalesce(mention.uuid, elementId(mention)) AS mention_edge_id,
            coalesce(episode.uuid, elementId(episode)) AS mention_source,
            coalesce(toString(entity.id_number), entity.uuid, elementId(entity)) AS mention_target,
            coalesce(mention.name, type(mention)) AS mention_label,
            type(mention) AS mention_type,
            properties(mention) AS mention_properties,

            CASE WHEN rel IS NULL THEN NULL ELSE coalesce(rel.uuid, elementId(rel)) END AS rel_edge_id,
            CASE
                WHEN rel IS NULL THEN NULL
                ELSE coalesce(toString(startNode(rel).id_number), startNode(rel).uuid, elementId(startNode(rel)))
            END AS rel_source,
            CASE
                WHEN rel IS NULL THEN NULL
                ELSE coalesce(toString(endNode(rel).id_number), endNode(rel).uuid, elementId(endNode(rel)))
            END AS rel_target,
            CASE WHEN rel IS NULL THEN NULL ELSE coalesce(rel.name, type(rel)) END AS rel_label,
            CASE WHEN rel IS NULL THEN NULL ELSE type(rel) END AS rel_type,
            CASE WHEN rel IS NULL THEN NULL ELSE properties(rel) END AS rel_properties
        LIMIT $max_edges
        """,
        event_content=content,
        group_id=group_id,
        max_edges=max_edges,
        routing_="r",
        timeout_=GRAPH_QUERY_TIMEOUT_SECONDS,
    )

    if not records:
        return _empty_event_subgraph(event_id)

    return _build_event_subgraph(
        event_id=event_id,
        records=records,
        max_edges=max_edges,
    )


async def fetch_graph_counts(*, graphiti: Graphiti, group_id: str) -> dict[str, int]:
    node_records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (n:Entity)
        WHERE n.group_id = $group_id
        RETURN count(n) AS node_count
        """,
        group_id=group_id,
        routing_="r",
        timeout_=GRAPH_QUERY_TIMEOUT_SECONDS,
    )
    edge_records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (source:Entity)-[r:RELATES_TO]->(target:Entity)
        WHERE source.group_id = $group_id
          AND target.group_id = $group_id
          AND r.group_id = $group_id
        RETURN count(r) AS edge_count
        """,
        group_id=group_id,
        routing_="r",
        timeout_=GRAPH_QUERY_TIMEOUT_SECONDS,
    )

    return {
        "graph_node_count": int(node_records[0].get("node_count", 0))
        if node_records
        else 0,
        "graph_edge_count": int(edge_records[0].get("edge_count", 0))
        if edge_records
        else 0,
    }
