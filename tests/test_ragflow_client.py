"""Tests for the retrieval-only RAGFlow HTTP client."""

import httpx
import pytest

from sentinel.ragflow.client import (
    RagflowApiError,
    RagflowConfig,
    _extract_chunks,
)


def test_ragflow_config_is_not_ready_without_credentials() -> None:
    config = RagflowConfig(
        enabled=True,
        base_url="http://127.0.0.1:9380",
        api_key="",
        dataset_ids=["dataset"],
    )

    assert not config.ready


def test_ragflow_config_is_not_ready_with_blank_connection_values() -> None:
    assert not RagflowConfig(
        enabled=True,
        base_url="   ",
        api_key="secret",
        dataset_ids=["dataset"],
    ).ready
    assert not RagflowConfig(
        enabled=True,
        base_url="http://127.0.0.1:9380",
        api_key="   ",
        dataset_ids=["dataset"],
    ).ready


@pytest.mark.asyncio
async def test_client_returns_empty_result_when_not_ready() -> None:
    from sentinel.ragflow.client import RagflowClient

    result = await RagflowClient(
        RagflowConfig(
            enabled=False,
            base_url="",
            api_key="",
            dataset_ids=[],
        )
    ).retrieve("query")

    assert result["ready"] is False
    assert result["chunks"] == []
    assert "query" not in result


@pytest.mark.asyncio
async def test_enabled_incomplete_config_fail_open_returns_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="",
            dataset_ids=["dataset"],
            fail_open=True,
        )
    ).retrieve("raw event contains rag-secret")

    output = f"{result}\n{caplog.text}"
    assert result["ready"] is False
    assert result["chunks"] == []
    assert result["error"] == "RagflowConfigurationError"
    assert "raw event contains" not in output
    assert "rag-secret" not in output


@pytest.mark.asyncio
async def test_enabled_incomplete_config_fail_closed_raises_safe_error() -> None:
    from sentinel.ragflow.client import RagflowClient

    with pytest.raises(Exception) as exc_info:
        await RagflowClient(
            RagflowConfig(
                enabled=True,
                base_url="http://ragflow.example",
                api_key="",
                dataset_ids=["dataset"],
                fail_open=False,
            )
        ).retrieve("raw event contains rag-secret")

    output = str(exc_info.value)
    assert type(exc_info.value).__name__ == "RagflowConfigurationError"
    assert "RAGFlow configuration incomplete" in output
    assert "raw event contains" not in output
    assert "rag-secret" not in output


@pytest.mark.asyncio
async def test_client_sends_expected_retrieval_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    calls: list[dict[str, object]] = []

    async def fake_post(
        self: httpx.AsyncClient,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> httpx.Response:
        calls.append(
            {
                "client": self,
                "url": url,
                "json": json,
                "headers": headers,
            }
        )
        request = httpx.Request("POST", url)
        return httpx.Response(
            200, json={"code": 0, "data": {"chunks": []}}, request=request
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    dataset_ids = ["dataset-a", "dataset-b"]

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example/",
            api_key="secret",
            dataset_ids=dataset_ids,
            top_k=7,
            similarity_threshold=0.0,
            vector_similarity_weight=0.5,
        )
    ).retrieve("virtual asset red flags")

    assert result["ready"] is True
    assert calls == [
        {
            "client": calls[0]["client"],
            "url": "http://ragflow.example/api/v1/retrieval",
            "json": {
                "question": "virtual asset red flags",
                "dataset_ids": ["dataset-a", "dataset-b"],
                "top_k": 7,
                "page_size": 7,
                "similarity_threshold": 0.0,
                "vector_similarity_weight": 0.5,
            },
            "headers": {"Authorization": "Bearer secret"},
        }
    ]
    assert calls[0]["json"]["dataset_ids"] is not dataset_ids


@pytest.mark.asyncio
async def test_client_reports_not_ready_when_fail_open_retrieval_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="secret",
            dataset_ids=["dataset"],
            fail_open=True,
        )
    ).retrieve("query contains rag-secret")

    assert result["ready"] is False
    assert result["chunks"] == []
    assert result["error"] == "ConnectError"
    assert "query contains" not in str(result)
    assert "rag-secret" not in str(result)


@pytest.mark.asyncio
async def test_client_reports_not_ready_when_ragflow_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        return httpx.Response(
            200,
            json={"code": 102, "message": "dataset not found", "data": False},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="secret",
            dataset_ids=["missing-dataset"],
            fail_open=True,
        )
    ).retrieve("query")

    assert result["ready"] is False
    assert result["chunks"] == []
    assert result["error"] == "RagflowApiError(code=102)"


@pytest.mark.asyncio
async def test_client_fail_open_redacts_remote_error_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        return httpx.Response(
            200,
            json={
                "code": 102,
                "message": "dataset missing for rag-secret Authorization header",
                "data": False,
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="rag-secret",
            dataset_ids=["missing-dataset"],
            fail_open=True,
        )
    ).retrieve("query")

    output = f"{result}\n{caplog.text}"
    assert result["ready"] is False
    assert result["error"] == "RagflowApiError(code=102)"
    assert "dataset missing" not in output
    assert "rag-secret" not in output
    assert "Authorization" not in output


