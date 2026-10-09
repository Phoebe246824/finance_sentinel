from datetime import datetime

from sentinel.main import PipelineRunResult
from sentinel.models import EventSource, NormalizedEvent, RiskLevel
from sentinel.trend_prediction.service import TrendReport
from sentinel.web.repository import EventResultRepository
from sentinel.web.serialization import (
    pipeline_result_to_event_payload,
    row_to_event_payload,
)


def make_result() -> PipelineRunResult:
    event = NormalizedEvent(
        event_id="EVT-WEB",
        source=EventSource.NEWS,
        raw_content="P01 高风险事件",
        title="标题",
        event_type="负面舆情",
        summary="摘要",
        risk_level=RiskLevel.HIGH,
        risk_score=0.91,
        reasoning="推理",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        structured_data={"key_entities": [{"name": "P01", "type": "PERSON"}]},
    )
    report = TrendReport(
        raw_report="趋势预测报告",
        category="finance",
        category_name="金融",
        category_confidence=0.88,
        severity="major",
        severity_name="重大",
        severity_confidence=0.77,
        event_text=event.raw_content,
        context_text="",
        model="model",
        temperature=0.3,
    )
    return PipelineRunResult(
        event_id=event.event_id,
        normalized_event=event,
        status="analyzed",
        entered_flow=True,
        trend_report=report,
        graph_result={"entities_extracted": 2, "relations_created": 1},
        message="分析完成",
    )


def test_pipeline_result_to_event_payload_contains_real_fields():
    payload = pipeline_result_to_event_payload(make_result())

    assert payload.event_id == "EVT-WEB"
    assert payload.risk_level == "high"
    assert payload.risk_score == 0.91
    assert payload.trend_report.category_name == "金融"
    assert payload.trend_report.trend_prediction == "趋势预测报告"
    assert payload.key_entities == [{"name": "P01", "type": "PERSON"}]
    assert payload.graph_summary.entities_extracted == 2
    assert payload.graph_summary.relations_created == 1
    assert payload.graph_summary.raw == {
        "entities_extracted": 2,
        "relations_created": 1,
    }


def test_row_to_event_payload_round_trips_repository_fields():
    original = pipeline_result_to_event_payload(make_result())
    fields = EventResultRepository.payload_to_store_fields(original)
    row = {
        "event_id": original.event_id,
        "raw_content": original.raw_content,
        "created_at": "2026-01-01T12:00:00",
        "person_ids": ["P01"],
        "expire_at": "2026-04-01T12:00:00",
        "is_graph_built": True,
        **fields,
    }

    restored = row_to_event_payload(row)

    assert restored.event_id == original.event_id
    assert restored.summary == original.summary
    assert restored.trend_report.severity_name == "重大"
    assert restored.dimension_scores["risk"] == 0.91
    assert restored.graph_summary.entities_extracted == 2
    assert restored.graph_summary.relations_created == 1


def test_row_to_event_payload_defaults_missing_graph_summary():
    restored = row_to_event_payload(
        {
            "event_id": "EVT-LEGACY",
            "analysis_status": "analyzed",
            "source": "news",
            "event_type": "负面舆情",
            "risk_level": "low",
            "risk_score": 0.1,
            "summary": "legacy",
            "raw_content": "legacy raw",
            "event_timestamp": "2026-01-01T12:00:00",
            "trend_report_json": "{}",
        }
    )

    assert restored.graph_summary.success is None
    assert restored.graph_summary.entities_extracted == 0
    assert restored.graph_summary.relations_created == 0
    assert restored.graph_summary.raw == {}


def test_pipeline_result_to_event_payload_normalizes_graph_summary_counts():
    result = make_result()
    result.graph_result = {
        "success": True,
        "entities_extracted": "3",
        "relations_created": 4,
        "group_id": "sentinel",
        "fetched_count": 5,
        "eligible_count": 2,
        "batched_count": 1,
        "skipped_irrelevant_count": 6,
        "skipped_existing_count": 7,
    }

    payload = pipeline_result_to_event_payload(result)

    assert payload.graph_summary.success is True
    assert payload.graph_summary.entities_extracted == 3
    assert payload.graph_summary.relations_created == 4
    assert payload.graph_summary.group_id == "sentinel"
    assert payload.graph_summary.fetched_count == 5
    assert payload.graph_summary.eligible_count == 2
    assert payload.graph_summary.batched_count == 1
    assert payload.graph_summary.skipped_irrelevant_count == 6
    assert payload.graph_summary.skipped_existing_count == 7
    assert payload.graph_summary.raw == result.graph_result


