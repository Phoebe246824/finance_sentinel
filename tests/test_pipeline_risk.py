"""Tests for risk pipeline evaluation and RAGFlow enrichment."""

from datetime import datetime

import pytest

from sentinel.config import PromptRenderError, SentinelSettings
from sentinel.models import EventSource, NormalizedEvent, RiskLevel
from sentinel.pipeline import risk
from sentinel.ragflow.client import RagflowApiError
from tests.test_profile_config import write_profile


@pytest.fixture(autouse=True)
def isolate_profile_config_cache():
    import sentinel.config.profile as profile_module

    profile_module.reset_profile_config_cache()
    yield
    profile_module.reset_profile_config_cache()


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j",
        "llm_api_key": "llm",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def make_event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="EVT-RISK",
        source=EventSource.NEWS,
        raw_content="风险事件",
        title="风险事件",
        summary="存在风险",
        event_type="负面舆情",
        structured_data={"person": "张三"},
        timestamp=datetime(2026, 6, 30, 10, 0, 0),
    )


def test_parse_risk_level_defaults_unknown_values_to_medium() -> None:
    assert risk.parse_risk_level("high") is RiskLevel.HIGH
    assert risk.parse_risk_level(RiskLevel.LOW) is RiskLevel.LOW
    assert risk.parse_risk_level("unknown") is RiskLevel.MEDIUM
    assert risk.parse_risk_level(None) is RiskLevel.MEDIUM


def test_build_related_events_context_accepts_dict_items_and_objects() -> None:
    class Episode:
        content = "episode content"

    context = risk.build_related_events_context(
        {
            "reranked_edges": [{"text": "edge fact"}],
            "reranked_episodes": [Episode()],
        }
    )

    assert context == "[edge] edge fact\n[episode] episode content"


def test_build_related_events_context_filters_current_event_text() -> None:
    current_text = "2026年6月12日 客户A 向账户B 转账 49000 元"

    context = risk.build_related_events_context(
        {
            "reranked_edges": [{"text": "客户A 历史命中过分拆交易模式"}],
            "reranked_episodes": [
                {"text": current_text},
                {"text": f"Episode content: {current_text}"},
            ],
        },
        current_event_text=current_text,
    )

    assert context == "[edge] 客户A 历史命中过分拆交易模式"


@pytest.mark.asyncio
async def test_evaluate_risk_normalizes_llm_risk_level_to_enum(monkeypatch) -> None:
    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        assert "Event type" in prompt
        assert temperature == 0.1
        return {"risk_level": "high", "risk_score": "0.91", "reasoning": "需跟进"}

    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.evaluate_risk(make_settings(), make_event())

    assert result["risk_level"] is RiskLevel.HIGH
    assert result["risk_score"] == pytest.approx(0.91)
    assert result["reasoning"] == "需跟进"


@pytest.mark.asyncio
async def test_evaluate_risk_uses_profile_prompt_and_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    write_profile(tmp_path)
    (tmp_path / "prompts/pipeline/risk_first.md").write_text(
        """# Risk first configured marker

Base the first assessment on the current event and separate confirmed facts from uncertain signals.

Configured risk dimensions: {risk_dimensions}
Event type: {event_type}
Event summary: {event_summary}
Key entities: {key_entities}
Event time: {event_time}
Source: {source}
Related event context: {related_events}
{output_schema}
""",
        encoding="utf-8",
    )
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    profile = profile_module.get_profile_config()
    monkeypatch.setattr(risk, "get_profile_config", lambda: profile)
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {
            "risk_level": "high",
            "risk_score": 0.91,
            "reasoning": "profile risk",
            "dimension_scores": {"urgency": 0.8, "credibility": 0.7},
        }

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.evaluate_risk(
        make_settings(),
        make_event(),
        {"reranked_edges": [{"text": "existing graph fact"}]},
    )

    assert result["dimension_scores"] == {
        "urgency": pytest.approx(0.8),
        "credibility": pytest.approx(0.7),
    }
    prompt = captured["prompt"]
    assert "# Risk first configured marker" in prompt
    assert "Base the first assessment on the current event" in prompt
    assert "separate confirmed facts from uncertain signals" in prompt
    assert "urgency: How quickly the event needs attention." in prompt
    assert "credibility: How reliable the reported evidence is." in prompt
    assert "Event type: 负面舆情" in prompt
    assert "Event summary: 存在风险" in prompt
    assert "Key entities: {'person': '张三'}" in prompt
    assert "Event time: 2026-06-30 10:00:00" in prompt
    assert "Source: EventSource.NEWS" in prompt
    assert "Related event context: [edge] existing graph fact" in prompt
    assert "Return strict JSON with this shape" in prompt
    assert "dimension_scores:{urgency:number,credibility:number}" in prompt
    assert "history_context_analysis:{used_context:boolean" in prompt
    assert "recommended_actions:list[string]" in prompt
    assert "customer_identity" not in prompt


