import pytest

from sentinel.graph.person_graph import (
    fetch_event_subgraph,
    fetch_graph_counts,
    fetch_person_subgraph,
)


class FakeGraphiti:
    def __init__(self, records_by_query: list[list[dict]]) -> None:
        self._records_by_query = records_by_query
        self.calls: list[tuple[str, dict]] = []
        self.driver = self

    async def execute_query(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        records = self._records_by_query.pop(0)
        return records, None, None


@pytest.mark.asyncio
async def test_fetch_person_subgraph_returns_one_hop_graph():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "center_id": "P001",
                    "center_label": "张三",
                    "center_type": "person",
                    "center_risk_level": "high",
                    "neighbor_id": "A001",
                    "neighbor_label": "账户 A001",
                    "neighbor_type": "account",
                    "neighbor_risk_level": "medium",
                    "edge_id": "edge-1",
                    "edge_source": "P001",
                    "edge_target": "A001",
                    "edge_label": "持有",
                }
            ]
        ]
    )

    result = await fetch_person_subgraph(
        graphiti=graphiti,
        person_id="P001",
        group_id="sentinel",
    )

    assert result["center_person_id"] == "P001"
    assert result["nodes"] == [
        {
            "id": "P001",
            "label": "张三",
            "type": "person",
            "risk_level": "high",
            "labels": [],
            "properties": {},
        },
        {
            "id": "A001",
            "label": "账户 A001",
            "type": "account",
            "risk_level": "medium",
            "labels": [],
            "properties": {},
        },
    ]
    assert result["edges"] == [
        {
            "id": "edge-1",
            "source": "P001",
            "target": "A001",
            "label": "持有",
            "type": None,
            "properties": {},
        }
    ]


@pytest.mark.asyncio
async def test_fetch_person_subgraph_uses_canonical_center_id_from_graph():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "center_id": "P001",
                    "center_label": "张三",
                    "center_type": "person",
                    "center_risk_level": "high",
                    "neighbor_id": None,
                    "neighbor_label": None,
                    "neighbor_type": None,
                    "neighbor_risk_level": None,
                    "edge_id": None,
                    "edge_source": None,
                    "edge_target": None,
                    "edge_label": None,
                }
            ]
        ]
    )

    result = await fetch_person_subgraph(
        graphiti=graphiti,
        person_id="p001",
        group_id="sentinel",
    )

    assert result["center_person_id"] == "P001"
    assert result["nodes"][0]["id"] == "P001"


@pytest.mark.asyncio
async def test_fetch_person_subgraph_queries_group_scoped_entity_relationships_with_uuid_fallbacks():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "center_id": "P001",
                    "center_label": "张三",
                    "center_type": "person",
                    "center_risk_level": "high",
                    "neighbor_id": "account-uuid-001",
                    "neighbor_label": "外部账户",
                    "neighbor_type": "Account",
                    "neighbor_risk_level": None,
                    "edge_id": "edge-1",
                    "edge_source": "P001",
                    "edge_target": "account-uuid-001",
                    "edge_label": "持有",
                }
            ]
        ]
    )

    await fetch_person_subgraph(
        graphiti=graphiti,
        person_id="P001",
        group_id="sentinel",
    )

    query, kwargs = graphiti.calls[0]

    assert kwargs["person_id"] == "P001"
    assert kwargs["group_id"] == "sentinel"
    assert kwargs["max_edges"] == 100
    assert kwargs["timeout_"] == 5
    assert "MATCH (center:Entity)" in query
    assert "center.id_number = $person_id" in query
    assert "center.group_id = $group_id" in query
    assert "toUpper" not in query
    assert "ORDER BY center.uuid" in query
    assert query.count("LIMIT") == 2
    assert "OPTIONAL MATCH (center)-[rel:RELATES_TO]-(neighbor:Entity)" in query
    assert "CALL {" in query
    assert "LIMIT $max_edges" in query
    assert "rel.group_id = $group_id" in query
    assert "neighbor.group_id = $group_id" in query
    assert "neighbor.uuid" in query
    assert "rel.uuid AS edge_id" in query
    assert "coalesce(rel.name, type(rel)) AS edge_label" in query
    assert "startNode(rel).uuid" in query
    assert "endNode(rel).uuid" in query


