"""Tests for trend prediction service behavior and optional RAGFlow evidence."""

from datetime import datetime

import pytest

from sentinel.config import PromptRenderError, SentinelSettings
from sentinel.models import EventSource, NormalizedEvent, RiskLevel
from sentinel.ragflow.client import RagflowApiError
from sentinel.trend_prediction.classification_taxonomy import (
    CATEGORY_NAMES,
    SEVERITY_NAMES,
    SEVERITY_TO_TIME_RANGES,
)
from sentinel.trend_prediction.service import (
    TrendPredictionConfig,
    TrendReport,
    run_trend_prediction,
)


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_model": "gpt-test",
        "llm_base_url": "https://llm.example/v1",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_run_trend_prediction_uses_litellm_generate_text(monkeypatch):
    calls = []

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        calls.append(
            {
                "settings": settings,
                "prompt": prompt,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        if len(calls) == 1:
            return "意图分析结果"
        return "趋势预测报告：风险将在短期内收敛。"

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )

    settings = make_settings()
    report = await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        "某地发生危险化学品泄漏。",
        app_settings=settings,
    )

    assert isinstance(report, TrendReport)
    assert report.raw_report.startswith("趋势预测报告")
    assert report.category == "public_safety"
    assert report.severity == "severe"
    assert len(calls) == 2
    assert all(call["settings"] is settings for call in calls)
    assert calls[0]["kwargs"]["model"] == "gpt-test"
    assert calls[0]["kwargs"]["api_key"] == "llm-secret"
    assert calls[0]["kwargs"]["base_url"] == "https://llm.example/v1"
    assert calls[0]["kwargs"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_run_trend_prediction_keeps_display_metadata(monkeypatch):
    captured_prompts: list[str] = []

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        if len(captured_prompts) == 1:
            return "意图分析结果"
        return "趋势预测报告：短期关注舆情扩散，中期关注监管响应。"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(
            use_rerank=False,
            temperature=0.0,
            event_metadata_text="事件类型: 公共安全\n风险等级: high\n风险分数: 0.90",
        ),
        "某地发生危险化学品泄漏，消防部门已到场处置。",
        app_settings=make_settings(),
    )

    assert report.category_name == "公共安全"
    assert report.severity_name == "严重"
    assert "风险等级: high" in captured_prompts[0]
    assert "意图分析结果" in captured_prompts[1]


@pytest.mark.asyncio
async def test_run_trend_prediction_selects_public_safety_profile_prompts(monkeypatch):
    captured_prompts: list[str] = []

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        if len(captured_prompts) == 1:
            return "intent"
        return "trend"

    async def fake_classify(self, event_text):
        return ("public_safety", 0.81, "severe", 0.72)

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        "event text",
        app_settings=make_settings(),
    )

    assert "公共安全意图分析报告" in captured_prompts[0]
    assert "公共安全趋势预测报告" in captured_prompts[1]
    assert "严重" in captured_prompts[1]
    assert all(
        value in captured_prompts[1]
        for value in SEVERITY_TO_TIME_RANGES["severe"].values()
    )


@pytest.mark.parametrize(
    ("category", "intent_marker", "trend_marker"),
    [
        ("intl_politics", "权力结构分析", "联盟重组"),
        ("tech", "技术生态分析", "技术突破"),
        ("economy", "贸易/产业/金融影响分析", "经济复苏"),
        ("society", "社会结构影响分析", "社会和解"),
        ("public_health", "治理体系影响分析", "常态化防控"),
        ("public_safety", "人员-地点-物料-通信链条", "危险物料聚集"),
        ("energy", "能源结构影响分析", "能源转型加速"),
        (
            "finance",
            "客户/商户：[立场和态度]",
            "路径A（风险收敛）：[概率]",
        ),
    ],
)
@pytest.mark.asyncio
async def test_run_trend_prediction_routes_each_category_to_its_profile_prompts(
    monkeypatch,
    category: str,
    intent_marker: str,
    trend_marker: str,
) -> None:
    captured_prompts: list[str] = []

    async def fake_classify(self, event_text):
        return (category, 0.81, "moderate", 0.72)

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        return "report"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        "event text",
        app_settings=make_settings(),
    )

    assert report.category == category
    assert report.category_name == CATEGORY_NAMES[category]
    assert intent_marker in captured_prompts[0]
    assert trend_marker in captured_prompts[1]


