"""测试 BlacklistFilter 三合一 OR 匹配逻辑。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sentinel.blacklist.filter import BlacklistFilter
from sentinel.blacklist.stores.event_samples_store import EventSampleMatch
from sentinel.models import EventSource, NormalizedEvent


@pytest.fixture
def mock_persons_store():
    store = MagicMock()
    store.query_person = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_keywords_store():
    store = MagicMock()
    store.query_keywords = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_samples_store():
    store = MagicMock()
    store.find_best_match = AsyncMock(return_value=None)
    return store


@pytest.fixture
def sample_event():
    return NormalizedEvent(
        event_id="E001",
        source=EventSource.NEWS,
        raw_content="【P01# 小明】被发现参与非法活动",
        title="测试事件",
        summary="小明参与非法活动",
    )


@pytest.fixture
def filter_instance(mock_persons_store, mock_keywords_store, mock_samples_store):
    return BlacklistFilter(
        persons_store=mock_persons_store,
        keywords_store=mock_keywords_store,
        samples_store=mock_samples_store,
        similarity_threshold=0.5,
    )


class TestBlacklistFilterPersonCheck:
    @pytest.mark.asyncio
    async def test_person_not_in_blacklist(
        self, filter_instance, mock_persons_store, sample_event
    ):
        """人员不在黑名单中不应命中。"""
        mock_persons_store.query_person.return_value = None
        hits = await filter_instance._check_persons(sample_event)
        assert hits == []

    @pytest.mark.asyncio
    async def test_person_in_blacklist(
        self, filter_instance, mock_persons_store, sample_event
    ):
        """人员在黑名单中应命中，但不在检查阶段自动累积。"""
        mock_persons_store.query_person.return_value = 1.0
        hits = await filter_instance._check_persons(sample_event)
        assert hits == ["P01"]

    @pytest.mark.asyncio
    async def test_no_person_in_text(self, filter_instance, mock_persons_store):
        """文本中无可识别人员 ID 应返回空。"""
        event = NormalizedEvent(
            event_id="E002",
            source=EventSource.NEWS,
            raw_content="今天天气很好，没有特定人员",
            title="无人员事件",
        )
        hits = await filter_instance._check_persons(event)
        assert hits == []


class TestBlacklistFilterKeywordCheck:
    @pytest.mark.asyncio
    async def test_no_keywords_in_db(
        self, filter_instance, mock_keywords_store, sample_event
    ):
        """敏感词库为空不应命中。"""
        mock_keywords_store.query_keywords.return_value = []
        result = await filter_instance._check_keywords(sample_event)
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_matches(
        self, filter_instance, mock_keywords_store, sample_event
    ):
        """内容包含敏感词应返回命中的关键词列表。"""
        mock_keywords_store.query_keywords.return_value = ["非法"]
        result = await filter_instance._check_keywords(sample_event)
        assert result == ["非法"]

    @pytest.mark.asyncio
    async def test_keyword_no_match(
        self, filter_instance, mock_keywords_store, sample_event
    ):
        """内容不包含敏感词不应命中。"""
        mock_keywords_store.query_keywords.return_value = ["无关词"]
        result = await filter_instance._check_keywords(sample_event)
        assert result == []


class TestBlacklistFilterEventSimilarity:
    @pytest.mark.asyncio
    async def test_no_events_in_db(
        self, filter_instance, mock_samples_store, sample_event
    ):
        """事件黑名单为空不应命中。"""
        mock_samples_store.find_best_match.return_value = None
        result = await filter_instance._check_event_similarity(sample_event)
        assert result is False

    @pytest.mark.asyncio
    async def test_event_match_found(
        self, filter_instance, mock_samples_store, sample_event
    ):
        """找到匹配事件应返回 True。"""
        mock_samples_store.find_best_match.return_value = EventSampleMatch(
            hit=True,
            score=0.9,
            event_id="E999",
            summary="highly similar event",
            threshold=0.5,
        )
        result = await filter_instance._check_event_similarity(sample_event)
        assert result is True


class TestBlacklistFilterCheck:
    @pytest.mark.asyncio
    async def test_all_miss_stash(
        self,
        filter_instance,
        mock_persons_store,
        mock_keywords_store,
        mock_samples_store,
        sample_event,
    ):
        """三维度均未命中应返回 STOP (False)。"""
        mock_persons_store.query_person.return_value = None
        mock_keywords_store.query_keywords.return_value = []
        mock_samples_store.find_best_match.return_value = None
        (
            should_proceed,
            matched_persons,
            matched_keywords,
            event_hit,
        ) = await filter_instance.check(sample_event)
        assert should_proceed is False
        assert matched_persons == []
        assert matched_keywords == []
        assert event_hit is False

    @pytest.mark.asyncio
    async def test_person_hit_pass(
        self,
        filter_instance,
        mock_persons_store,
        mock_keywords_store,
        mock_samples_store,
        sample_event,
    ):
        """人员命中应返回 PASS (True)。"""
        mock_persons_store.query_person.return_value = 1.0
        mock_keywords_store.query_keywords.return_value = []
        mock_samples_store.find_best_match.return_value = None
        (
            should_proceed,
            matched_persons,
            matched_keywords,
            event_hit,
        ) = await filter_instance.check(sample_event)
        assert should_proceed is True
        assert matched_persons == ["P01"]
        assert matched_keywords == []
        assert event_hit is False

    @pytest.mark.asyncio
    async def test_keyword_hit_pass(
        self,
        filter_instance,
        mock_persons_store,
        mock_keywords_store,
        mock_samples_store,
    ):
        """敏感词命中应返回 PASS。"""
        event = NormalizedEvent(
            event_id="E003",
            source=EventSource.NEWS,
            raw_content="某公司发布新产品",
            title="无人员事件",
        )
        mock_persons_store.query_person.return_value = None
        mock_keywords_store.query_keywords.return_value = ["新产品"]
        mock_samples_store.find_best_match.return_value = None
        (
            should_proceed,
            matched_persons,
            matched_keywords,
            event_hit,
        ) = await filter_instance.check(event)
        assert should_proceed is True
        assert matched_persons == []
        assert matched_keywords == ["新产品"]
        assert event_hit is False

    @pytest.mark.asyncio
    async def test_keyword_hit_pass_without_person_ids(
        self,
        filter_instance,
        mock_persons_store,
        mock_keywords_store,
        mock_samples_store,
    ):
        """无人员但命中敏感词时仍应 PASS。"""
        event = NormalizedEvent(
            event_id="E004",
            source=EventSource.NEWS,
            raw_content="某工业园区仓库发生爆炸，周边企业员工已紧急疏散。",
            title="爆炸事件",
        )
        mock_persons_store.query_person.return_value = None
        mock_keywords_store.query_keywords.return_value = ["爆炸", "制裁"]
        mock_samples_store.find_best_match.return_value = None

        (
            should_proceed,
            matched_persons,
            matched_keywords,
            event_hit,
        ) = await filter_instance.check(event)

        assert should_proceed is True
        assert matched_persons == []
        assert matched_keywords == ["爆炸"]
        assert event_hit is False


@pytest.mark.asyncio
async def test_event_similarity_uses_injected_samples_store(
    mock_persons_store, mock_keywords_store, mock_samples_store, sample_event
):
    """Event similarity check delegates to the injected samples store."""
    mock_persons_store.query_person.return_value = None
    mock_keywords_store.query_keywords.return_value = []
    mock_samples_store.find_best_match.return_value = EventSampleMatch(
        hit=True,
        score=0.91,
        event_id="E999",
        summary="highly similar event",
        threshold=0.5,
    )

    filter_instance = BlacklistFilter(
        persons_store=mock_persons_store,
        keywords_store=mock_keywords_store,
        samples_store=mock_samples_store,
        similarity_threshold=0.5,
    )

    assert await filter_instance._check_event_similarity(sample_event) is True
    mock_samples_store.find_best_match.assert_awaited_once_with(
        sample_event.raw_content,
        threshold=0.5,
    )
