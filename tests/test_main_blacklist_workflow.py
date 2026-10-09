from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import sentinel.main as main
from sentinel.config import PromptRenderError, SentinelSettings
from sentinel.models import EventSource, NormalizedEvent
from sentinel.pipeline.blacklist_gate import BlacklistGateResult


class FakePersonsStore:
    def __init__(self) -> None:
        self.appended: list[str] = []

    async def append_person(self, person_id: str) -> None:
        self.appended.append(person_id)


class FakeKeywordsStore:
    def __init__(self) -> None:
        self.appended: list[str] = []

    async def append_keyword(self, keyword: str) -> None:
        self.appended.append(keyword)


class FakeEventSamplesStore:
    def __init__(self) -> None:
        self.appended: list[tuple[str, str]] = []

    async def append_event(self, event_id: str, summary: str) -> None:
        self.appended.append((event_id, summary))


class FakeEventsStore:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str, list[str], datetime]] = []
        self.marked_event_ids: list[str] = []
        self.analysis_updates: list[tuple[str, dict]] = []

    async def stash_event(
        self,
        event_id: str,
        raw_content: str,
        person_ids: list[str],
        created_at: datetime | None = None,
    ) -> int:
        assert created_at is not None
        self.stored.append((event_id, raw_content, person_ids, created_at))
        return 1

    async def mark_events_graph_built(self, event_ids: list[str]) -> int:
        self.marked_event_ids.extend(event_ids)
        return len(event_ids)

    async def update_analysis_result(self, event_id: str, fields: dict) -> int:
        self.analysis_updates.append((event_id, fields))
        return 1


class FakeStoreBundle:
    def __init__(self) -> None:
        self.events = FakeEventsStore()
        self.persons = FakePersonsStore()
        self.keywords = FakeKeywordsStore()
        self.event_samples = FakeEventSamplesStore()
        self.close_count = 0
        self.aclose_count = 0

    def close(self) -> None:
        self.close_count += 1

    async def aclose(self) -> None:
        self.aclose_count += 1


class FakeFlow:
    instances: list["FakeFlow"] = []

    def __init__(
        self,
        app_settings,
        normalized_event,
        store_bundle,
        stash_store,
        id_numbers,
        observer=None,
    ) -> None:
        self.app_settings = app_settings
        self.normalized_event = normalized_event
        self.store_bundle = store_bundle
        self.stash_store = stash_store
        self.id_numbers = id_numbers
        self.observer = observer
        self.kicked_off = False
        self.state = {}
        FakeFlow.instances.append(self)

    async def kickoff_async(self) -> None:
        self.kicked_off = True


def make_settings() -> SentinelSettings:
    return SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
        milvus_uri="http://milvus.local:19530",
        milvus_input_events_collection="input_events",
        embedding_dim=3,
    )


def make_event(raw_content: str = "【P01# 张三】涉及制裁名单") -> NormalizedEvent:
    return NormalizedEvent(
        event_id="EVT-001",
        source=EventSource.NEWS,
        raw_content=raw_content,
        title="测试事件",
        summary="测试摘要",
        timestamp=datetime(2026, 6, 30, 10, 0, 0),
    )


@pytest.fixture(autouse=True)
def reset_fake_flow() -> None:
    FakeFlow.instances.clear()


async def patch_common(monkeypatch, event: NormalizedEvent):
    bundle = FakeStoreBundle()
    monkeypatch.setattr(
        main, "normalize_payload_to_event", AsyncMock(return_value=event)
    )
    monkeypatch.setattr(main, "create_store_bundle", lambda config: bundle)
    monkeypatch.setattr(main, "SentinelPipelineFlow", FakeFlow)
    return bundle


@pytest.mark.asyncio
async def test_keyword_pass_stores_event_and_starts_flow(monkeypatch) -> None:
    event = make_event()
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=True,
                matched_persons=[],
                matched_keywords=["制裁"],
                event_hit=False,
                id_numbers=["P01"],
            )
        ),
    )

    event_id = await main.process_message("原始输入", make_settings())

    assert event_id == "EVT-001"
    assert bundle.events.stored == [
        ("EVT-001", event.raw_content, ["P01"], event.timestamp)
    ]
    assert len(FakeFlow.instances) == 1
    assert FakeFlow.instances[0].kicked_off is True
    assert FakeFlow.instances[0].id_numbers == ["P01"]
    assert FakeFlow.instances[0].stash_store is bundle.events
    assert bundle.aclose_count == 1
    assert bundle.close_count == 0


