"""基于 LiteLLM 的文本生成原子工具。"""

import asyncio
import os
from collections.abc import Sequence
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm

from sentinel.config import SentinelSettings
from sentinel.utils.litellm_models import litellm_model_name

Message = dict[str, str]


def _response_choice_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        return ""

    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        if isinstance(first, dict):
            return str(first.get("text", ""))
        return str(getattr(first, "text", ""))

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return "" if content is None else str(content)


async def generate_text(
    settings: SentinelSettings,
    *,
    prompt: str | None = None,
    messages: Sequence[Message] | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.3,
    max_completion_tokens: int = 8192,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> str:
    if messages is None:
        if prompt is None:
            raise ValueError("generate_text requires prompt or messages")
        messages = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": litellm_model_name(settings.llm_provider, model or settings.llm_model),
        "messages": list(messages),
        "api_key": api_key or settings.require_llm_api_key(),
        "api_base": base_url or settings.llm_base_url,
        "temperature": temperature,
        "max_completion_tokens": max_completion_tokens,
    }
    if extra_body is not None:
        kwargs["extra_body"] = extra_body
    if timeout is not None:
        kwargs["timeout"] = timeout

    request = litellm.acompletion(**kwargs)
    if timeout is not None:
        response = await asyncio.wait_for(request, timeout=timeout)
    else:
        response = await request
    return _response_choice_content(response)
