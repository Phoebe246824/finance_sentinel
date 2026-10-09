from __future__ import annotations

import asyncio
import time

import pytest

from sentinel.web.settings_checks import (
    CHECK_TIMEOUT_SECONDS,
    RuntimeSettingsCheckService,
    ServiceCheckFactories,
)


class FakeSettings:
    neo4j_uri = "bolt://neo4j.local:7687"
    neo4j_user = "neo4j"
    neo4j_database = "sentinel"
    milvus_uri = "http://milvus.local:19530"
    llm_provider = "openai"
    llm_model = "chat-model"
    llm_base_url = "https://llm.example/v1"
    embedder_model = "embedder-model"
    effective_embedder_api_base = "https://embed.example/v1"
    effective_reranker_model = "reranker-model"
    effective_reranker_base_url = "https://rerank.example/v1"

    def require_neo4j_password(self) -> str:
        return "neo4j-secret"

    def optional_milvus_token(self) -> str | None:
        return "milvus-secret"

    def require_llm_api_key(self) -> str:
        return "llm-secret"

    def effective_embedder_api_key_value(self) -> str:
        return "embed-secret"

    def effective_reranker_api_key_value(self) -> str:
        return "rerank-secret"


class FakeNeo4jResult:
    async def single(self) -> dict[str, int]:
        return {"ok": 1}


class FakeNeo4jSession:
    def __init__(self) -> None:
        self.database = ""
        self.query = ""

    async def __aenter__(self) -> "FakeNeo4jSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def run(self, query: str) -> FakeNeo4jResult:
        self.query = query
        return FakeNeo4jResult()


class FakeNeo4jDriver:
    def __init__(self) -> None:
        self.session_obj = FakeNeo4jSession()
        self.closed = False

    def session(self, *, database: str) -> FakeNeo4jSession:
        self.session_obj.database = database
        return self.session_obj

    async def close(self) -> None:
        self.closed = True


class FakeMilvusClient:
    def __init__(self, *, uri: str, token: str | None) -> None:
        self.uri = uri
        self.token = token
        self.closed = False

    def list_collections(self) -> list[str]:
        return []

    def close(self) -> None:
        self.closed = True


async def fake_embed_text(*args, **kwargs) -> list[float]:
    del args, kwargs
    return [0.1]


async def fake_rerank_scores(*args, **kwargs) -> list[float]:
    del args, kwargs
    return [1.0]


def make_service(
    *,
    neo4j_driver: FakeNeo4jDriver | None = None,
    milvus_client: FakeMilvusClient | None = None,
    milvus_client_factory=None,
) -> RuntimeSettingsCheckService:
    driver = neo4j_driver or FakeNeo4jDriver()
    client = milvus_client or FakeMilvusClient(
        uri="http://milvus.local:19530",
        token="milvus-secret",
    )
    return RuntimeSettingsCheckService(
        service_factories=ServiceCheckFactories(
            neo4j_driver_factory=lambda uri, auth: driver,
            milvus_client_factory=milvus_client_factory or (lambda **kwargs: client),
        )
    )


@pytest.mark.asyncio
async def test_run_service_checks_returns_rows_and_redacts_secrets():
    settings = FakeSettings()
    neo4j_driver = FakeNeo4jDriver()
    milvus_client = FakeMilvusClient(
        uri="http://milvus.local:19530",
        token="milvus-secret",
    )
    service = make_service(neo4j_driver=neo4j_driver, milvus_client=milvus_client)

    payload = await service.run_service_checks(settings)

    assert [row.name for row in payload.results] == ["Neo4j", "Milvus"]
    assert all(row.kind == "service" for row in payload.results)
    assert all(row.ok for row in payload.results)
    assert all(row.duration_ms >= 0 for row in payload.results)
    assert "neo4j-secret" not in payload.model_dump_json()
    assert "milvus-secret" not in payload.model_dump_json()
    assert "password=***" in payload.results[0].detail
    assert "token=***" in payload.results[1].detail
    assert neo4j_driver.closed is True
    assert milvus_client.closed is True
    assert neo4j_driver.session_obj.database == "sentinel"
    assert neo4j_driver.session_obj.query == "RETURN 1 AS ok"
    assert milvus_client.uri == "http://milvus.local:19530"
    assert milvus_client.token == "milvus-secret"