@pytest.mark.asyncio
async def test_unknown_category_normalizes_to_general_profile(monkeypatch):
    prompts: list[str] = []

    async def fake_classify(self, event_text):
        return ("unknown_category", 0.42, "moderate", 0.73)

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        prompts.append(prompt or "")
        return "report"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False),
        "event text",
        app_settings=make_settings(),
    )

    assert report.category == "general"
    assert report.category_name == "通用"
    assert report.category_confidence == pytest.approx(1.0)
    assert "# 意图分析报告" in prompts[0]
    assert "# 趋势预测报告" in prompts[1]
    assert "公共安全" not in "\n".join(prompts)


@pytest.mark.asyncio
async def test_run_trend_prediction_injects_ragflow_dashboard_section(
    monkeypatch,
):
    captured_prompts: list[str] = []

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        assert stage == "dashboard"
        return {
            "chunks": [
                {
                    "content": "Emergency response note: temporary shelter capacity is limited.",
                    "document_name": "incident-response.pdf",
                    "score": 0.91,
                }
            ]
        }

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        if len(captured_prompts) == 1:
            return "意图分析结果"
        return "趋势预测报告"

    event = NormalizedEvent(
        event_id="evt-ragflow",
        source=EventSource.NEWS,
        raw_content="某地强降雨导致临时安置点容量紧张。",
        timestamp=datetime(2026, 7, 1, 10, 0, 0),
        event_type="负面舆情",
        risk_level=RiskLevel.HIGH,
        risk_score=0.91,
    )

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.retrieve_event_knowledge",
        fake_retrieve_event_knowledge,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        event.raw_content,
        app_settings=make_settings(),
        source_event=event,
    )

    assert "RAGFlow external knowledge reference:" in captured_prompts[0]
    assert "Emergency response note" in captured_prompts[0]
    assert "untrusted reference evidence" in captured_prompts[0]
    assert "RAGFlow external knowledge reference:" in captured_prompts[1]
    assert "意图分析结果" in captured_prompts[1]


@pytest.mark.asyncio
async def test_run_trend_prediction_skips_ragflow_without_source_event(
    monkeypatch,
):
    captured_prompts: list[str] = []

    async def fail_retrieve_event_knowledge(app_settings, event, *, stage):
        raise AssertionError("RAGFlow retrieval requires a source event")

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        return "报告"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.retrieve_event_knowledge",
        fail_retrieve_event_knowledge,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        "某地强降雨导致临时安置点容量紧张。",
        app_settings=make_settings(),
    )

    assert all(
        "RAGFlow external knowledge reference:" not in prompt
        for prompt in captured_prompts
    )


@pytest.mark.asyncio
async def test_run_trend_prediction_ignores_ragflow_failure_and_still_generates(
    monkeypatch,
):
    captured_prompts: list[str] = []

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        raise RagflowApiError(code=500, message="ragflow unavailable")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        if len(captured_prompts) == 1:
            return "意图分析结果"
        return "趋势预测报告"

    event = NormalizedEvent(
        event_id="evt-ragflow-failure",
        source=EventSource.NEWS,
        raw_content="某地强降雨导致临时安置点容量紧张。",
        timestamp=datetime(2026, 7, 1, 10, 0, 0),
        event_type="负面舆情",
        risk_level=RiskLevel.HIGH,
        risk_score=0.91,
    )

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.retrieve_event_knowledge",
        fake_retrieve_event_knowledge,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(use_rerank=False, temperature=0.0),
        event.raw_content,
        app_settings=make_settings(),
        source_event=event,
    )

    assert report.raw_report == "趋势预测报告"
    assert len(captured_prompts) == 2
    assert all(
        "RAGFlow external knowledge reference:" not in prompt
        for prompt in captured_prompts
    )


@pytest.mark.asyncio
async def test_run_trend_prediction_propagates_fail_closed_ragflow_errors(
    monkeypatch,
):
    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        raise RagflowApiError(code=500, message="ragflow unavailable")

    async def fail_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        raise AssertionError("fail-closed retrieval errors must stop before LLM")

    event = NormalizedEvent(
        event_id="evt-ragflow-fail-closed",
        source=EventSource.NEWS,
        raw_content="某地强降雨导致临时安置点容量紧张。",
        timestamp=datetime(2026, 7, 1, 10, 0, 0),
        event_type="负面舆情",
        risk_level=RiskLevel.HIGH,
        risk_score=0.91,
    )

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.retrieve_event_knowledge",
        fake_retrieve_event_knowledge,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fail_generate_text
    )

    with pytest.raises(RagflowApiError):
        await run_trend_prediction(
            TrendPredictionConfig(use_rerank=False, temperature=0.0),
            event.raw_content,
            app_settings=make_settings(ragflow_fail_open=False),
            source_event=event,
        )


