"""设置页的服务健康检查：结果模型与检查服务编排。"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from sentinel.utils.litellm_embedding import embed_text
from sentinel.utils.litellm_rerank import rerank_scores
from sentinel.utils.litellm_text import generate_text

THINKING_DISABLED_EXTRA_BODY = {
    "enable_thinking": False,
    "thinking": {"type": "disabled"},
}
CHECK_TIMEOUT_SECONDS = 15.0


class SettingsCheckResultPayload(BaseModel):
    name: str
    kind: Literal["service", "model"]
    ok: bool
    target: str
    detail: str = ""
    error: str | None = None
    duration_ms: int


class SettingsCheckResponsePayload(BaseModel):
    checked_at: str
    results: list[SettingsCheckResultPayload]


@dataclass(frozen=True)
class ServiceCheckFactories:
    neo4j_driver_factory: Callable[..., Any]
    milvus_client_factory: Callable[..., Any]

    @classmethod
    def defaults(cls) -> ServiceCheckFactories:
        from neo4j import AsyncGraphDatabase
        from pymilvus import MilvusClient

        return cls(
            neo4j_driver_factory=AsyncGraphDatabase.driver,
            milvus_client_factory=MilvusClient,
        )


class RuntimeSettingsCheckService:
    def __init__(
        self,
        *,
        service_factories: ServiceCheckFactories | None = None,
    ) -> None:
        self._service_factories = service_factories or ServiceCheckFactories.defaults()

    async def run_service_checks(self, settings: Any) -> SettingsCheckResponsePayload:
        secrets = [
            settings.require_neo4j_password(),
            settings.optional_milvus_token(),
        ]
        return SettingsCheckResponsePayload(
            checked_at=_checked_at(),
            results=[
                await self._check_neo4j(settings, secrets),
                await self._check_milvus(settings, secrets),
            ],
        )

    async def run_model_checks(self, settings: Any) -> SettingsCheckResponsePayload:
        llm_api_key = settings.require_llm_api_key()
        embedder_api_key = settings.effective_embedder_api_key_value()
        reranker_api_key = settings.effective_reranker_api_key_value()
        secrets = [llm_api_key, embedder_api_key, reranker_api_key]
        return SettingsCheckResponsePayload(
            checked_at=_checked_at(),
            results=[
                await self._check_llm(settings, llm_api_key, secrets),
                await self._check_embedder(settings, embedder_api_key, secrets),
                await self._check_reranker(settings, reranker_api_key, secrets),
            ],
        )

    async def _check_neo4j(
        self,
        settings: Any,
        secrets: list[str | None],
    ) -> SettingsCheckResultPayload:
        password = settings.require_neo4j_password()
        target = f"{_safe_uri(settings.neo4j_uri)} database={settings.neo4j_database}"
        detail = f"user={settings.neo4j_user} password={_secret_status(password)}"
        started_at = time.perf_counter()
        driver = None
        try:
            driver = self._service_factories.neo4j_driver_factory(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, password),
            )
            await _with_timeout(
                self._probe_neo4j(driver, database=settings.neo4j_database),
            )
            return SettingsCheckResultPayload(
                name="Neo4j",
                kind="service",
                ok=True,
                target=target,
                detail=detail,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return SettingsCheckResultPayload(
                name="Neo4j",
                kind="service",
                ok=False,
                target=target,
                detail=detail,
                error=_check_error(exc, secrets),
                duration_ms=_duration_ms(started_at),
            )
        finally:
            if driver is not None:
                await _close_async(driver)

    async def _probe_neo4j(self, driver: Any, *, database: str) -> None:
        async with driver.session(database=database) as session:
            result = await session.run("RETURN 1 AS ok")
            record = await result.single()
            if record is None or record["ok"] != 1:
                raise RuntimeError("unexpected Neo4j health check result")

    async def _check_milvus(
        self,
        settings: Any,
        secrets: list[str | None],
    ) -> SettingsCheckResultPayload:
        token = settings.optional_milvus_token()
        target = _safe_uri(settings.milvus_uri)
        detail = f"token={_secret_status(token)}"
        started_at = time.perf_counter()
        try:
            await _with_timeout(
                asyncio.to_thread(self._probe_milvus, settings.milvus_uri, token),
            )
            return SettingsCheckResultPayload(
                name="Milvus",
                kind="service",
                ok=True,
                target=target,
                detail=detail,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return SettingsCheckResultPayload(
                name="Milvus",
                kind="service",
                ok=False,
                target=target,
                detail=detail,
                error=_check_error(exc, secrets),
                duration_ms=_duration_ms(started_at),
            )

    def _probe_milvus(self, uri: str, token: str | None) -> None:
        client = None
        try:
            client = self._service_factories.milvus_client_factory(
                uri=uri,
                token=token,
            )
            list_collections = getattr(client, "list_collections", None)
            if list_collections is not None:
                list_collections()
            else:
                client.has_collection("__sentinel_health_check__")
        finally:
            if client is not None:
                _close_sync(client)

    async def _check_llm(
        self,
        settings: Any,
        api_key: str,
        secrets: list[str | None],
    ) -> SettingsCheckResultPayload:
        target = settings.llm_model
        detail = (
            f"provider={settings.llm_provider} base_url={_safe_uri(settings.llm_base_url)} "
            f"api_key={_secret_status(api_key)}"
        )
        started_at = time.perf_counter()
        try:
            await _with_timeout(
                generate_text(
                    settings,
                    prompt="ping",
                    model=settings.llm_model,
                    api_key=api_key,
                    base_url=settings.llm_base_url,
                    temperature=0,
                    max_completion_tokens=4,
                    extra_body=THINKING_DISABLED_EXTRA_BODY,
                    timeout=CHECK_TIMEOUT_SECONDS,
                )
            )
            return SettingsCheckResultPayload(
                name="LLM",
                kind="model",
                ok=True,
                target=target,
                detail=detail,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return SettingsCheckResultPayload(
                name="LLM",
                kind="model",
                ok=False,
                target=target,
                detail=detail,
                error=_check_error(exc, secrets),
                duration_ms=_duration_ms(started_at),
            )

    async def _check_embedder(
        self,
        settings: Any,
        api_key: str,
        secrets: list[str | None],
    ) -> SettingsCheckResultPayload:
        target = settings.embedder_model
        detail = (
            f"base_url={_safe_uri(settings.effective_embedder_api_base)} "
            f"api_key={_secret_status(api_key)}"
        )
        started_at = time.perf_counter()
        try:
            await _with_timeout(
                embed_text(
                    settings,
                    "x",
                    model=settings.embedder_model,
                    api_key=api_key,
                    base_url=settings.effective_embedder_api_base,
                )
            )
            return SettingsCheckResultPayload(
                name="Embedder",
                kind="model",
                ok=True,
                target=target,
                detail=detail,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return SettingsCheckResultPayload(
                name="Embedder",
                kind="model",
                ok=False,
                target=target,
                detail=detail,
                error=_check_error(exc, secrets),
                duration_ms=_duration_ms(started_at),
            )

    async def _check_reranker(
        self,
        settings: Any,
        api_key: str,
        secrets: list[str | None],
    ) -> SettingsCheckResultPayload:
        target = settings.effective_reranker_model
        detail = (
            f"base_url={_safe_uri(settings.effective_reranker_base_url)} "
            f"api_key={_secret_status(api_key)}"
        )
        started_at = time.perf_counter()
        try:
            await _with_timeout(
                rerank_scores(
                    query="x",
                    documents=["x"],
                    model=settings.effective_reranker_model,
                    api_key=api_key,
                    base_url=settings.effective_reranker_base_url,
                )
            )
            return SettingsCheckResultPayload(
                name="Reranker",
                kind="model",
                ok=True,
                target=target,
                detail=detail,
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return SettingsCheckResultPayload(
                name="Reranker",
                kind="model",
                ok=False,
                target=target,
                detail=detail,
                error=_check_error(exc, secrets),
                duration_ms=_duration_ms(started_at),
            )


def _checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _duration_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _secret_status(value: str | None) -> str:
    return "***" if value else "<none>"


def _mask_secret(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _redact_text(value: object, secrets: list[str | None]) -> str:
    redacted = str(value)
    for secret in sorted(
        {secret for secret in secrets if secret},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(secret, _mask_secret(secret))
    return redacted


def _check_error(exc: Exception, secrets: list[str | None]) -> str:
    if isinstance(exc, TimeoutError):
        return "check timed out"
    return _redact_text(exc, secrets)


def _safe_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if not parsed.scheme and not parsed.netloc:
        return uri
    if parsed.username is None and parsed.password is None:
        masked = parsed.netloc
    else:
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        masked = f"***:***@{host}" if host else "***:***"
    return urlunsplit(
        (
            parsed.scheme,
            masked,
            parsed.path,
            "",
            "",
        )
    )


async def _with_timeout(awaitable: Any) -> Any:
    return await asyncio.wait_for(awaitable, timeout=CHECK_TIMEOUT_SECONDS)


async def _maybe_await(value: Any) -> None:
    if inspect.isawaitable(value):
        await value


async def _close_async(resource: Any) -> None:
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is not None:
        await _maybe_await(close())


def _close_sync(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if close is not None:
        close()
