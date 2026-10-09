"""Batch graph build helpers for recalled Milvus event records."""

from datetime import datetime
from typing import Protocol

from sentinel.config import SentinelSettings
from sentinel.graph import (
    batch_add_to_graph,
    close_graph_client,
    graph_episode_content_count,
    init_graph_client,
)
from sentinel.models import NormalizedEvent
from sentinel.utils.litellm_rerank import rerank_scores
from sentinel.utils.logging import get_logger, print_error, print_info


class EventRecallStore(Protocol):
    async def fetch_related_events(
        self,
        event: NormalizedEvent,
        id_numbers: list[str],
        top_k_semantic: int = 10,
        max_per_person: int = 20,
    ) -> list[dict]: ...

    async def mark_events_graph_built(self, event_ids: list[str]) -> int: ...


def get_shared_person_ids(
    historical_event: dict,
    current_id_numbers: list[str],
) -> list[str]:
    current_person_ids = {pid.upper() for pid in current_id_numbers}
    historical_person_ids = {
        str(pid).upper() for pid in historical_event.get("person_ids", [])
    }
    return sorted(current_person_ids.intersection(historical_person_ids))


async def rerank_historical_candidates(
    app_settings: SentinelSettings,
    query: str,
    candidates: list[dict],
    min_score: float,
) -> dict[str, tuple[bool, str, float]]:
    if not candidates:
        return {}

    documents = [candidate.get("raw_content", "") for candidate in candidates]
    scores = await rerank_scores(
        query=query,
        documents=documents,
        model=app_settings.effective_reranker_model,
        api_key=app_settings.effective_reranker_api_key_value(),
        base_url=app_settings.effective_reranker_base_url,
    )
    results = {}
    for index, candidate in enumerate(candidates):
        score = scores[index] if index < len(scores) else 0.0
        passed = score >= min_score
        reason = f"rerank_score={score:.4f} {'>=' if passed else '<'} {min_score:.4f}"
        results[candidate.get("event_id", str(index))] = (passed, reason, score)
    return results


