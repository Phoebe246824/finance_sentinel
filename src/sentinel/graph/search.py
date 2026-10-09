"""图谱混合检索的查询封装。"""

import logging
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.search.search_config_recipes import (
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
)
from graphiti_core.search.search_filters import SearchFilters

logger = logging.getLogger(__name__)


async def hybrid_search(
    graphiti: Graphiti,
    query: str,
    group_id: str | None = None,
    recipe: Any = COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    filters: Any | None = None,
    num_results: int = 10,
    candidate_limit: int | None = None,
    min_score: float = 0.0,
) -> Any:
    group_ids = [group_id] if group_id else None
    search_config = recipe
    if candidate_limit is None:
        candidate_limit = max(num_results * 2, 10) if num_results else 10
    if hasattr(recipe, "model_copy"):
        search_config = recipe.model_copy(update={"limit": candidate_limit})
    elif hasattr(recipe, "copy"):
        search_config = recipe.copy(update={"limit": candidate_limit})
    elif isinstance(recipe, dict):
        search_config = {**recipe, "limit": candidate_limit}

    # Graphiti 底层部分搜索实现会假定 search_filter 一定是 SearchFilters 实例。
    # 显式传空过滤器，避免 None 传入后在驱动层触发 `'NoneType' object has no attribute 'get'`。
    search_filters = filters if filters is not None else SearchFilters()

    result = await graphiti.search_(
        query,
        config=search_config,
        group_ids=group_ids,
        search_filter=search_filters,
    )
    global_ranked = None
    if num_results is not None:
        global_ranked = await _global_merge_rerank_top_k(
            graphiti=graphiti,
            query=query,
            edges=result.edges,
            nodes=result.nodes,
            episodes=result.episodes,
            communities=result.communities,
            top_k=num_results,
        )

    if min_score > 0.0 and global_ranked:
        before = len(global_ranked)
        global_ranked = [
            item
            for item in global_ranked
            if (item.get("score") if item.get("score") is not None else 0) >= min_score
        ]
        after = len(global_ranked)
        if after < before:
            logger.info(
                "相关性过滤: %d -> %d (min_score=%.2f)", before, after, min_score
            )

    return {
        "query": query,
        "results": global_ranked,
        "num_results_count": len(global_ranked) if global_ranked else 0,
        "num_results_limit": num_results,
        "group_id": group_id,
        "nodes": result.nodes,
        "edges": result.edges,
        "episodes": result.episodes,
        "communities": result.communities,
    }


async def _global_merge_rerank_top_k(
    graphiti: Graphiti,
    query: str,
    edges: list[Any],
    nodes: list[Any],
    episodes: list[Any],
    communities: list[Any],
    top_k: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, str]] = []
    for edge in edges:
        if getattr(edge, "fact", None):
            candidates.append({"type": "edge", "text": edge.fact})
    for episode in episodes:
        if getattr(episode, "content", None):
            candidates.append({"type": "episode", "text": episode.content})

    if not candidates or top_k <= 0:
        return []

    text_to_type: dict[str, str] = {}
    unique_texts: list[str] = []
    for item in candidates:
        text = item["text"]
        if text not in text_to_type:
            text_to_type[text] = item["type"]
            unique_texts.append(text)

    reranked = await graphiti.cross_encoder.rank(query, unique_texts)
    top_ranked: list[dict[str, Any]] = []
    for text, score in reranked:
        if len(top_ranked) >= top_k:
            break
        top_ranked.append(
            {
                "type": text_to_type.get(text, "unknown"),
                "text": text,
                "score": score,
            }
        )

    return top_ranked


async def graph_episode_content_count(graphiti, content: str, group_id: str) -> int:
    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Episodic)
        WHERE e.group_id = $group_id
          AND (e.content = $content OR e.raw_content = $content)
        RETURN count(e) AS content_count
        """,
        group_id=group_id,
        content=content,
        routing_="r",
    )
    if not records:
        return 0
    return int(records[0].get("content_count", 0))


async def get_subject_episode_uuids(
    graphiti, id_numbers: list[str], group_id: str
) -> set[str]:
    """查找所有包含指定 id_number 主体的 Episode UUID。

    这里的"包含"指 Episode 通过 MENTIONS 关系直接提到了 id_number=P01 的实体，
    不是从 P01 出发扩展一跳/多跳邻居子图。
    """
    if not id_numbers:
        return set()

    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Episodic)-[:MENTIONS]->(n:Entity)
        WHERE e.group_id = $group_id
          AND toUpper(toString(n.id_number)) IN $id_numbers
        RETURN DISTINCT e.uuid AS uuid
        """,
        group_id=group_id,
        id_numbers=[id_number.upper() for id_number in id_numbers],
        routing_="r",
    )
    return {record["uuid"] for record in records if record.get("uuid")}


def filter_search_result_by_subject_episodes(
    result: dict, episode_uuids: set[str], id_numbers: list[str]
) -> dict:
    """只保留"包含当前主体 id_number 的 Episode"及其内部结果。"""
    if not id_numbers or not result:
        return result

    if not episode_uuids:
        scoped_result = dict(result)
        scoped_result["scope_mode"] = "subject_episode"
        scoped_result["subject_id_numbers"] = id_numbers
        scoped_result["subject_episode_uuids"] = []
        scoped_result["edges"] = []
        scoped_result["nodes"] = []
        scoped_result["episodes"] = []
        scoped_result["results"] = []
        scoped_result["num_results_count"] = 0
        return scoped_result

    scoped_episodes = [
        episode
        for episode in result.get("episodes", [])
        if getattr(episode, "uuid", None) in episode_uuids
    ]
    scoped_edge_uuids = {
        edge_uuid
        for episode in scoped_episodes
        for edge_uuid in getattr(episode, "entity_edges", [])
    }
    scoped_edges = [
        edge
        for edge in result.get("edges", [])
        if getattr(edge, "uuid", None) in scoped_edge_uuids
    ]
    scoped_node_uuids = {
        node_uuid
        for edge in scoped_edges
        for node_uuid in (
            getattr(edge, "source_node_uuid", None),
            getattr(edge, "target_node_uuid", None),
        )
        if node_uuid
    }
    scoped_nodes = [
        node
        for node in result.get("nodes", [])
        if getattr(node, "uuid", None) in scoped_node_uuids
    ]

    scoped_texts: list[str] = []
    for episode in scoped_episodes:
        content = getattr(episode, "content", None)
        if content:
            scoped_texts.append(str(content))
    for edge in scoped_edges:
        fact = getattr(edge, "fact", None)
        if fact:
            scoped_texts.append(str(fact))

    filtered_results = []
    for item in result.get("results", []):
        text = item.get("text", "")
        if any(text and text in scoped_text for scoped_text in scoped_texts):
            filtered_results.append(item)

    if not filtered_results:
        filtered_results = [
            {"type": "subject_episode", "text": text, "score": None}
            for text in scoped_texts[: result.get("num_results_limit", 10)]
        ]

    scoped_result = dict(result)
    scoped_result["scope_mode"] = "subject_episode"
    scoped_result["subject_id_numbers"] = id_numbers
    scoped_result["subject_episode_uuids"] = sorted(episode_uuids)
    scoped_result["edges"] = scoped_edges
    scoped_result["nodes"] = scoped_nodes
    scoped_result["episodes"] = scoped_episodes
    scoped_result["results"] = filtered_results[: result.get("num_results_limit", 10)]
    scoped_result["num_results_count"] = len(scoped_result["results"])
    return scoped_result
