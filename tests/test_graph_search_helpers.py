from types import SimpleNamespace

from sentinel.graph.search import filter_search_result_by_subject_episodes


def test_filter_search_result_returns_empty_scope_when_subject_has_no_episodes():
    result = {
        "edges": [SimpleNamespace(uuid="edge-1")],
        "nodes": [SimpleNamespace(uuid="node-1")],
        "episodes": [SimpleNamespace(uuid="episode-1")],
        "results": [{"type": "episode", "text": "episode text", "score": 0.8}],
        "num_results_limit": 10,
    }

    scoped = filter_search_result_by_subject_episodes(result, set(), ["P01"])

    assert scoped["scope_mode"] == "subject_episode"
    assert scoped["subject_id_numbers"] == ["P01"]
    assert scoped["subject_episode_uuids"] == []
    assert scoped["edges"] == []
    assert scoped["nodes"] == []
    assert scoped["episodes"] == []
    assert scoped["results"] == []
    assert scoped["num_results_count"] == 0


def test_filter_search_result_keeps_episode_internal_edges_nodes_and_results():
    episode = SimpleNamespace(
        uuid="episode-1",
        content="P01 appeared in episode content",
        entity_edges=["edge-1"],
    )
    edge = SimpleNamespace(
        uuid="edge-1",
        fact="P01 related fact",
        source_node_uuid="node-1",
        target_node_uuid="node-2",
    )
    result = {
        "edges": [edge, SimpleNamespace(uuid="edge-2")],
        "nodes": [
            SimpleNamespace(uuid="node-1"),
            SimpleNamespace(uuid="node-2"),
            SimpleNamespace(uuid="node-3"),
        ],
        "episodes": [episode, SimpleNamespace(uuid="episode-2", entity_edges=[])],
        "results": [{"type": "episode", "text": "P01 appeared", "score": 0.8}],
        "num_results_limit": 10,
    }

    scoped = filter_search_result_by_subject_episodes(result, {"episode-1"}, ["P01"])

    assert scoped["episodes"] == [episode]
    assert scoped["edges"] == [edge]
    assert [node.uuid for node in scoped["nodes"]] == ["node-1", "node-2"]
    assert scoped["results"] == [
        {"type": "episode", "text": "P01 appeared", "score": 0.8}
    ]
    assert scoped["num_results_count"] == 1
