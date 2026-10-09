"""基于 LiteLLM 的文本 embedding 原子工具。"""

import os
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm

from sentinel.config import SentinelSettings
from sentinel.utils.litellm_models import litellm_model_name


def _first_embedding(response: Any) -> list[float]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        return []

    first = data[0]
    embedding = getattr(first, "embedding", None)
    if embedding is None and isinstance(first, dict):
        embedding = first.get("embedding")
    return [float(value) for value in embedding or []]


async def embed_text(
    settings: SentinelSettings,
    text: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[float]:
    response = await litellm.aembedding(
        model=litellm_model_name(
            settings.llm_provider,
            model or settings.embedder_model,
        ),
        input=[text],
        api_key=api_key or settings.effective_embedder_api_key_value(),
        api_base=base_url or settings.effective_embedder_api_base,
    )
    return _first_embedding(response)