@pytest.mark.asyncio
async def test_normalize_payload_accepts_string_source_without_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        main,
        "generate_pipeline_json",
        AsyncMock(
            return_value={
                "source": "string",
                "title": "文本线索",
                "timestamp": "2026-07-02T10:30:00+08:00",
                "structured_data": {"topic": "社区公告"},
                "trace_id": "trace-001",
                "content_type": "text",
                "event_type": "community_activity",
            }
        ),
    )

    event = await main.normalize_payload_to_event(
        {"data": "普通文本输入"},
        make_settings(),
    )

    assert event.source is EventSource.STRING
    assert event.title == "文本线索"
    assert event.raw_content == "普通文本输入"
    assert event.structured_data == {"topic": "社区公告"}
    assert event.trace_id == "trace-001"
    assert event.content_type == "text"
    assert event.event_type == "community_activity"


@pytest.mark.asyncio
async def test_normalize_payload_renders_profile_prompt(monkeypatch) -> None:
    captured_prompts: list[str] = []

    async def capture_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured_prompts.append(prompt)
        return {
            "source": "news",
            "timestamp": "2026-07-14T12:00:00+08:00",
        }

    monkeypatch.setattr(
        main,
        "generate_pipeline_json",
        capture_generate_pipeline_json,
    )

    await main.normalize_payload_to_event(
        {"data": "当前原始事件内容"},
        make_settings(),
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "当前原始事件内容" in prompt
    assert "source" in prompt
    assert "timestamp" in prompt
    assert "当前时间：" in prompt


@pytest.mark.asyncio
async def test_normalize_payload_propagates_prompt_render_error(monkeypatch) -> None:
    generate = AsyncMock()

    def raise_render_error(template, **values):
        raise PromptRenderError("normalization prompt is invalid")

    monkeypatch.setattr(main, "render_prompt", raise_render_error)
    monkeypatch.setattr(main, "generate_pipeline_json", generate)

    with pytest.raises(PromptRenderError, match="normalization prompt is invalid"):
        await main.normalize_payload_to_event(
            {"data": "待标准化事件"},
            make_settings(),
        )

    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_initializes_profile_before_external_work(
    monkeypatch,
) -> None:
    normalize = AsyncMock()
    create_stores = AsyncMock()
    monkeypatch.setattr(
        main,
        "get_profile_config",
        lambda: (_ for _ in ()).throw(RuntimeError("profile unavailable")),
    )
    monkeypatch.setattr(main, "normalize_payload_to_event", normalize)
    monkeypatch.setattr(main, "create_store_bundle", create_stores)

    with pytest.raises(RuntimeError, match="profile unavailable"):
        await main.process_message("原始输入", make_settings())

    normalize.assert_not_awaited()
    create_stores.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_initializes_profile_before_starting_service(monkeypatch) -> None:
    start_service = AsyncMock()
    monkeypatch.setattr(main, "setup_file_logging", lambda log_dir: "sentinel.log")
    monkeypatch.setattr(main, "get_settings", make_settings)
    monkeypatch.setattr(
        main,
        "get_profile_config",
        lambda: (_ for _ in ()).throw(RuntimeError("profile unavailable")),
    )
    monkeypatch.setattr(main, "start_service", start_service)
    monkeypatch.setattr(main.logging, "shutdown", lambda: None)
    monkeypatch.setattr("sys.argv", ["sentinel"])

    with pytest.raises(RuntimeError, match="profile unavailable"):
        await main.main()

    start_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_miss_stores_event_without_starting_flow(monkeypatch) -> None:
    event = make_event("普通事件，无黑名单命中")
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=False,
                matched_persons=[],
                matched_keywords=[],
                event_hit=False,
                id_numbers=[],
            )
        ),
    )

    event_id = await main.process_message("原始输入", make_settings())

    assert event_id == "EVT-001"
    assert bundle.events.stored == [("EVT-001", event.raw_content, [], event.timestamp)]
    assert FakeFlow.instances == []
    assert bundle.aclose_count == 1
    assert bundle.close_count == 0