def test_pipeline_result_to_event_payload_omits_batch_results_from_graph_summary():
    result = make_result()
    result.graph_result = {
        "entities_extracted": 3,
        "relations_created": 4,
        "batch_results": [{"event_id": "EVT-1", "content": "verbose"}],
    }

    payload = pipeline_result_to_event_payload(result)
    fields = EventResultRepository.payload_to_store_fields(payload)
    restored = row_to_event_payload(
        {
            "event_id": payload.event_id,
            "raw_content": payload.raw_content,
            "created_at": "2026-01-01T12:00:00",
            "person_ids": ["P01"],
            "expire_at": "2026-04-01T12:00:00",
            "is_graph_built": True,
            **fields,
        }
    )

    assert "batch_results" not in payload.graph_summary.raw
    assert "batch_results" not in restored.graph_summary.raw


def test_row_to_event_payload_clamps_legacy_stashed_risk_fields():
    restored = row_to_event_payload(
        {
            "event_id": "EVT-LEGACY-STASH",
            "analysis_status": "stashed",
            "source": "news",
            "event_type": "未触发",
            "risk_level": "medium",
            "risk_score": 0.5,
            "summary": "legacy",
            "raw_content": "legacy raw",
            "event_timestamp": "2026-01-01T12:00:00",
            "dimension_scores_json": '{"risk":0.5}',
            "trend_report_json": "{}",
        }
    )

    assert restored.risk_level == "unassessed"
    assert restored.risk_score == 0.0
    assert restored.dimension_scores == {}


def test_stashed_result_has_explicit_not_triggered_trend_report():
    event = NormalizedEvent(
        event_id="EVT-STASH",
        source=EventSource.NEWS,
        raw_content="普通事件",
        title="",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )
    result = PipelineRunResult(
        event_id="EVT-STASH",
        normalized_event=event,
        status="stashed",
        entered_flow=False,
        message="事件未命中黑名单，已写入 Milvus 事件库",
    )

    payload = pipeline_result_to_event_payload(result)

    assert payload.event_type == "未触发"
    assert payload.analysis_status == "stashed"
    assert payload.risk_level == "unassessed"
    assert payload.risk_score == 0.0
    assert payload.dimension_scores == {}
    assert payload.trend_report.trend_prediction == "未触发趋势预测"
    assert payload.reasoning == "事件未命中黑名单，已写入 Milvus 事件库"


def test_pipeline_result_to_event_payload_converts_legacy_entity_mapping():
    event = NormalizedEvent(
        event_id="EVT-LEGACY",
        source=EventSource.NEWS,
        raw_content="某公司发布召回公告",
        title="召回公告",
        event_type="负面舆情",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        structured_data={"company": "某公司", "person": ["张三", "李四"]},
    )
    result = PipelineRunResult(
        event_id=event.event_id,
        normalized_event=event,
        status="analyzed",
        entered_flow=True,
        message="分析完成",
    )

    payload = pipeline_result_to_event_payload(result)

    assert payload.key_entities == [
        {"name": "某公司", "type": "COMPANY"},
        {"name": "张三", "type": "PERSON"},
        {"name": "李四", "type": "PERSON"},
    ]


def test_payload_to_store_fields_keeps_json_valid_when_trend_report_is_long():
    event = make_result()
    payload = pipeline_result_to_event_payload(event)
    payload.trend_report.intent_analysis = "意图" * 6000
    payload.trend_report.trend_prediction = "趋势" * 6000

    fields = EventResultRepository.payload_to_store_fields(payload)
    row = {
        "event_id": payload.event_id,
        "raw_content": payload.raw_content,
        "created_at": "2026-01-01T12:00:00",
        "person_ids": [],
        "expire_at": "2026-04-01T12:00:00",
        "is_graph_built": True,
        **fields,
    }

    restored = row_to_event_payload(row)

    assert restored.trend_report.intent_analysis
    assert restored.trend_report.trend_prediction


def test_payload_to_store_fields_truncates_pipeline_message_by_utf8_bytes():
    event = make_result()
    payload = pipeline_result_to_event_payload(event)
    payload.reasoning = "风" * 1000

    fields = EventResultRepository.payload_to_store_fields(payload)

    assert len(str(fields["pipeline_message"]).encode("utf-8")) <= 512


