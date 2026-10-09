"""Check Sentinel dependency service configuration health."""

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sentinel.config import get_settings


@dataclass(frozen=True)
class ServiceCheckResult:
    name: str
    target: str
    ok: bool
    detail: str = ""
    error: str | None = None

    def line(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        line = f"[{status}] {self.name} {self.target}"
        if self.detail:
            line = f"{line} ({self.detail})"
        if self.error:
            line = f"{line}: {self.error}"
        return line


@dataclass(frozen=True)
class ServiceFactories:
    neo4j_driver_factory: Callable[..., Any]
    milvus_client_factory: Callable[..., Any]

    @classmethod
    def defaults(cls) -> "ServiceFactories":
        from neo4j import AsyncGraphDatabase
        from pymilvus import MilvusClient

        return cls(
            neo4j_driver_factory=AsyncGraphDatabase.driver,
            milvus_client_factory=MilvusClient,
        )


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
        {secret for secret in secrets if secret}, key=len, reverse=True
    ):
        redacted = redacted.replace(secret, _mask_secret(secret))
    return redacted


def _safe_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.username is None and parsed.password is None:
        return uri

    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    masked = f"***:***@{host}" if host else "***:***"
    return urlunsplit(
        (
            parsed.scheme,
            masked,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


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


async def check_neo4j(
    settings: Any,
    factories: ServiceFactories,
) -> ServiceCheckResult:
    password = settings.require_neo4j_password()
    target = f"{_safe_uri(settings.neo4j_uri)} database={settings.neo4j_database}"
    detail = f"user={settings.neo4j_user} password={_secret_status(password)}"
    driver = None

    try:
        driver = factories.neo4j_driver_factory(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, password),
        )
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run("RETURN 1 AS ok")
            record = await result.single()
            if record is None or record["ok"] != 1:
                raise RuntimeError("unexpected Neo4j health check result")
        return ServiceCheckResult("Neo4j", target, True, detail)
    except Exception as error:
        return ServiceCheckResult(
            "Neo4j",
            target,
            False,
            detail,
            _redact_text(error, [password]),
        )
    finally:
        if driver is not None:
            await _close_async(driver)


def check_milvus(
    settings: Any,
    factories: ServiceFactories,
) -> ServiceCheckResult:
    token = settings.optional_milvus_token()
    target = _safe_uri(settings.milvus_uri)
    detail = f"token={_secret_status(token)}"
    client = None

    try:
        client = factories.milvus_client_factory(uri=settings.milvus_uri, token=token)
        list_collections = getattr(client, "list_collections", None)
        if list_collections is not None:
            list_collections()
        else:
            client.has_collection("__sentinel_health_check__")
        return ServiceCheckResult("Milvus", target, True, detail)
    except Exception as error:
        return ServiceCheckResult(
            "Milvus",
            target,
            False,
            detail,
            _redact_text(error, [token]),
        )
    finally:
        if client is not None:
            _close_sync(client)


async def run_checks(
    settings: Any,
    factories: ServiceFactories,
) -> list[ServiceCheckResult]:
    return [
        await check_neo4j(settings, factories),
        check_milvus(settings, factories),
    ]


def main(
    argv: list[str] | None = None,
    *,
    settings_provider: Callable[[], Any] = get_settings,
    factories: ServiceFactories | None = None,
) -> int:
    del argv

    try:
        settings = settings_provider()
    except Exception as error:
        print(f"[FAIL] Settings failed to load: {error}")
        return 1

    results = asyncio.run(
        run_checks(settings, factories or ServiceFactories.defaults())
    )
    for result in results:
        print(result.line())

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