@pytest.mark.asyncio
async def test_service_checks_keep_running_when_each_service_fails():
    class FailingNeo4jSession(FakeNeo4jSession):
        async def run(self, query: str):
            self.query = query
            raise RuntimeError("neo4j-secret unavailable")

    class FailingNeo4jDriver(FakeNeo4jDriver):
        def __init__(self) -> None:
            super().__init__()
            self.session_obj = FailingNeo4jSession()

    class FailingMilvusClient(FakeMilvusClient):
        def list_collections(self) -> list[str]:
            raise RuntimeError("milvus-secret unavailable")

    settings = FakeSettings()
    service = make_service(
        neo4j_driver=FailingNeo4jDriver(),
        milvus_client=FailingMilvusClient(
            uri="http://milvus.local:19530",
            token="milvus-secret",
        ),
    )

    payload = await service.run_service_checks(settings)

    assert [row.name for row in payload.results] == ["Neo4j", "Milvus"]
    assert [row.ok for row in payload.results] == [False, False]
    assert "neo4j-secret" not in payload.model_dump_json()
    assert "milvus-secret" not in payload.model_dump_json()


@pytest.mark.asyncio
async def test_milvus_check_runs_in_thread_without_blocking_event_loop():
    class SlowMilvusClient(FakeMilvusClient):
        def list_collections(self) -> list[str]:
            time.sleep(0.05)
            return []

    service = make_service(
        milvus_client=SlowMilvusClient(
            uri="http://milvus.local:19530",
            token="milvus-secret",
        )
    )
    ticked = False

    async def tick() -> None:
        nonlocal ticked
        await asyncio.sleep(0.01)
        ticked = True

    await asyncio.gather(service.run_service_checks(FakeSettings()), tick())

    assert ticked is True


@pytest.mark.asyncio
async def test_service_check_targets_redact_uri_userinfo_query_and_fragment_secrets():
    class QuerySecretSettings(FakeSettings):
        neo4j_uri = "bolt://neo4j:neo4j-secret@neo4j.local:7687?token=neo4j-secret#frag"
        milvus_uri = (
            "http://milvus.local:19530?api_key=milvus-secret#token=milvus-secret"
        )

    payload = await make_service().run_service_checks(QuerySecretSettings())
    serialized = payload.model_dump_json()

    assert "neo4j-secret" not in serialized
    assert "milvus-secret" not in serialized
    assert "api_key=" not in serialized
    assert "token=neo4j-secret" not in serialized
    assert "token=milvus-secret" not in serialized
    assert "#" not in payload.results[0].target
    assert "#" not in payload.results[1].target