def test_repository_caps_rows_for_list_and_overview():
    class CapturingStore:
        def __init__(self) -> None:
            self.limits: list[int | None] = []
            self.output_fields: list[list[str] | None] = []

        def list_analysis_rows(
            self,
            *,
            limit=10000,
            source=None,
            risk_level=None,
            event_type=None,
            output_fields=None,
        ):
            del source, risk_level, event_type
            self.limits.append(limit)
            self.output_fields.append(output_fields)
            return []

    store = CapturingStore()
    repository = EventResultRepository(store)  # type: ignore[arg-type]

    repository.list_results(page=1, page_size=20)
    repository.overview()

    assert store.limits == [5001, 5001]
    assert store.output_fields == [None, None]


def test_repository_marks_truncated_results_and_excludes_unassessed_risk():
    class CappedStore:
        def list_analysis_rows(
            self,
            *,
            limit=10000,
            source=None,
            risk_level=None,
            event_type=None,
            output_fields=None,
        ):
            del limit, source, risk_level, event_type, output_fields
            return [
                _analysis_row("EVT-HIGH", "analyzed", "high", 0.91),
                _analysis_row("EVT-STASH", "stashed", "unassessed", 0.0),
                _analysis_row("EVT-LOW", "analyzed", "low", 0.2),
            ]

    repository = EventResultRepository(CappedStore(), row_limit=2)  # type: ignore[arg-type]

    page = repository.list_results(page=1, page_size=10)
    overview = repository.overview()

    assert page.truncated is True
    assert [event.event_id for event in page.items] == ["EVT-HIGH", "EVT-STASH"]
    assert page.items[1].risk_level == "unassessed"
    assert overview.truncated is True
    assert overview.risk_distribution == {"high": 1, "medium": 0, "low": 0}
    assert overview.stats.unassessed_count == 1
    assert overview.stats.data_truncated is True


def test_repository_keyword_search_requests_full_fields_for_raw_content_match():
    class KeywordStore:
        WEB_OUTPUT_FIELDS = ["event_id", "raw_content", "summary"]

        def __init__(self) -> None:
            self.output_fields: list[list[str] | None] = []

        def list_analysis_rows(
            self,
            *,
            limit=10000,
            source=None,
            risk_level=None,
            event_type=None,
            output_fields=None,
        ):
            del limit, source, risk_level, event_type
            self.output_fields.append(output_fields)
            row = _analysis_row("EVT-RAW", "analyzed", "medium", 0.5)
            row["raw_content"] = "raw-only-keyword appears here"
            row["summary"] = "summary without the token"
            return [row]

    store = KeywordStore()
    repository = EventResultRepository(store)  # type: ignore[arg-type]

    page = repository.list_results(
        page=1,
        page_size=20,
        keyword="raw-only-keyword",
    )

    assert store.output_fields == [KeywordStore.WEB_OUTPUT_FIELDS]
    assert [event.event_id for event in page.items] == ["EVT-RAW"]


def test_events_store_list_analysis_rows_uses_lightweight_projection_by_default():
    class CapturingStore:
        WEB_LIST_OUTPUT_FIELDS = ["event_id", "summary"]
        WEB_OUTPUT_FIELDS = ["event_id", "raw_content", "reasoning"]

        def __init__(self) -> None:
            self.queries: list[tuple[list[str], int]] = []

        def _analysis_rows_filter(self, **kwargs):
            del kwargs
            return 'analysis_status == "analyzed"'

        def query_rows(self, filter_expr, output_fields, *, limit=None):
            del filter_expr
            self.queries.append((output_fields, limit))
            return []

    from sentinel.blacklist.stores.events_store import EventsStore

    store = CapturingStore()
    EventsStore.list_analysis_rows(store, limit=25)  # type: ignore[arg-type]

    assert store.queries == [(["event_id", "summary"], 25)]


def _analysis_row(
    event_id: str,
    status: str,
    risk_level: str,
    risk_score: float,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "analysis_status": status,
        "raw_content": f"{event_id} raw",
        "created_at": "2026-01-01T12:00:00",
        "source": "news",
        "event_type": "负面舆情" if status == "analyzed" else "未触发",
        "risk_level": risk_level,
        "risk_score": risk_score,
        "summary": event_id,
        "reasoning": "",
        "event_timestamp": "2026-01-01T12:00:00",
        "key_entities_json": "[]",
        "dimension_scores_json": "{}",
        "trend_report_json": "{}",
    }
