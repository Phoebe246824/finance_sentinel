import pytest

from sentinel.config import SentinelSettings
from sentinel.pipeline import llm_json


def make_settings() -> SentinelSettings:
    return SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
    )


@pytest.mark.asyncio
async def test_generate_pipeline_json_uses_bounded_non_reasoning_requests(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def fake_generate_text(settings_arg, **kwargs):
        assert settings_arg == make_settings()
        captured.update(kwargs)
        return '{"ok": true}'

    monkeypatch.setattr(llm_json, "generate_text", fake_generate_text)

    result = await llm_json.generate_pipeline_json(
        make_settings(),
        prompt="hello",
        temperature=0.2,
    )

    assert result == {"ok": True}
    assert captured["model"] == make_settings().llm_model
    assert captured["max_completion_tokens"] == 1024
    assert captured["timeout"] == 180
    assert captured["extra_body"] == {
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }
