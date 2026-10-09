"""Blacklist proceed/stop gate helpers used by the main workflow."""

from dataclasses import dataclass, field

from sentinel.blacklist.filter import BlacklistFilter, EventSimilarityHit
from sentinel.config import SentinelSettings
from sentinel.models import NormalizedEvent
from sentinel.utils.logging import get_logger
from sentinel.utils.text import extract_person_id_numbers


@dataclass(slots=True)
class BlacklistGateResult:
    should_proceed: bool
    matched_persons: list[str]
    matched_keywords: list[str]
    event_hit: bool
    id_numbers: list[str]
    event_similarity: EventSimilarityHit = field(default_factory=EventSimilarityHit)


def build_blacklist_store_config(app_settings: SentinelSettings) -> dict:
    """Build the Milvus/embedder config consumed by create_store_bundle()."""
    return {
        "milvus": {
            "uri": app_settings.milvus_uri,
            "token": app_settings.optional_milvus_token() or "",
            "input_events_collection": app_settings.milvus_input_events_collection,
            "kv_ttl_days": app_settings.kv_ttl_days,
            "stash_semantic_top_k": app_settings.stash_semantic_top_k,
            "stash_rerank_min_score": app_settings.stash_rerank_min_score,
            "stash_rerank_enabled": app_settings.stash_rerank_enabled,
            "batch_max_per_person": app_settings.batch_max_per_person,
            "embedding_dim": app_settings.embedding_dim,
        },
        "embedder": {
            "model": app_settings.embedder_model,
            "api_key": app_settings.effective_embedder_api_key_value(),
            "api_base": app_settings.effective_embedder_api_base,
        },
    }


async def evaluate_blacklist_gate(
    app_settings: SentinelSettings,
    normalized_event: NormalizedEvent,
    store_bundle,
) -> BlacklistGateResult:
    """Run BlacklistFilter and return the explicit proceed/stop contract."""
    blacklist_filter = BlacklistFilter(
        persons_store=store_bundle.persons,
        keywords_store=store_bundle.keywords,
        samples_store=store_bundle.event_samples,
        similarity_threshold=app_settings.blacklist_event_similarity_threshold,
    )
    check_result = await blacklist_filter.check_with_details(normalized_event)
    event_similarity = check_result.event_similarity
    return BlacklistGateResult(
        should_proceed=check_result.should_proceed,
        matched_persons=check_result.matched_persons,
        matched_keywords=check_result.matched_keywords,
        event_hit=event_similarity.hit,
        id_numbers=extract_person_id_numbers(normalized_event.raw_content),
        event_similarity=event_similarity,
    )


async def record_blacklist_matches(
    normalized_event: NormalizedEvent,
    gate_result: BlacklistGateResult,
    store_bundle,
) -> None:
    """Persist PASS match metadata without converting failures into stop decisions."""
    logger = get_logger("main.blacklist_gate")
    for person_id in gate_result.matched_persons:
        try:
            await store_bundle.persons.append_person(person_id)
        except Exception as exc:
            logger.warning(
                "failed to record matched blacklist person: event_id=%s, person_id=%s, error=%s",
                normalized_event.event_id,
                person_id,
                exc,
                exc_info=True,
            )
    for keyword in gate_result.matched_keywords:
        try:
            await store_bundle.keywords.append_keyword(keyword)
        except Exception as exc:
            logger.warning(
                "failed to record matched blacklist keyword: event_id=%s, keyword=%s, error=%s",
                normalized_event.event_id,
                keyword,
                exc,
                exc_info=True,
            )
    if gate_result.event_hit:
        summary = normalized_event.summary or normalized_event.raw_content[:200]
        try:
            await store_bundle.event_samples.append_event(
                normalized_event.event_id,
                summary,
            )
        except Exception as exc:
            logger.warning(
                "failed to record matched blacklist event sample: event_id=%s, error=%s",
                normalized_event.event_id,
                exc,
                exc_info=True,
            )
