"""基于 LiteLLM 的重排序打分原子工具。"""

import os
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm

from sentinel.utils.litellm_models import litellm_rerank_model_name


def _response_results(response: Any) -> list[Any]:
    results = getattr(response, "results", None)
    if results is None and isinstance(response, dict):
        results = response.get("results")
    return list(results or [])


async def rerank_scores(
    *,
    query: str,
    documents: list[str],
    model: str,
    api_key: str,
    base_url: str,
) -> list[float]:
    if not documents:
        return []

    response = await litellm.arerank(
        model=litellm_rerank_model_name(model),
        query=query,
        documents=documents,
        top_n=len(documents),
        return_documents=True,
        api_key=api_key,
        api_base=base_url,
    )

    scores = [0.0] * len(documents)
    for item in _response_results(response):
        index = getattr(item, "index", None)
        if index is None and isinstance(item, dict):
            index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(documents):
            continue

        score = getattr(item, "relevance_score", None)
        if score is None and isinstance(item, dict):
            score = item.get("relevance_score", item.get("score", 0.0))
        scores[index] = float(score or 0.0)
    return scores