async def batch_graph_event_with_related_stash(
    app_settings: SentinelSettings,
    stash_store: EventRecallStore | None,
    id_numbers: list[str],
    normalized_event: NormalizedEvent,
) -> dict:
    logger = get_logger("main.graph.batch")
    summary = {
        "fetched_count": 0,
        "eligible_count": 0,
        "batched_count": 0,
        "skipped_irrelevant_count": 0,
        "success": True,
        "batch_results": [],
    }
    if stash_store is None:
        return summary

    historical_events = await stash_store.fetch_related_events(
        normalized_event,
        id_numbers,
        top_k_semantic=app_settings.stash_semantic_top_k,
        max_per_person=app_settings.batch_max_per_person,
    )
    summary["fetched_count"] = len(historical_events)
    logger.info(
        "Milvus recall fetched_count=%d event_ids=%s",
        len(historical_events),
        [event.get("event_id") for event in historical_events if event.get("event_id")],
    )

    if not historical_events:
        print_info("Milvus 事件库回捞为空，跳过批量构图")
        return summary

    print_info(
        f"从 Milvus 取回 {len(historical_events)} 条候选事件，检查相关性和是否需要批量构图"
    )
    graphiti = None
    try:
        graphiti = await init_graph_client(app_settings)
        dry_run = app_settings.graphiti_dry_run
        group_id = app_settings.graphiti_episode_source

        rerank_enabled = app_settings.stash_rerank_enabled
        rerank_min_score = app_settings.stash_rerank_min_score
        shared_person_events = []
        rerank_candidate_events = []
        skipped_irrelevant_results = []
        for historical_event in historical_events:
            raw_content = historical_event.get("raw_content", "")
            if not raw_content:
                continue
            shared_person_ids = get_shared_person_ids(historical_event, id_numbers)
            if shared_person_ids:
                historical_event["eligibility_reason"] = (
                    f"shared_person_ids={shared_person_ids}"
                )
                shared_person_events.append(historical_event)
            else:
                rerank_candidate_events.append(historical_event)

        rerank_results = {}
        if rerank_candidate_events:
            if rerank_enabled:
                rerank_results = await rerank_historical_candidates(
                    app_settings,
                    normalized_event.raw_content,
                    rerank_candidate_events,
                    rerank_min_score,
                )
            else:
                rerank_results = {
                    candidate.get("event_id", str(index)): (
                        False,
                        "rerank disabled for non-shared-person candidate",
                        0.0,
                    )
                    for index, candidate in enumerate(rerank_candidate_events)
                }

        eligible_events = list(shared_person_events)
        for index, historical_event in enumerate(rerank_candidate_events):
            event_id = historical_event.get("event_id", str(index))
            passed, reason, score = rerank_results.get(
                event_id,
                (False, "missing rerank result", 0.0),
            )
            historical_event["rerank_score"] = score
            historical_event["eligibility_reason"] = reason
            if passed:
                eligible_events.append(historical_event)
                continue
            skipped_irrelevant_results.append(
                {
                    "event_id": historical_event.get("event_id"),
                    "success": True,
                    "skipped": True,
                    "skip_reason": "rerank_filtered_candidate",
                    "reason": reason,
                    "match_source": historical_event.get("match_source"),
                    "semantic_score": historical_event.get("semantic_score"),
                    "rerank_score": score,
                }
            )
            logger.info(
                "skip Milvus candidate by rerank: event_id=%s, reason=%s, match_source=%s, semantic_score=%s, rerank_score=%.4f",
                historical_event.get("event_id"),
                reason,
                historical_event.get("match_source"),
                historical_event.get("semantic_score"),
                score,
            )

        batch_texts = []
        events_to_graph = []
        skipped_existing_results = []
        skipped_existing_event_ids = []
        for historical_event in eligible_events:
            raw_content = historical_event.get("raw_content", "")
            existing_content_count = 0
            if not dry_run:
                existing_content_count = await graph_episode_content_count(
                    graphiti, raw_content, group_id
                )
            if existing_content_count > 0:
                event_id = historical_event.get("event_id")
                if event_id:
                    skipped_existing_event_ids.append(event_id)
                skipped_existing_results.append(
                    {
                        "event_id": event_id,
                        "success": True,
                        "skipped": True,
                        "skip_reason": "existing_episode_content",
                        "existing_content_count": existing_content_count,
                        "entities_extracted": 0,
                        "relations_created": 0,
                    }
                )
                continue

            reference_time = historical_event.get("created_at") or historical_event.get(
                "timestamp", datetime.now()
            )
            if isinstance(reference_time, str):
                reference_time = datetime.fromisoformat(reference_time)
            batch_texts.append(
                {
                    "text": raw_content,
                    "reference_time": reference_time,
                }
            )
            events_to_graph.append(historical_event)

        if skipped_irrelevant_results:
            print_info(
                f"Milvus 回捞中 {len(skipped_irrelevant_results)} 条未通过 rerank 过滤，跳过批量构图"
            )
        if skipped_existing_results:
            print_info(
                f"Milvus 回捞中 {len(skipped_existing_results)} 条已存在 Neo4j，跳过重复批量构图"
            )

        if batch_texts:
            print_info(f"{len(batch_texts)} 条历史事件需要执行批量构图")
            batch_results = await batch_add_to_graph(
                graphiti,
                batch_texts,
                group_id,
                dry_run,
                app_settings=app_settings,
            )
        else:
            print_info("Milvus 回捞后无新增候选需要批量构图")
            batch_results = []

        all_results = [
            *skipped_irrelevant_results,
            *skipped_existing_results,
            *batch_results,
        ]
        summary["batch_results"] = all_results
        summary["eligible_count"] = len(eligible_events)
        summary["batched_count"] = len(batch_texts)
        summary["skipped_irrelevant_count"] = len(skipped_irrelevant_results)
        summary["skipped_existing_count"] = len(skipped_existing_results)

        all_success = all(
            r.get("success", True) for r in [*skipped_existing_results, *batch_results]
        )
        summary["success"] = all_success
        if all_success and not dry_run:
            consumed_event_ids = [
                event["event_id"] for event in events_to_graph if event.get("event_id")
            ]
            consumed_event_ids.extend(skipped_existing_event_ids)
            await stash_store.mark_events_graph_built(consumed_event_ids)
            print_info("批量构图/跳过检查完成，已标记相关 Milvus 事件为已构图")
        elif all_success:
            print_info("DRY RUN: 批量构图检查完成，Milvus 事件记录保留为未构图")
        else:
            failed = sum(1 for r in all_results if not r.get("success", True))
            print_info(
                f"批量构图部分失败 ({failed}/{len(all_results)})，Milvus 事件记录保留待重试"
            )
        return summary
    except Exception as e:
        print_error(f"批量补图失败: {type(e).__name__}: {e}")
        logger.error(
            "batch graph from Milvus event recall failed: %s", e, exc_info=True
        )
        raise
    finally:
        if graphiti is not None:
            await close_graph_client(graphiti)
