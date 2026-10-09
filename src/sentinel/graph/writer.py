"""图谱写入：episode 构建与去重落库。"""

import logging
from datetime import datetime
from typing import Any

from graphiti_core import Graphiti
from sentinel.config import ProfileConfig, get_profile_config
from sentinel.utils.litellm_text import generate_text

logger = logging.getLogger(__name__)


async def _summarize_for_extraction(
    settings,
    text: str,
    source_description: str | None,
) -> str:
    system_prompt = (
        "你是严谨的信息压缩助手。请从原文中提炼最重要、最稳定、最适合后续实体抽取与关系抽取的事实。"
        "去掉重复、修饰、情绪化表达和弱相关细节，只保留关键事件、主体、动作、结果、数字、时间、地点、因果关系。"
        "输出必须是中文摘要，尽量用条目式。"
    )
    user_prompt = f"""
标题：
{source_description or ""}

原文：
{text}

请输出一个适合后续 LLM 实体抽取和关系抽取的“重要事实摘要”，要求：
1. 只保留核心事实，不要复述全文。
2. 保留明确时间、地点、主体、动作、结果、数值、因果链。
3. 如有多条关键事实，请用编号列表输出。
4. 控制在 200~400 字左右。
"""
    response = await generate_text(
        settings,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return str(response).strip()


async def add_event_to_graph(
    graphiti: Graphiti,
    event_text: str,
    reference_time: datetime | None = None,
    source_description: str | None = None,
    group_id: str | None = None,
    custom_extraction_instructions: str | None = None,
    update_communities: bool = False,
    summarize_before_extract: bool = False,
    dry_run: bool = False,
    app_settings=None,
    profile_config: ProfileConfig | None = None,
) -> Any:
    effective_profile = profile_config
    if effective_profile is None:
        if app_settings is None:
            raise ValueError("app_settings is required when profile_config is None")
        effective_profile = get_profile_config()
    entity_types, edge_types, edge_type_map = (
        effective_profile.graphiti_extraction_config()
    )
    extraction_instructions = (
        custom_extraction_instructions
        if custom_extraction_instructions is not None
        else effective_profile.prompts.pipeline.graph_extraction.body
    )

    effective_reference_time = reference_time or datetime.now()
    effective_source = source_description
    effective_event_text = event_text
    summary_text = None

    if summarize_before_extract:
        if app_settings is None:
            raise ValueError(
                "app_settings is required when summarize_before_extract=True"
            )
        summary_text = await _summarize_for_extraction(
            app_settings,
            event_text,
            effective_source,
        )
        effective_event_text = summary_text

    _original_process: Any = None
    if dry_run:
        _original_process = graphiti._process_episode_data

        async def _noop_process(
            episode: Any,
            nodes: Any,
            entity_edges: Any,
            now: Any,
            group_id: Any,
            saga: Any = None,
            saga_previous_episode_uuid: Any = None,
            node_episode_index_map: Any = None,
        ) -> tuple[list, Any]:
            episodes = episode if isinstance(episode, list) else [episode]
            for ep in episodes:
                ep.entity_edges = [e.uuid for e in entity_edges]
            return [], episodes[0]

        graphiti._process_episode_data = _noop_process

    try:
        result = await graphiti.add_episode(
            name=effective_source,
            episode_body=effective_event_text,
            source_description=effective_source,
            reference_time=effective_reference_time,
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
            custom_extraction_instructions=extraction_instructions,
            group_id=group_id,
            update_communities=update_communities,
        )
    finally:
        if dry_run and _original_process is not None:
            graphiti._process_episode_data = _original_process

    result_payload = (
        result.model_dump()
        if hasattr(result, "model_dump")
        else result.dict()
        if hasattr(result, "dict")
        else result
    )

    entities_extracted = len(result_payload.get("nodes", []))
    relations_created = len(result_payload.get("edges", []))

    return {
        "entities_extracted": entities_extracted,
        "relations_created": relations_created,
        "input_text": event_text,
        "summary": summary_text,
        "used_summary_for_extraction": summarize_before_extract,
        "group_id": group_id,
    }


async def batch_add_to_graph(
    graphiti: Graphiti,
    events: list[dict],
    group_id: str,
    dry_run: bool = False,
    app_settings=None,
) -> list[dict]:
    """
    批量将多个事件写入图谱。

    Args:
        graphiti: Graphiti 客户端实例
        events: 事件列表，每个元素包含 {"text": ..., "reference_time": ..., ...}
        group_id: 事件分组 ID
        dry_run: 是否跳过 Neo4j 写入

    Returns:
        list[dict]: 每个事件的写入结果（与 add_event_to_graph 返回值格式一致）
    """
    results = []
    profile_config = None
    if app_settings is not None:
        profile_config = get_profile_config()
    for event in events:
        event_text = event.get("text", "")
        reference_time = event.get("reference_time")
        if isinstance(reference_time, str):
            try:
                reference_time = datetime.fromisoformat(reference_time)
            except ValueError:
                reference_time = datetime.now()
        elif reference_time is None:
            reference_time = datetime.now()

        try:
            result = await add_event_to_graph(
                graphiti=graphiti,
                event_text=event_text,
                reference_time=reference_time,
                source_description=f"batch:{group_id}",
                group_id=group_id,
                dry_run=dry_run,
                app_settings=app_settings,
                profile_config=profile_config,
            )
            results.append(result)
        except Exception as e:
            logger.error("batch_add_to_graph failed for event: %s", e)
            results.append(
                {
                    "success": False,
                    "error": str(e),
                    "entities_extracted": 0,
                    "relations_created": 0,
                }
            )

    total_nodes = sum(r.get("entities_extracted", 0) for r in results)
    total_edges = sum(r.get("relations_created", 0) for r in results)
    logger.info(
        "batch_add_to_graph complete: %d events, %d nodes, %d edges",
        len(results),
        total_nodes,
        total_edges,
    )
    return results