@pytest.mark.asyncio
async def test_second_evaluate_risk_uses_profile_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    write_profile(tmp_path)
    (tmp_path / "prompts/pipeline/risk_second.md").write_text(
        """# Risk second configured marker

Compare the current event with related past events and update scores only when the risk picture changes.

Configured risk dimensions: {risk_dimensions}
Event type: {event_type}
Event summary: {event_summary}
Key entities: {key_entities}
Event time: {event_time}
Source: {source}
Related event context: {related_events}
{output_schema}
""",
        encoding="utf-8",
    )
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    profile = profile_module.get_profile_config()
    monkeypatch.setattr(risk, "get_profile_config", lambda: profile)
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {"risk_level": "medium", "risk_score": 0.5, "reasoning": "second"}

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    await risk.second_evaluate_risk(
        make_settings(),
        make_event(),
        {"reranked_edges": [{"text": "existing graph fact"}]},
    )

    prompt = captured["prompt"]
    assert "# Risk second configured marker" in prompt
    assert "Compare the current event with related past events" in prompt
    assert "update scores only when the risk picture changes" in prompt
    assert "Related event context: [edge] existing graph fact" in prompt
    assert "Return strict JSON with this shape" in prompt
    assert "risk_level:string" in prompt
    assert "recommended_actions:list[string]" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("evaluation", [risk.evaluate_risk, risk.second_evaluate_risk])
async def test_risk_evaluation_propagates_prompt_render_error(
    monkeypatch,
    evaluation,
) -> None:
    render_error = PromptRenderError("invalid risk prompt")

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    def fail_render_prompt(*args, **kwargs):
        raise render_error

    async def fail_generate_pipeline_json(*args, **kwargs):
        raise AssertionError("model must not run after prompt rendering fails")

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "render_prompt", fail_render_prompt)
    monkeypatch.setattr(risk, "generate_pipeline_json", fail_generate_pipeline_json)

    with pytest.raises(PromptRenderError) as exc_info:
        if evaluation is risk.evaluate_risk:
            await evaluation(make_settings(), make_event())
        else:
            await evaluation(make_settings(), make_event(), {})

    assert exc_info.value is render_error


@pytest.mark.asyncio
@pytest.mark.parametrize("evaluation", [risk.evaluate_risk, risk.second_evaluate_risk])
async def test_risk_evaluation_returns_medium_when_generation_fails(
    monkeypatch,
    evaluation,
) -> None:
    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fail_generate_pipeline_json(*args, **kwargs):
        raise ValueError("invalid model JSON")

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fail_generate_pipeline_json)

    if evaluation is risk.evaluate_risk:
        result = await evaluation(make_settings(), make_event())
    else:
        result = await evaluation(make_settings(), make_event(), {})

    assert result == {
        "risk_level": RiskLevel.MEDIUM,
        "risk_score": 0.5,
        "reasoning": "自动评估",
    }


@pytest.mark.asyncio
async def test_evaluate_risk_requires_llm_history_context_analysis(
    monkeypatch,
) -> None:
    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        assert "existing graph fact" in prompt
        assert "Analyze the related event context separately" in prompt
        assert "history_context_analysis" in prompt
        return {
            "risk_level": "medium",
            "risk_score": 0.56,
            "reasoning": "召回上下文弱相关，维持中性分",
            "dimension_scores": {"history_context": 0.5},
            "dimension_reasoning": {
                "history_context": "召回事实仅证明有历史上下文，但同主体关联不足。"
            },
            "history_context_analysis": {
                "used_context": True,
                "matched_evidence": ["existing graph fact"],
                "relevance": "weak",
                "score_reason": "召回内容弱相关，因此历史上下文维度给 0.5。",
            },
        }

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.evaluate_risk(
        make_settings(),
        make_event(),
        {"reranked_edges": [{"text": "existing graph fact"}]},
    )

    assert result["dimension_scores"]["history_context"] == pytest.approx(0.5)
    assert result["dimension_reasoning"]["history_context"]
    assert result["history_context_analysis"]["used_context"] is True
    assert result["history_context_analysis"]["matched_evidence"] == [
        "existing graph fact"
    ]


@pytest.mark.asyncio
async def test_evaluate_risk_excludes_current_event_text_from_history_context(
    monkeypatch,
) -> None:
    event = make_event()
    event.raw_content = "当前事件原文，不应作为历史上下文"
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {
            "risk_level": "medium",
            "risk_score": 0.5,
            "reasoning": "仅分析真实历史上下文",
            "dimension_scores": {"history_context": 0.4},
            "history_context_analysis": {
                "used_context": True,
                "matched_evidence": ["真实历史图谱事实"],
                "relevance": "weak",
                "score_reason": "真实历史事实弱相关。",
            },
        }

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    await risk.evaluate_risk(
        make_settings(),
        event,
        {
            "reranked_episodes": [{"text": event.raw_content}],
            "reranked_edges": [{"text": "真实历史图谱事实"}],
        },
    )

    prompt = captured["prompt"]
    assert "真实历史图谱事实" in prompt
    related_context = prompt.split("Related event context:", 1)[1].split(
        "Return strict JSON",
        1,
    )[0]
    assert "当前事件原文，不应作为历史上下文" not in related_context


@pytest.mark.asyncio
async def test_evaluate_risk_appends_ragflow_knowledge(monkeypatch) -> None:
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        captured["stage"] = stage
        return {
            "chunks": [
                {
                    "content": "AML red flag: mule-account fund aggregation.",
                    "document_name": "aml.pdf",
                    "score": 0.91,
                }
            ]
        }

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {"risk_level": "high", "risk_score": 0.92, "reasoning": "知识库命中"}

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.evaluate_risk(make_settings(), make_event())

    assert result["risk_level"] is RiskLevel.HIGH
    assert captured["stage"] == "risk_first"
    assert "[RAGFlow external knowledge]" in captured["prompt"]
    assert "AML red flag" in captured["prompt"]
    assert "untrusted reference evidence" in captured["prompt"]


@pytest.mark.asyncio
async def test_second_evaluate_risk_appends_ragflow_knowledge(monkeypatch) -> None:
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        captured["stage"] = stage
        return {
            "chunks": [
                {
                    "content": "Second-pass risk context from RAGFlow.",
                    "document_name": "case.pdf",
                }
            ]
        }

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {"risk_level": "medium", "risk_score": 0.51, "reasoning": "复评"}

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.second_evaluate_risk(
        make_settings(),
        make_event(),
        {"reranked_edges": [{"text": "existing graph fact"}]},
    )

    assert result["risk_level"] is RiskLevel.MEDIUM
    assert captured["stage"] == "risk_second"
    assert "existing graph fact" in captured["prompt"]
    assert "[RAGFlow external knowledge]" in captured["prompt"]
    assert "Second-pass risk context" in captured["prompt"]


@pytest.mark.asyncio
async def test_evaluate_risk_skips_empty_ragflow_knowledge(monkeypatch) -> None:
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        return {"chunks": []}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {"risk_level": "low", "risk_score": 0.2, "reasoning": "低风险"}

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    await risk.evaluate_risk(make_settings(), make_event())

    assert "[RAGFlow external knowledge]" not in captured["prompt"]


@pytest.mark.asyncio
async def test_evaluate_risk_continues_when_ragflow_retrieval_raises(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        raise RagflowApiError(code=500, message="ragflow unavailable")

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        return {"risk_level": "high", "risk_score": 0.73, "reasoning": "图谱上下文"}

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fake_generate_pipeline_json)

    result = await risk.evaluate_risk(
        make_settings(),
        make_event(),
        {"reranked_edges": [{"text": "existing graph fact"}]},
    )

    assert result["risk_level"] is RiskLevel.HIGH
    assert "existing graph fact" in captured["prompt"]
    assert "[RAGFlow external knowledge]" not in captured["prompt"]


@pytest.mark.asyncio
async def test_evaluate_risk_propagates_fail_closed_ragflow_errors(
    monkeypatch,
) -> None:
    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        raise RagflowApiError(code=500, message="ragflow unavailable")

    async def fail_generate_pipeline_json(app_settings, *, prompt, temperature):
        raise AssertionError("fail-closed retrieval errors must stop before LLM")

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fail_generate_pipeline_json)

    with pytest.raises(RagflowApiError):
        await risk.evaluate_risk(
            make_settings(ragflow_fail_open=False),
            make_event(),
            {"reranked_edges": [{"text": "existing graph fact"}]},
        )


@pytest.mark.asyncio
async def test_second_evaluate_risk_propagates_fail_closed_ragflow_errors(
    monkeypatch,
) -> None:
    async def fake_retrieve_event_knowledge(app_settings, event, *, stage):
        raise RagflowApiError(code=500, message="ragflow unavailable")

    async def fail_generate_pipeline_json(app_settings, *, prompt, temperature):
        raise AssertionError("fail-closed retrieval errors must stop before LLM")

    monkeypatch.setattr(risk, "retrieve_event_knowledge", fake_retrieve_event_knowledge)
    monkeypatch.setattr(risk, "generate_pipeline_json", fail_generate_pipeline_json)

    with pytest.raises(RagflowApiError):
        await risk.second_evaluate_risk(
            make_settings(ragflow_fail_open=False),
            make_event(),
            {"reranked_edges": [{"text": "existing graph fact"}]},
        )
