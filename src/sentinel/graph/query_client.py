"""面向查询侧的 Graphiti 检索客户端。"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase, Query

from sentinel.config import SentinelSettings, get_settings


class ReadOnlyGraphDriver:
    def __init__(self, settings: SentinelSettings) -> None:
        self._client = AsyncGraphDatabase.driver(
            uri=settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.require_neo4j_password()),
        )
        self._database = settings.neo4j_database

    async def execute_query(self, cypher_query_: str, **kwargs: Any) -> Any:
        params = kwargs.pop("params", None)
        timeout = kwargs.pop("timeout_", None)
        if timeout is not None:
            cypher_query_ = Query(cypher_query_, timeout=timeout)
        kwargs.setdefault("database_", self._database)
        return await self._client.execute_query(
            cypher_query_,
            parameters_=params,
            **kwargs,
        )

    async def close(self) -> None:
        await self._client.close()


class ReadOnlyGraphClient:
    def __init__(self, settings: SentinelSettings) -> None:
        self.driver = ReadOnlyGraphDriver(settings)

    async def close(self) -> None:
        await self.driver.close()


async def init_read_only_graph_client(
    app_settings: SentinelSettings | None = None,
) -> ReadOnlyGraphClient:
    settings = app_settings or get_settings()
    return ReadOnlyGraphClient(settings)
