"""RAGFlow retrieval client and response normalization helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RagflowApiError(Exception):
    code: int | str
    message: str = "RAGFlow request failed"

    def __str__(self) -> str:
        return f"RAGFlow API error code={_safe_ragflow_code(self.code)}"


class RagflowConfigurationError(Exception):
    def __str__(self) -> str:
        return "RAGFlow configuration incomplete"


@dataclass(frozen=True, slots=True)
class RagflowRetrievalError(Exception):
    summary: str

    def __str__(self) -> str:
        return f"RAGFlow retrieval failed: {self.summary}"


@dataclass(frozen=True, slots=True)
class RagflowConfig:
    enabled: bool
    base_url: str
    api_key: str
    dataset_ids: list[str]
    top_k: int = 5
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.7
    timeout_seconds: float = 15.0
    max_context_chars: int = 4000
    fail_open: bool = True

    @property
    def ready(self) -> bool:
        return bool(
            self.enabled
            and self.base_url.strip()
            and self.api_key.strip()
            and self.dataset_ids
        )


class RagflowClient:
    def __init__(self, config: RagflowConfig) -> None:
        self._config = config

    async def retrieve(self, question: str) -> dict[str, Any]:
        if not self._config.ready:
            if self._config.enabled:
                exc = RagflowConfigurationError()
                if not self._config.fail_open:
                    raise exc
                error = ragflow_error_summary(exc)
                logger.warning(
                    "RAGFlow retrieval skipped; continuing without external "
                    "knowledge: %s",
                    error,
                )
                return _failed_retrieval_result(error)
            return {
                "enabled": self._config.enabled,
                "ready": False,
                "chunks": [],
                "message": "RAGFlow is disabled or missing required configuration.",
            }

        payload = {
            "question": question,
            "dataset_ids": list(self._config.dataset_ids),
            "top_k": self._config.top_k,
            "page_size": self._config.top_k,
            "similarity_threshold": self._config.similarity_threshold,
            "vector_similarity_weight": self._config.vector_similarity_weight,
        }
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        url = f"{self._config.base_url.rstrip('/')}/api/v1/retrieval"

        try:
            async with httpx.AsyncClient(
                timeout=self._config.timeout_seconds
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                _raise_for_error_envelope(data)
        except (httpx.HTTPError, JSONDecodeError, RagflowApiError) as exc:
            if not self._config.fail_open:
                if isinstance(exc, RagflowApiError):
                    raise
                raise RagflowRetrievalError(ragflow_error_summary(exc)) from None
            error = ragflow_error_summary(exc)
            logger.warning(
                "RAGFlow retrieval failed; continuing without external knowledge: %s",
                error,
            )
            return _failed_retrieval_result(error)

        return {
            "enabled": True,
            "ready": True,
            "chunks": _extract_chunks(data),
        }


def ragflow_error_summary(exc: BaseException) -> str:
    if isinstance(exc, RagflowApiError):
        return f"RagflowApiError(code={_safe_ragflow_code(exc.code)})"
    if isinstance(exc, RagflowConfigurationError):
        return "RagflowConfigurationError"
    if isinstance(exc, RagflowRetrievalError):
        return exc.summary
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTPStatusError(status_code={exc.response.status_code})"
    return type(exc).__name__


def _safe_ragflow_code(code: int | str) -> int | str:
    if isinstance(code, bool):
        return "non_numeric"
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.isdecimal():
        return int(code)
    return "non_numeric"


def _failed_retrieval_result(error: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "ready": False,
        "chunks": [],
        "error": error,
        "message": "RAGFlow retrieval failed; continuing without external knowledge.",
    }


def _raise_for_error_envelope(data: Any) -> None:
    if not isinstance(data, dict):
        return

    code = data.get("code")
    if code in (None, 0, "0"):
        return

    raise RagflowApiError(code=code)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _document_name_lookup(payload: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in payload.get("doc_aggs", []):
        if not isinstance(item, dict):
            continue
        doc_id = item.get("doc_id") or item.get("document_id")
        doc_name = (
            item.get("doc_name")
            or item.get("document_name")
            or item.get("document_keyword")
        )
        if doc_id and doc_name:
            lookup[str(doc_id)] = str(doc_name)
    return lookup


def _first_position_page(positions: Any) -> str | None:
    if not isinstance(positions, list):
        return None
    for position in positions:
        if isinstance(position, dict):
            value = _first_not_none(
                position.get("page"),
                position.get("page_num"),
                position.get("page_number"),
            )
            if value is not None:
                return str(value)
        elif isinstance(position, list | tuple) and position:
            return str(position[0])
    return None


def _extract_chunks(data: Any) -> list[dict[str, Any]]:
    payload = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        document_names = _document_name_lookup(payload)
        candidates = (
            payload.get("chunks")
            or payload.get("records")
            or payload.get("results")
            or payload.get("documents")
            or []
        )
    else:
        document_names = {}
        candidates = payload if isinstance(payload, list) else []

    chunks: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = (
            item.get("content")
            or item.get("content_with_weight")
            or item.get("content_ltks")
            or item.get("text")
            or item.get("chunk")
            or item.get("page_content")
            or ""
        )
        if not str(text).strip():
            continue
        document_id = item.get("document_id") or item.get("doc_id")
        document_name = item.get("document_name")
        if not document_name and document_id:
            document_name = document_names.get(str(document_id))
        document_name = (
            document_name
            or item.get("doc_name")
            or item.get("document_keyword")
            or item.get("docnm_kwd")
            or item.get("name")
            or item.get("source")
            or ""
        )
        chunks.append(
            {
                "content": str(text).strip(),
                "document_name": document_name,
                "score": _first_not_none(
                    item.get("similarity"),
                    item.get("score"),
                    item.get("rank"),
                ),
                "vector_score": item.get("vector_similarity"),
                "term_score": item.get("term_similarity"),
                "page": _first_not_none(
                    item.get("page"),
                    item.get("page_num"),
                    item.get("position"),
                    _first_position_page(item.get("positions")),
                ),
            }
        )
    return chunks