@pytest.mark.asyncio
async def test_fetch_person_subgraph_preserves_parallel_edges_by_uuid():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "center_id": "P001",
                    "center_label": "张三",
                    "center_type": "person",
                    "center_risk_level": "high",
                    "neighbor_id": "A001",
                    "neighbor_label": "账户 A001",
                    "neighbor_type": "account",
                    "neighbor_risk_level": "medium",
                    "edge_id": "edge-transfer",
                    "edge_source": "P001",
                    "edge_target": "A001",
                    "edge_label": "转账",
                },
                {
                    "center_id": "P001",
                    "center_label": "张三",
                    "center_type": "person",
                    "center_risk_level": "high",
                    "neighbor_id": "A001",
                    "neighbor_label": "账户 A001",
                    "neighbor_type": "account",
                    "neighbor_risk_level": "medium",
                    "edge_id": "edge-control",
                    "edge_source": "P001",
                    "edge_target": "A001",
                    "edge_label": "控制",
                },
            ]
        ]
    )

    result = await fetch_person_subgraph(
        graphiti=graphiti,
        person_id="P001",
        group_id="sentinel",
    )

    assert result["edges"] == [
        {
            "id": "edge-transfer",
            "source": "P001",
            "target": "A001",
            "label": "转账",
            "type": None,
            "properties": {},
        },
        {
            "id": "edge-control",
            "source": "P001",
            "target": "A001",
            "label": "控制",
            "type": None,
            "properties": {},
        },
    ]


@pytest.mark.asyncio
async def test_fetch_person_subgraph_returns_empty_graph_when_missing():
    graphiti = FakeGraphiti([[]])

    result = await fetch_person_subgraph(
        graphiti=graphiti,
        person_id="P404",
        group_id="sentinel",
    )

    assert result == {"center_person_id": "P404", "nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_fetch_event_subgraph_returns_episode_entities_and_relationships():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "episode_id": "episode-1",
                    "episode_label": "风险事件",
                    "episode_labels": ["Episodic"],
                    "episode_properties": {
                        "summary": "事件摘要",
                        "embedding": [0.1] * 64,
                    },
                    "episode_risk_level": "high",
                    "entity_id": "P001",
                    "entity_label": "客户A",
                    "entity_type": "Customer",
                    "entity_labels": ["Entity", "Customer"],
                    "entity_properties": {
                        "summary": {"nested": "value"},
                        "name_embedding": [0.2] * 64,
                    },
                    "entity_risk_level": "medium",
                    "neighbor_id": "A001",
                    "neighbor_label": "账户A",
                    "neighbor_type": "Account",
                    "neighbor_labels": ["Entity", "Account"],
                    "neighbor_properties": {"summary": "账户摘要"},
                    "neighbor_risk_level": None,
                    "mention_edge_id": "mention-1",
                    "mention_source": "episode-1",
                    "mention_target": "P001",
                    "mention_label": "MENTIONS",
                    "mention_type": "MENTIONS",
                    "mention_properties": {"fact_embedding": [0.3] * 64},
                    "rel_edge_id": "rel-1",
                    "rel_source": "P001",
                    "rel_target": "A001",
                    "rel_label": "持有",
                    "rel_type": "RELATES_TO",
                    "rel_properties": {"amounts": [1, 2, 3]},
                }
            ]
        ]
    )

    result = await fetch_event_subgraph(
        graphiti=graphiti,
        event_id="EVT-1",
        event_content="原始事件",
        group_id="sentinel",
    )

    assert result["center_person_id"] == "episode-1"
    assert result["source"] == "neo4j"
    assert result["nodes"] == [
        {
            "id": "episode-1",
            "label": "风险事件",
            "type": "Event",
            "risk_level": "high",
            "labels": ["Episodic"],
            "properties": {"summary": "事件摘要"},
        },
        {
            "id": "P001",
            "label": "客户A",
            "type": "Customer",
            "risk_level": "medium",
            "labels": ["Entity", "Customer"],
            "properties": {"summary": {"nested": "value"}},
        },
        {
            "id": "A001",
            "label": "账户A",
            "type": "Account",
            "risk_level": None,
            "labels": ["Entity", "Account"],
            "properties": {"summary": "账户摘要"},
        },
    ]
    assert result["edges"] == [
        {
            "id": "mention-1",
            "source": "episode-1",
            "target": "P001",
            "label": "MENTIONS",
            "type": "MENTIONS",
            "properties": {},
        },
        {
            "id": "rel-1",
            "source": "P001",
            "target": "A001",
            "label": "持有",
            "type": "RELATES_TO",
            "properties": {"amounts": [1, 2, 3]},
        },
    ]


