"""
Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from ..llm_client import LLMConfig
from .client import CrossEncoderClient

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'bce-reranker-base_v1'


def _is_retryable(e: BaseException) -> bool:
    return isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout))


def _log_retry(retry_state: Any) -> None:
    logger.warning(
        'Reranker API call failed, retrying (attempt %d/%d): %s',
        retry_state.attempt_number, 3, retry_state.outcome.exception(),
    )


class JinaRerankerClient(CrossEncoderClient):
    """Cross-encoder reranker using the Jina-style /v1/rerank API.

    Compatible with Gitee AI, Jina AI, and other providers that implement
    the same rerank endpoint contract.
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        if config is None:
            config = LLMConfig()

        self._base_url = (config.base_url or 'https://api.jina.ai/v1').rstrip('/')
        self._api_key = config.api_key or ''
        self._model = config.model or DEFAULT_MODEL
        self._client = httpx.AsyncClient()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=1, max=10),
        reraise=True,
        after=_log_retry,
    )
    async def _api_call(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        response = await self._client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            logger.debug('rank() called with empty passages list')
            return []

        empty_count = sum(1 for p in passages if not p or not p.strip())
        logger.info(
            'rank() called: total=%d, empty_or_whitespace=%d, query_len=%d',
            len(passages), empty_count, len(query),
        )
        if empty_count > 0:
            logger.warning(
                'rank() detected %d empty/whitespace documents in passages',
                empty_count,
            )

        url = f'{self._base_url}/rerank'
        headers = {
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self._model,
            'query': query,
            'documents': passages,
        }

        logger.debug(
            'Sending rerank request: url=%s, model=%s, payload_size=%d bytes',
            url, self._model, len(str(payload)),
        )

        data = await self._api_call(url, payload, headers)

        if not isinstance(data, dict):
            logger.warning('Unexpected reranker response type: %s', type(data).__name__)
            return []

        results = data.get('results') or []
        logger.debug('Reranker API returned %d results', len(results))
        scored: list[tuple[str, float]] = []
        for item in results:
            if not isinstance(item, dict):
                logger.warning('Unexpected reranker result item type: %s', type(item).__name__)
                continue

            score = item.get('relevance_score', 0.0)
            document = item.get('document')
            doc_text = document.get('text') if isinstance(document, dict) else None
            if doc_text is None:
                idx = item.get('index')
                if idx is not None and 0 <= idx < len(passages):
                    doc_text = passages[idx]
                else:
                    logger.warning('Reranker result missing document text, index=%s', idx)
                    continue
            scored.append((doc_text, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        logger.info('rank() completed: scored=%d documents', len(scored))
        return scored

    async def close(self) -> None:
        await self._client.aclose()