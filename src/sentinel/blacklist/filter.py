"""
黑名单过滤器 — BlacklistFilter
=============================
对 NormalizedEvent 执行三合一 OR 匹配：
    1. 人员 ID 比对  → person_blacklist (Milvus)
    2. 敏感词比对    → keyword_blacklist (Milvus)
    3. 事件相似度比对 → event_blacklist (Milvus 向量搜索)

OR 逻辑：任一维度命中 → PASS (True)；全未命中 → STOP (False)。
"""

from dataclasses import dataclass, field
from typing import Protocol

from sentinel.blacklist.stores.event_samples_store import EventSampleMatch
from sentinel.models import NormalizedEvent
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


class PersonsLookup(Protocol):
    async def query_person(self, id_number: str) -> float | None: ...


class KeywordsLookup(Protocol):
    async def query_keywords(self) -> list[str]: ...


class EventSamplesLookup(Protocol):
    async def find_best_match(
        self,
        query: str,
        *,
        threshold: float,
    ) -> EventSampleMatch | None: ...


@dataclass(frozen=True, slots=True)
class EventSimilarityHit:
    hit: bool = False
    score: float = 0.0
    event_id: str = ""
    summary: str = ""
    threshold: float = 0.0


@dataclass(frozen=True, slots=True)
class BlacklistCheckResult:
    should_proceed: bool
    matched_persons: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    event_similarity: EventSimilarityHit = field(default_factory=EventSimilarityHit)

    @property
    def event_hit(self) -> bool:
        return self.event_similarity.hit

    def as_legacy_tuple(self) -> tuple[bool, list[str], list[str], bool]:
        return (
            self.should_proceed,
            self.matched_persons,
            self.matched_keywords,
            self.event_hit,
        )


class BlacklistFilter:
    def __init__(
        self,
        persons_store: PersonsLookup,
        keywords_store: KeywordsLookup,
        samples_store: EventSamplesLookup,
        similarity_threshold: float | None = None,
    ) -> None:
        self._persons = persons_store
        self._keywords = keywords_store
        self._samples = samples_store
        self._similarity_threshold = (
            similarity_threshold if similarity_threshold is not None else 0.5
        )

    async def check(
        self,
        event: NormalizedEvent,
    ) -> tuple[bool, list[str], list[str], bool]:
        return (await self.check_with_details(event)).as_legacy_tuple()

    async def check_with_details(self, event: NormalizedEvent) -> BlacklistCheckResult:
        matched_persons = await self._check_persons(event)
        matched_keywords = await self._check_keywords(event)
        event_similarity = await self._check_event_similarity_details(event)
        should_proceed = bool(
            matched_persons or matched_keywords or event_similarity.hit
        )
        if should_proceed:
            logger.info(
                "blacklist PASS: event_id=%s, persons=%s, keywords=%s, event_sim=%s, event_sim_score=%.4f, event_sim_id=%s",
                event.event_id,
                matched_persons,
                matched_keywords,
                event_similarity.hit,
                event_similarity.score,
                event_similarity.event_id,
            )
        else:
            logger.info("blacklist STOP: event_id=%s, no matches", event.event_id)
        return BlacklistCheckResult(
            should_proceed=should_proceed,
            matched_persons=matched_persons,
            matched_keywords=matched_keywords,
            event_similarity=event_similarity,
        )

    async def _check_persons(self, event: NormalizedEvent) -> list[str]:
        from sentinel.utils.text import extract_person_id_numbers

        hits: list[str] = []
        for pid in extract_person_id_numbers(event.raw_content):
            if await self._persons.query_person(pid) is not None:
                hits.append(pid)
        return hits

    async def _check_keywords(self, event: NormalizedEvent) -> list[str]:
        keywords = await self._keywords.query_keywords()
        return [keyword for keyword in keywords if keyword in event.raw_content]

    async def _check_event_similarity(self, event: NormalizedEvent) -> bool:
        return (await self._check_event_similarity_details(event)).hit

    async def _check_event_similarity_details(
        self,
        event: NormalizedEvent,
    ) -> EventSimilarityHit:
        try:
            match = await self._samples.find_best_match(
                event.raw_content,
                threshold=self._similarity_threshold,
            )
        except Exception as exc:
            logger.error(
                "event similarity check failed, skipping: event_id=%s error=%s",
                event.event_id,
                exc,
                exc_info=True,
            )
            return EventSimilarityHit(threshold=self._similarity_threshold)
        if match is None:
            return EventSimilarityHit(threshold=self._similarity_threshold)
        return EventSimilarityHit(
            hit=match.hit,
            score=match.score,
            event_id=match.event_id,
            summary=match.summary,
            threshold=match.threshold,
        )
