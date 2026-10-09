import pytest
from neo4j import Query

from sentinel.config import SentinelSettings
from sentinel.graph.query_client import ReadOnlyGraphDriver


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


class FakeAsyncNeo4jDriver:
    def __init__(self) -> None:
        self.query = None
        self.kwargs = None

    async def execute_query(self, query, **kwargs):
        if "timeout_" in kwargs:
            raise ValueError("keyword parameters must not end with a single '_'")
        self.query = query
        self.kwargs = kwargs
        return [{"ok": True}], None, None

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_read_only_graph_driver_translates_timeout_to_neo4j_query(
    monkeypatch,
):
    fake_driver = FakeAsyncNeo4jDriver()

    def fake_driver_factory(**kwargs):
        assert kwargs["uri"] == "bolt://localhost:7687"
        return fake_driver

    monkeypatch.setattr(
        "sentinel.graph.query_client.AsyncGraphDatabase.driver",
        fake_driver_factory,
    )
    driver = ReadOnlyGraphDriver(make_settings())

    result = await driver.execute_query(
        "RETURN $value AS value",
        params={"value": 1},
        routing_="r",
        timeout_=5,
    )

    assert result == ([{"ok": True}], None, None)
    assert isinstance(fake_driver.query, Query)
    assert fake_driver.query.text == "RETURN $value AS value"
    assert fake_driver.query.timeout == 5
    assert fake_driver.kwargs == {
        "parameters_": {"value": 1},
        "routing_": "r",
        "database_": "neo4j",
    }
