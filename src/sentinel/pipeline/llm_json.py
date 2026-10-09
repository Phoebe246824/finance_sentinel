"""Shared LLM JSON generation helper for pipeline stages."""

from sentinel.config import SentinelSettings
from sentinel.utils.litellm_text import generate_text
from sentinel.utils.text import parse_llm_json_object

THINKING_DISABLED_EXTRA_BODY = {
    "enable_thinking": False,
    "thinking": {"type": "disabled"},
}


async def generate_pipeline_json(
    app_settings: SentinelSettings,
    *,
    prompt: str,
    temperature: float,
) -> dict:
    raw_output = await generate_text(
        app_settings,
        prompt=prompt,
        model=app_settings.llm_model,
        api_key=app_settings.require_llm_api_key(),
        base_url=app_settings.llm_base_url,
        temperature=temperature,
        max_completion_tokens=1024,
        extra_body=THINKING_DISABLED_EXTRA_BODY,
        timeout=180,
    )
    return parse_llm_json_object(raw_output)
