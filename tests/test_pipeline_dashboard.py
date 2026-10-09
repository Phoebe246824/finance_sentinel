"""Tests for dashboard context and trend prediction stage helpers."""

from datetime import datetime

import pytest

from sentinel.config import SentinelSettings
from sentinel.models import EventSource, NormalizedEvent, RiskLevel
from sentinel.pipeline.dashboard import (
    build_dashboard_context_text,
    build_event_metadata_text,
)
from tests.test_profile_config import write_profile


def make_settings() -> SentinelSettings:
    return SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
    )


def make_event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="EVT-DASH",
        source=EventSource.NEWS,
        raw_content="dashboard event",
        event_type="负面舆情",
        risk_level=RiskLevel.HIGH,
        risk_score=0.82,
        timestamp=datetime(2026, 6, 30, 10, 0, 0),
    )


def test_build_dashboard_context_text_uses_edges_and_episodes():
    class Episode:
        content = "episode content"

    text = build_dashboard_context_text(
        {
            "reranked_edges": [{"text": "edge fact"}],
            "reranked_episodes": [Episode()],
        }
    )

    assert text == "[edge] edge fact\n[episode] episode content"


def test_build_event_metadata_text_contains_type_and_risk():
    text = build_event_metadata_text(make_event())

    assert "事件类型: 负面舆情" in text
    assert "风险等级: high" in text
    assert "风险分数: 0.82" in text


@pytest.mark.asyncio
async def test_execute_dashboard_returns_trend_report(monkeypatch):
    from sentinel.pipeline import dashboard as dashboard_module
    from sentinel.trend_prediction.service import TrendReport

    report = TrendReport(
        raw_report="raw",
        category="general",
        category_name="通用",
        category_confidence=0.9,
        severity="major",
        severity_name="重大",
        severity_confidence=0.8,
        event_text="dashboard event",
        context_text="",
        model="model",
        temperature=0.3,
    )

    async def fake_run_trend_prediction(
        config,
        event_text,
        context_text,
        app_settings,
        source_event,
    ):
        assert source_event.event_id == "EVT-DASH"
        assert source_event.raw_content == "dashboard event"
        return report

    monkeypatch.setattr(
        dashboard_module,
        "run_trend_prediction",
        fake_run_trend_prediction,
    )

    result = await dashboard_module.execute_dashboard(
        app_settings=None,
        normalized_event=make_event(),
        results={},
    )

    assert result is report


@pytest.mark.asyncio
async def test_execute_dashboard_uses_profile_metadata_and_category(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path,
):
    from sentinel.pipeline import dashboard as dashboard_module
    from sentinel.trend_prediction.service import TrendReport

    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    request.addfinalizer(profile_module.reset_profile_config_cache)
    captured = {}
    report = TrendReport(
        raw_report="raw",
        category="general",
        category_name="General",
        category_confidence=0.9,
        severity="major",
        severity_name="Major",
        severity_confidence=0.8,
        event_text="dashboard event",
        context_text="",
        model="model",
        temperature=0.3,
    )

    async def fake_run_trend_prediction(
        config,
        event_text,
        context_text,
        app_settings,
        source_event,
    ):
        captured["config"] = config
        return report

    monkeypatch.setattr(
        dashboard_module,
        "run_trend_prediction",
        fake_run_trend_prediction,
    )

    result = await dashboard_module.execute_dashboard(
        app_settings=make_settings(),
        normalized_event=make_event(),
        results={},
    )

    assert result is report
    config = captured["config"]
    assert config.force_category is None
    assert config.force_category_confidence == pytest.approx(0.9)
    assert "Public impact and response." in config.event_metadata_text
    assert not hasattr(config, "intent_prompt_template")
    assert not hasattr(config, "trend_prompt_template")