@pytest.mark.asyncio
async def test_zero_shot_with_source_event_skips_ragflow(monkeypatch):
    calls = []

    async def fail_retrieve_event_knowledge(app_settings, event, *, stage):
        raise AssertionError("zero-shot baseline must not retrieve external evidence")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        calls.append(prompt or "")
        return "零样本趋势预测报告"

    event = NormalizedEvent(
        event_id="evt-zero-shot",
        source=EventSource.NEWS,
        raw_content="某地强降雨导致临时安置点容量紧张。",
        timestamp=datetime(2026, 7, 1, 10, 0, 0),
        event_type="负面舆情",
        risk_level=RiskLevel.HIGH,
        risk_score=0.91,
    )

    monkeypatch.setattr(
        "sentinel.trend_prediction.service.retrieve_event_knowledge",
        fail_retrieve_event_knowledge,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    await run_trend_prediction(
        TrendPredictionConfig(zero_shot=True, use_rerank=False, temperature=0.0),
        event.raw_content,
        app_settings=make_settings(),
        source_event=event,
    )

    # zero-shot 只调用一次 LLM（不分类、不注入历史/知识）
    assert len(calls) == 1
    zero_shot_prompt = calls[0]
    # 事件正文进入 prompt
    assert "强降雨" in zero_shot_prompt
    # zero-shot 不得注入 RAGFlow 知识段或分类上下文
    assert "RAGFlow external knowledge reference:" not in zero_shot_prompt
    assert "当前事件分类" not in zero_shot_prompt


@pytest.mark.asyncio
async def test_zero_shot_bypasses_classifier(monkeypatch):
    calls = []

    async def fail_classify(self, event_text):
        raise AssertionError("zero-shot baseline must not classify events")

    def fail_get_profile_config():
        raise AssertionError("zero-shot baseline must not load profile prompts")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        calls.append(prompt or "")
        return "零样本趋势预测报告"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fail_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.get_profile_config",
        fail_get_profile_config,
        raising=False,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(zero_shot=True, use_rerank=False, temperature=0.0),
        "某地发生危险化学品泄漏，消防部门已到场处置。",
        app_settings=make_settings(),
    )

    assert report.category == "general"
    assert report.category_name == "通用"
    assert report.severity == "moderate"
    assert report.severity_name == SEVERITY_NAMES["moderate"]
    # 绕过分类器：只有一次 LLM 调用，且 prompt 不含分类上下文
    assert len(calls) == 1
    assert "当前事件分类" not in calls[0]


@pytest.mark.asyncio
async def test_forced_category_and_severity_bypass_classifier(monkeypatch):
    prompts: list[str] = []

    async def fail_classify(self, event_text):
        raise AssertionError("forced labels must not classify events")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        prompts.append(prompt or "")
        return "趋势预测报告"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fail_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(
            use_rerank=False,
            temperature=0.0,
            force_category="public_safety",
            force_severity="severe",
        ),
        "某地发生危险化学品泄漏，消防部门已到场处置。",
        app_settings=make_settings(),
    )

    assert report.category == "public_safety"
    assert report.severity == "severe"
    assert "公共安全意图分析报告" in prompts[0]
    assert "公共安全趋势预测报告" in prompts[1]


@pytest.mark.asyncio
async def test_forced_category_without_severity_bypasses_classifier(monkeypatch):
    async def fail_classify(self, event_text):
        raise AssertionError("forced category must not classify events")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, prompt, messages, kwargs
        return "趋势预测报告"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fail_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(
            use_rerank=False,
            temperature=0.0,
            force_category="general",
            force_category_confidence=0.9,
        ),
        "某地发布公共服务调整公告。",
        app_settings=make_settings(),
    )

    assert report.category == "general"
    assert report.category_confidence == pytest.approx(0.9)
    assert report.severity == "moderate"
    assert report.severity_confidence == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_forced_unknown_category_normalizes_to_general(monkeypatch):
    prompts: list[str] = []

    async def fail_classify(self, event_text):
        raise AssertionError("forced category must not classify events")

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        prompts.append(prompt or "")
        return "report"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fail_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(force_category="missing", use_rerank=False),
        "event text",
        app_settings=make_settings(),
    )

    assert report.category == "general"
    assert report.category_name == "通用"
    assert report.category_confidence == pytest.approx(1.0)
    assert "# 意图分析报告" in prompts[0]


