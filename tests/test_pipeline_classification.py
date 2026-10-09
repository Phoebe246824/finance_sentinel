from datetime import datetime

import pytest

from sentinel.config import PromptRenderError, SentinelSettings
from sentinel.config.profile import ClassificationProfileConfig
from sentinel.models import EventSource, NormalizedEvent
from sentinel.pipeline import classification
from tests.test_profile_config import write_profile


@pytest.fixture(autouse=True)
def isolate_profile_config_cache():
    import sentinel.config.profile as profile_module

    profile_module.reset_profile_config_cache()
    yield
    profile_module.reset_profile_config_cache()


def make_settings() -> SentinelSettings:
    return SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
    )


def make_event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="EVT-CLS",
        source=EventSource.NEWS,
        raw_content="某公司发布召回公告",
        title="召回公告",
        timestamp=datetime(2026, 6, 30, 10, 0, 0),
    )


def test_classification_category_text_with_no_categories_is_data_only() -> None:
    profile = ClassificationProfileConfig(categories={})

    category_text = classification.classification_category_text(profile)

    assert category_text == "No configured categories."
    assert "Use" not in category_text
    assert "default event type" not in category_text


@pytest.mark.asyncio
async def test_execute_classification_writes_classification_fields(monkeypatch) -> None:
    async def fake_classify_event(app_settings, normalized_event):
        return {
            "event_type": "负面舆情",
            "key_entities": {"company": "某公司"},
            "summary": "某公司发布召回公告",
        }

    monkeypatch.setattr(classification, "classify_event", fake_classify_event)
    event = make_event()

    result = await classification.execute_classification(make_settings(), event)

    assert result is event
    assert event.event_type == "负面舆情"
    assert event.structured_data == {"company": "某公司"}
    assert event.summary == "某公司发布召回公告"


@pytest.mark.asyncio
async def test_execute_classification_keeps_event_when_llm_parse_fails(
    monkeypatch,
) -> None:
    async def fake_classify_event(app_settings, normalized_event):
        return None

    monkeypatch.setattr(classification, "classify_event", fake_classify_event)
    event = make_event()

    result = await classification.execute_classification(make_settings(), event)

    assert result is event
    assert event.event_type == ""
    assert event.summary == ""


@pytest.mark.asyncio
async def test_classify_event_uses_profile_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    write_profile(tmp_path)
    (tmp_path / "prompts/pipeline/classification.md").write_text(
        """# Classification configured marker

Use category keyword extensions as weak signals, not as the only evidence.

Configured categories:
{category_options}

Default event type: {default_event_type}
Summary instruction: {summary_instruction}
Title: {title}
Content: {raw_content}
{output_schema}
""",
        encoding="utf-8",
    )
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    profile = profile_module.get_profile_config()
    monkeypatch.setattr(classification, "get_profile_config", lambda: profile)
    captured = {}

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        captured["prompt"] = prompt
        captured["temperature"] = temperature
        return {
            "event_type": "public_notice",
            "key_entities": {"organization": ["某公司"]},
            "summary": "某公司发布召回公告",
        }

    monkeypatch.setattr(
        classification,
        "generate_pipeline_json",
        fake_generate_pipeline_json,
    )

    result = await classification.classify_event(make_settings(), make_event())

    assert result == {
        "event_type": "public_notice",
        "key_entities": {"organization": ["某公司"]},
        "summary": "某公司发布召回公告",
    }
    assert captured["temperature"] == 0.3
    prompt = captured["prompt"]
    assert "# Classification configured marker" in prompt
    assert "Use category keyword extensions as weak signals" in prompt
    assert "public_notice: Public Notice; keywords: advisory" in prompt
    assert "Default event type: public_event" in prompt
    assert "Summary instruction: Summarize the event for operators." in prompt
    assert "Title: 召回公告" in prompt
    assert "Content: 某公司发布召回公告" in prompt
    assert "event_type:str" in prompt
    assert "key_entities:dict" in prompt
    assert "summary:str" in prompt


@pytest.mark.asyncio
async def test_classify_event_propagates_prompt_render_error(monkeypatch) -> None:
    render_error = PromptRenderError("invalid classification prompt")

    def fail_render_prompt(*args, **kwargs):
        raise render_error

    async def fail_generate_pipeline_json(*args, **kwargs):
        raise AssertionError("model must not run after prompt rendering fails")

    monkeypatch.setattr(classification, "render_prompt", fail_render_prompt)
    monkeypatch.setattr(
        classification,
        "generate_pipeline_json",
        fail_generate_pipeline_json,
    )

    with pytest.raises(PromptRenderError) as exc_info:
        await classification.classify_event(make_settings(), make_event())

    assert exc_info.value is render_error


@pytest.mark.asyncio
async def test_classify_event_returns_none_when_generation_fails(monkeypatch) -> None:
    async def fail_generate_pipeline_json(*args, **kwargs):
        raise ValueError("invalid model JSON")

    monkeypatch.setattr(
        classification,
        "generate_pipeline_json",
        fail_generate_pipeline_json,
    )

    assert await classification.classify_event(make_settings(), make_event()) is None


@pytest.mark.asyncio
async def test_classify_event_uses_profile_default_when_event_type_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    profile = profile_module.get_profile_config()
    monkeypatch.setattr(classification, "get_profile_config", lambda: profile)

    async def fake_generate_pipeline_json(app_settings, *, prompt, temperature):
        return {
            "key_entities": {"organization": ["某公司"]},
            "summary": "某公司发布召回公告",
        }

    monkeypatch.setattr(
        classification,
        "generate_pipeline_json",
        fake_generate_pipeline_json,
    )

    result = await classification.classify_event(make_settings(), make_event())

    assert result == {
        "event_type": "public_event",
        "key_entities": {"organization": ["某公司"]},
        "summary": "某公司发布召回公告",
    }


@pytest.mark.asyncio
async def test_classify_event_propagates_profile_load_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        classification,
        "get_profile_config",
        profile_module.get_profile_config,
    )

    with pytest.raises(FileNotFoundError, match="profile.yaml"):
        await classification.classify_event(make_settings(), make_event())