@pytest.mark.asyncio
async def test_event_store_keeps_person_ids_person_only(monkeypatch) -> None:
    event = make_event(
        "【L17# 北京市海淀区】。【C11# 清河街道办事处】"
        "与【P04# 赵六】共同参与活动，另有 T02 编号。"
    )
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=False,
                matched_persons=[],
                matched_keywords=[],
                event_hit=False,
                id_numbers=["L17", "C11", "P04", "T02"],
            )
        ),
    )

    await main.process_message("原始输入", make_settings())

    assert bundle.events.stored == [
        ("EVT-001", event.raw_content, ["P04"], event.timestamp)
    ]


@pytest.mark.asyncio
async def test_person_and_event_sample_hits_are_recorded_before_flow(
    monkeypatch,
) -> None:
    event = make_event("【P05# 李四】与历史事件高度相似")
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=True,
                matched_persons=["P05"],
                matched_keywords=[],
                event_hit=True,
                id_numbers=["P05"],
            )
        ),
    )

    await main.process_message("原始输入", make_settings())

    assert bundle.persons.appended == ["P05"]
    assert bundle.event_samples.appended == [("EVT-001", "测试摘要")]
    assert bundle.events.stored == [
        ("EVT-001", event.raw_content, ["P05"], event.timestamp)
    ]
    assert FakeFlow.instances[0].kicked_off is True


@pytest.mark.asyncio
async def test_store_bundle_create_error_is_not_masked(monkeypatch) -> None:
    event = make_event()
    monkeypatch.setattr(
        main, "normalize_payload_to_event", AsyncMock(return_value=event)
    )

    def raise_milvus_error(config):
        raise RuntimeError("milvus unavailable")

    monkeypatch.setattr(main, "create_store_bundle", raise_milvus_error)

    with pytest.raises(RuntimeError, match="milvus unavailable"):
        await main.process_message("原始输入", make_settings())


@pytest.mark.asyncio
async def test_event_is_stored_before_blacklist_gate_errors(monkeypatch) -> None:
    event = make_event("【P06# 王五】待判定事件")
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(side_effect=RuntimeError("gate unavailable")),
    )

    with pytest.raises(RuntimeError, match="gate unavailable"):
        await main.process_message("原始输入", make_settings())

    assert bundle.events.stored == [
        ("EVT-001", event.raw_content, ["P06"], event.timestamp)
    ]
    assert FakeFlow.instances == []
    assert bundle.aclose_count == 1
    assert bundle.close_count == 0


@pytest.mark.asyncio
async def test_process_message_can_return_pipeline_result_for_stored_event(
    monkeypatch,
) -> None:
    event = make_event("普通事件，无黑名单命中")
    bundle = await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=False,
                matched_persons=[],
                matched_keywords=[],
                event_hit=False,
                id_numbers=[],
            )
        ),
    )

    result = await main.process_message(
        "原始输入",
        make_settings(),
        return_result=True,
    )

    assert result.event_id == "EVT-001"
    assert result.normalized_event is event
    assert result.entered_flow is False
    assert result.status == "stashed"
    assert result.trend_report is None
    assert bundle.events.stored == [("EVT-001", event.raw_content, [], event.timestamp)]
    assert bundle.events.analysis_updates[-1][0] == "EVT-001"
    assert bundle.events.analysis_updates[-1][1]["analysis_status"] == "stashed"


@pytest.mark.asyncio
async def test_process_message_observer_receives_key_stages(monkeypatch) -> None:
    event = make_event("普通事件，无黑名单命中")
    await patch_common(monkeypatch, event)
    monkeypatch.setattr(
        main,
        "evaluate_blacklist_gate",
        AsyncMock(
            return_value=BlacklistGateResult(
                should_proceed=False,
                matched_persons=[],
                matched_keywords=[],
                event_hit=False,
                id_numbers=[],
            )
        ),
    )
    updates: list[main.PipelineStageUpdate] = []

    class Observer:
        async def on_stage(self, update: main.PipelineStageUpdate) -> None:
            updates.append(update)

    await main.process_message(
        "原始输入",
        make_settings(),
        observer=Observer(),
    )

    assert [update.stage_key for update in updates] == [
        "normalize",
        "event_store",
        "blacklist_gate",
        "complete",
    ]
    assert updates[0].event_id == "EVT-001"