@pytest.mark.asyncio
async def test_prompt_only_keeps_classification_context_with_fallback_prompts(
    monkeypatch,
):
    captured_prompts: list[str] = []

    async def fake_classify(self, event_text):
        return ("public_safety", 0.80, "severe", 0.70)

    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        del settings, messages, kwargs
        captured_prompts.append(prompt or "")
        return "趋势预测报告"

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fake_generate_text
    )

    report = await run_trend_prediction(
        TrendPredictionConfig(
            use_rerank=False,
            temperature=0.0,
            use_adaptive_prompts=False,
        ),
        "某地发生危险化学品泄漏，消防部门已到场处置。",
        app_settings=make_settings(),
    )

    assert report.category == "public_safety"
    assert "当前事件分类：公共安全" in captured_prompts[0]
    assert "# 意图分析报告" in captured_prompts[0]
    assert "公共安全意图分析报告" not in captured_prompts[0]


@pytest.mark.asyncio
async def test_prompt_render_error_stops_before_model_calls(monkeypatch):
    async def fake_classify(self, event_text):
        return ("public_safety", 0.8, "severe", 0.7)

    async def fail_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        raise AssertionError("invalid prompts must stop before model generation")

    def fail_render_prompt(template, **values):
        raise PromptRenderError("invalid dashboard prompt")

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.EventClassifier.classify_with_severity",
        fake_classify,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.task_templates.render_prompt",
        fail_render_prompt,
        raising=False,
    )
    monkeypatch.setattr(
        "sentinel.trend_prediction.service.generate_text", fail_generate_text
    )

    with pytest.raises(PromptRenderError, match="invalid dashboard prompt"):
        await run_trend_prediction(
            TrendPredictionConfig(use_rerank=False),
            "event text",
            app_settings=make_settings(),
        )


@pytest.mark.asyncio
async def test_simulate_dashboard_prints_localized_labels_and_risk_metadata(
    monkeypatch,
    capsys,
):
    from sentinel.pipeline import dashboard

    async def fake_run_trend_prediction(
        config,
        event_text,
        context_text="",
        *,
        source_event=None,
        **kwargs,
    ):
        del kwargs
        assert source_event is event
        assert "事件类型: 公共安全" in config.event_metadata_text
        assert "风险等级: high" in config.event_metadata_text
        assert "风险分数: 0.90" in config.event_metadata_text
        return TrendReport(
            raw_report="趋势预测报告",
            category="public_safety",
            category_name="公共安全",
            category_confidence=0.8,
            severity="severe",
            severity_name="严重",
            severity_confidence=0.7,
            event_text=event_text,
            context_text=context_text,
            model=None,
            temperature=0.3,
        )

    event = NormalizedEvent(
        event_id="evt-1",
        source=EventSource.CHAT,
        raw_content="某地发生危险化学品泄漏，消防部门已到场处置。",
        timestamp=datetime(2026, 1, 10),
        event_type="公共安全",
        risk_level=RiskLevel.HIGH,
        risk_score=0.9,
    )
    monkeypatch.setattr(dashboard, "run_trend_prediction", fake_run_trend_prediction)
    monkeypatch.setattr(dashboard, "print_info", lambda message: print(message))

    await dashboard.execute_dashboard({}, event, {})

    output = capsys.readouterr().out
    assert "事件分类: 公共安全" in output
    assert "影响严重度: 严重" in output


@pytest.mark.parametrize(
    ("raw", "expected_value"),
    [
        ("HIGH", "high"),
        (" high ", "high"),
        ("Low", "low"),
        ("medium", "medium"),
        (None, "medium"),
        ("nonsense", "medium"),
    ],
)
def test_parse_risk_level_normalizes_input(raw, expected_value):
    from sentinel.pipeline.risk import parse_risk_level

    assert parse_risk_level(raw).value == expected_value


def test_parse_risk_level_passes_through_enum():
    from sentinel.models import RiskLevel
    from sentinel.pipeline.risk import parse_risk_level

    assert parse_risk_level(RiskLevel.HIGH) is RiskLevel.HIGH