@pytest.mark.asyncio
async def test_client_fail_open_redacts_remote_error_code_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        return httpx.Response(
            200,
            json={
                "code": "Authorization: Bearer rag-secret",
                "message": "dataset missing",
                "data": False,
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="rag-secret",
            dataset_ids=["missing-dataset"],
            fail_open=True,
        )
    ).retrieve("query")

    output = f"{result}\n{caplog.text}"
    assert result["ready"] is False
    assert result["error"] == "RagflowApiError(code=non_numeric)"
    assert "dataset missing" not in output
    assert "rag-secret" not in output
    assert "Authorization" not in output


@pytest.mark.asyncio
async def test_client_raises_safe_http_error_when_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            "server leaked dataset missing rag-secret Authorization",
            request=request,
            response=response,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(Exception) as exc_info:
        await RagflowClient(
            RagflowConfig(
                enabled=True,
                base_url="http://ragflow.example",
                api_key="secret",
                dataset_ids=["dataset"],
                fail_open=False,
            )
        ).retrieve("query")

    output = str(exc_info.value)
    assert type(exc_info.value).__name__ == "RagflowRetrievalError"
    assert output == "RAGFlow retrieval failed: HTTPStatusError(status_code=500)"
    assert "dataset missing" not in output
    assert "rag-secret" not in output
    assert "Authorization" not in output


@pytest.mark.asyncio
async def test_client_raises_safe_error_envelope_when_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        return httpx.Response(
            200,
            json={
                "code": 102,
                "message": "dataset missing for rag-secret Authorization header",
                "data": False,
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(RagflowApiError) as exc_info:
        await RagflowClient(
            RagflowConfig(
                enabled=True,
                base_url="http://ragflow.example",
                api_key="secret",
                dataset_ids=["missing-dataset"],
                fail_open=False,
            )
        ).retrieve("query")

    output = str(exc_info.value)
    assert output == "RAGFlow API error code=102"
    assert "dataset missing" not in output
    assert "rag-secret" not in output
    assert "Authorization" not in output


@pytest.mark.asyncio
async def test_client_success_result_exposes_only_normalized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "http://ragflow.example/api/v1/retrieval")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "content": "AML red flag.",
                            "document_name": "rules.pdf",
                            "similarity": 0.9,
                            "internal_note": "Authorization: Bearer rag-secret",
                        }
                    ],
                    "debug": "rag-secret raw envelope",
                },
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await RagflowClient(
        RagflowConfig(
            enabled=True,
            base_url="http://ragflow.example",
            api_key="rag-secret",
            dataset_ids=["dataset"],
        )
    ).retrieve("query contains rag-secret")

    assert result == {
        "enabled": True,
        "ready": True,
        "chunks": [
            {
                "content": "AML red flag.",
                "document_name": "rules.pdf",
                "score": 0.9,
                "vector_score": None,
                "term_score": None,
                "page": None,
            }
        ],
    }
    output = str(result)
    assert "query contains" not in output
    assert "rag-secret" not in output
    assert "Authorization" not in output


@pytest.mark.asyncio
async def test_client_does_not_fail_open_programmer_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ragflow.client import RagflowClient

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        raise ValueError("programmer bug")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ValueError, match="programmer bug"):
        await RagflowClient(
            RagflowConfig(
                enabled=True,
                base_url="http://ragflow.example",
                api_key="secret",
                dataset_ids=["dataset"],
                fail_open=True,
            )
        ).retrieve("query")


def test_extract_chunks_supports_ragflow_retrieval_payload() -> None:
    chunks = _extract_chunks(
        {
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "content_with_weight": "Virtual assets red flag indicators.",
                        "content_ltks": "virtual assets red flag indicators",
                        "docnm_kwd": "fatf.pdf",
                        "similarity": 0.88,
                        "vector_similarity": 0.91,
                        "term_similarity": 0.72,
                    }
                ],
                "total": 1,
            },
        }
    )

    assert chunks == [
        {
            "content": "Virtual assets red flag indicators.",
            "document_name": "fatf.pdf",
            "score": 0.88,
            "vector_score": 0.91,
            "term_score": 0.72,
            "page": None,
        }
    ]


def test_extract_chunks_supports_official_ragflow_fields() -> None:
    chunks = _extract_chunks(
        {
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "content_with_weight": "Official retrieval payload.",
                        "document_id": "doc-1",
                        "document_keyword": "fallback-document.pdf",
                        "positions": [{"page_num": 3}],
                        "similarity": 0.77,
                    }
                ],
                "doc_aggs": [
                    {
                        "doc_id": "doc-1",
                        "doc_name": "official-rules.pdf",
                    }
                ],
                "total": 1,
            },
        }
    )

    assert chunks[0]["document_name"] == "official-rules.pdf"
    assert chunks[0]["page"] == "3"
    assert chunks[0]["score"] == 0.77


def test_extract_chunks_preserves_zero_scores_and_page() -> None:
    chunks = _extract_chunks(
        {
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "content": "Zero-valued retrieval metadata is valid.",
                        "document_name": "zero.pdf",
                        "similarity": 0.0,
                        "score": 0.42,
                        "rank": 9,
                        "vector_similarity": 0.0,
                        "term_similarity": 0.0,
                        "page": 0,
                        "page_num": 12,
                        "position": 34,
                    }
                ],
                "total": 1,
            },
        }
    )

    assert chunks[0]["score"] == 0.0
    assert chunks[0]["vector_score"] == 0.0
    assert chunks[0]["term_score"] == 0.0
    assert chunks[0]["page"] == 0