@pytest.mark.asyncio
async def test_fetch_event_subgraph_limits_final_edges():
    graphiti = FakeGraphiti(
        [
            [
                {
                    "episode_id": "episode-1",
                    "episode_label": "风险事件",
                    "episode_labels": ["Episodic"],
                    "episode_properties": {},
                    "episode_risk_level": "high",
                    "entity_id": "P001",
                    "entity_label": "客户A",
                    "entity_type": "Customer",
                    "entity_labels": ["Entity", "Customer"],
                    "entity_properties": {},
                    "entity_risk_level": "medium",
                    "neighbor_id": "A001",
                    "neighbor_label": "账户A",
                    "neighbor_type": "Account",
                    "neighbor_labels": ["Entity", "Account"],
                    "neighbor_properties": {},
                    "neighbor_risk_level": None,
                    "mention_edge_id": "mention-1",
                    "mention_source": "episode-1",
                    "mention_target": "P001",
                    "mention_label": "MENTIONS",
                    "mention_type": "MENTIONS",
                    "mention_properties": {},
                    "rel_edge_id": "rel-1",
                    "rel_source": "P001",
                    "rel_target": "A001",
                    "rel_label": "持有",
                    "rel_type": "RELATES_TO",
                    "rel_properties": {},
                }
            ]
        ]
    )

    result = await fetch_event_subgraph(
        graphiti=graphiti,
        event_id="EVT-1",
        event_content="原始事件",
        group_id="sentinel",
        max_edges=1,
    )

    assert len(result["edges"]) == 1
    assert result["edges"][0]["id"] == "mention-1"


@pytest.mark.asyncio
async def test_fetch_event_subgraph_queries_group_scoped_episode_content():
    graphiti = FakeGraphiti([[]])

    await fetch_event_subgraph(
        graphiti=graphiti,
        event_id="EVT-1",
        event_content=" 原始事件 ",
        group_id="sentinel",
    )

    query, kwargs = graphiti.calls[0]
    assert kwargs["event_content"] == "原始事件"
    assert kwargs["group_id"] == "sentinel"
    assert kwargs["max_edges"] == 140
    assert kwargs["timeout_"] == 5
    assert "MATCH (episode:Episodic)" in query
    assert "episode.group_id = $group_id" in query
    assert "episode.content = $event_content" in query
    assert "OPTIONAL MATCH (episode)-[mention:MENTIONS]" in query
    assert "OPTIONAL MATCH (entity)-[rel:RELATES_TO]" in query
    assert "LIMIT $max_edges" in query


@pytest.mark.asyncio
async def test_fetch_event_subgraph_returns_empty_without_content_or_records():
    blank_graphiti = FakeGraphiti([])

    blank = await fetch_event_subgraph(
        graphiti=blank_graphiti,
        event_id="EVT-BLANK",
        event_content=" ",
        group_id="sentinel",
    )

    assert blank == {
        "center_person_id": "EVT-BLANK",
        "nodes": [],
        "edges": [],
        "source": "neo4j",
    }
    assert blank_graphiti.calls == []

    missing_graphiti = FakeGraphiti([[]])
    missing = await fetch_event_subgraph(
        graphiti=missing_graphiti,
        event_id="EVT-MISSING",
        event_content="原始事件",
        group_id="sentinel",
    )

    assert missing == {
        "center_person_id": "EVT-MISSING",
        "nodes": [],
        "edges": [],
        "source": "neo4j",
    }


@pytest.mark.asyncio
async def test_fetch_graph_counts_returns_node_and_edge_totals():
    graphiti = FakeGraphiti(
        [
            [{"node_count": 12}],
            [{"edge_count": 34}],
        ]
    )

    counts = await fetch_graph_counts(graphiti=graphiti, group_id="sentinel")

    assert counts == {"graph_node_count": 12, "graph_edge_count": 34}
    node_query, node_kwargs = graphiti.calls[0]
    edge_query, edge_kwargs = graphiti.calls[1]
    assert node_kwargs["group_id"] == "sentinel"
    assert edge_kwargs["group_id"] == "sentinel"
    assert node_kwargs["timeout_"] == 5
    assert edge_kwargs["timeout_"] == 5
    assert "MATCH (n:Entity)" in node_query
    assert "n.group_id = $group_id" in node_query
    assert "MATCH (source:Entity)-[r:RELATES_TO]->(target:Entity)" in edge_query
    assert "source.group_id = $group_id" in edge_query
    assert "target.group_id = $group_id" in edge_query
    assert "r.group_id = $group_id" in edge_query


def test_graph_package_exports_person_graph_helpers():
    from sentinel.graph import fetch_event_subgraph as exported_fetch_event_subgraph
    from sentinel.graph import fetch_graph_counts as exported_fetch_graph_counts
    from sentinel.graph import fetch_person_subgraph as exported_fetch_person_subgraph

    assert exported_fetch_event_subgraph is fetch_event_subgraph
    assert exported_fetch_graph_counts is fetch_graph_counts
    assert exported_fetch_person_subgraph is fetch_person_subgraph