@pytest.mark.asyncio
async def test_run_model_checks_captures_failures_without_leaking_keys(monkeypatch):
    async def fail_generate_text(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("bad key llm-secret embed-secret rerank-secret")

    monkeypatch.setattr(
        "sentinel.web.settings_checks.generate_text", fail_generate_text
    )
    monkeypatch.setattr("sentinel.web.settings_checks.embed_text", fake_embed_text)
    monkeypatch.setattr(
        "sentinel.web.settings_checks.rerank_scores", fake_rerank_scores
    )

    payload = await RuntimeSettingsCheckService().run_model_checks(FakeSettings())

    assert [row.name for row in payload.results] == ["LLM", "Embedder", "Reranker"]
    assert all(row.kind == "model" for row in payload.results)
    assert payload.results[0].ok is False
    assert payload.results[1].ok is True
    assert payload.results[2].ok is True
    assert payload.results[0].error is not None
    assert "llm-secret" not in payload.results[0].error
    assert "embed-secret" not in payload.results[0].error
    assert "rerank-secret" not in payload.results[0].error
    assert "ll***et" in payload.results[0].error
    assert "em***et" in payload.results[0].error
    assert "re***et" in payload.results[0].error


@pytest.mark.parametrize(
    ("failing_name", "expected_statuses"),
    [
        ("generate_text", [False, True, True]),
        ("embed_text", [True, False, True]),
        ("rerank_scores", [True, True, False]),
    ],
)
@pytest.mark.asyncio
async def test_model_checks_capture_each_target_failure_without_stopping_siblings(
    monkeypatch,
    failing_name,
    expected_statuses,
):
    async def ok_generate_text(*args, **kwargs):
        del args, kwargs
        return "pong"

    async def fail_generate_text(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("bad key llm-secret embed-secret rerank-secret")

    async def fail_embed_text(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("bad key llm-secret embed-secret rerank-secret")

    async def fail_rerank_scores(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("bad key llm-secret embed-secret rerank-secret")

    monkeypatch.setattr(
        "sentinel.web.settings_checks.generate_text",
        fail_generate_text if failing_name == "generate_text" else ok_generate_text,
    )
    monkeypatch.setattr(
        "sentinel.web.settings_checks.embed_text",
        fail_embed_text if failing_name == "embed_text" else fake_embed_text,
    )
    monkeypatch.setattr(
        "sentinel.web.settings_checks.rerank_scores",
        fail_rerank_scores if failing_name == "rerank_scores" else fake_rerank_scores,
    )

    payload = await RuntimeSettingsCheckService().run_model_checks(FakeSettings())

    assert [row.name for row in payload.results] == ["LLM", "Embedder", "Reranker"]
    assert [row.ok for row in payload.results] == expected_statuses
    assert "llm-secret" not in payload.model_dump_json()
    assert "embed-secret" not in payload.model_dump_json()
    assert "rerank-secret" not in payload.model_dump_json()


@pytest.mark.asyncio
async def test_model_checks_pass_effective_provider_settings(monkeypatch):
    calls = {}

    async def capture_generate_text(settings, **kwargs):
        calls["llm"] = (settings, kwargs)
        return "pong"

    async def capture_embed_text(settings, text, **kwargs):
        calls["embedder"] = (settings, text, kwargs)
        return [0.1]

    async def capture_rerank_scores(**kwargs):
        calls["reranker"] = kwargs
        return [1.0]

    monkeypatch.setattr(
        "sentinel.web.settings_checks.generate_text", capture_generate_text
    )
    monkeypatch.setattr("sentinel.web.settings_checks.embed_text", capture_embed_text)
    monkeypatch.setattr(
        "sentinel.web.settings_checks.rerank_scores", capture_rerank_scores
    )

    settings = FakeSettings()
    payload = await RuntimeSettingsCheckService().run_model_checks(settings)

    assert all(row.ok for row in payload.results)
    llm_settings, llm_kwargs = calls["llm"]
    assert llm_settings is settings
    assert llm_kwargs["model"] == "chat-model"
    assert llm_kwargs["base_url"] == "https://llm.example/v1"
    assert llm_kwargs["api_key"] == "llm-secret"
    assert llm_kwargs["timeout"] == CHECK_TIMEOUT_SECONDS
    embedder_settings, embedder_text, embedder_kwargs = calls["embedder"]
    assert embedder_settings is settings
    assert embedder_text == "x"
    assert embedder_kwargs["model"] == "embedder-model"
    assert embedder_kwargs["base_url"] == "https://embed.example/v1"
    assert embedder_kwargs["api_key"] == "embed-secret"
    assert calls["reranker"]["model"] == "reranker-model"
    assert calls["reranker"]["base_url"] == "https://rerank.example/v1"
    assert calls["reranker"]["api_key"] == "rerank-secret"


@pytest.mark.parametrize(
    ("slow_name", "expected_error_row"),
    [
        ("generate_text", "LLM"),
        ("embed_text", "Embedder"),
        ("rerank_scores", "Reranker"),
    ],
)
@pytest.mark.asyncio
async def test_model_check_timeouts_return_failed_row_and_continue(
    monkeypatch,
    slow_name,
    expected_error_row,
):
    async def ok_generate_text(*args, **kwargs):
        del args, kwargs
        return "pong"

    async def slow_generate_text(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.1)
        return "pong"

    async def slow_embed_text(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.1)
        return [0.1]

    async def slow_rerank_scores(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.1)
        return [1.0]

    monkeypatch.setattr(
        "sentinel.web.settings_checks.CHECK_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "sentinel.web.settings_checks.generate_text",
        slow_generate_text if slow_name == "generate_text" else ok_generate_text,
    )
    monkeypatch.setattr(
        "sentinel.web.settings_checks.embed_text",
        slow_embed_text if slow_name == "embed_text" else fake_embed_text,
    )
    monkeypatch.setattr(
        "sentinel.web.settings_checks.rerank_scores",
        slow_rerank_scores if slow_name == "rerank_scores" else fake_rerank_scores,
    )

    payload = await RuntimeSettingsCheckService().run_model_checks(FakeSettings())

    failed_rows = [row for row in payload.results if not row.ok]
    assert [row.name for row in payload.results] == ["LLM", "Embedder", "Reranker"]
    assert [row.name for row in failed_rows] == [expected_error_row]
    assert failed_rows[0].error == "check timed out"
