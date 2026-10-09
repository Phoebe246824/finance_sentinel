import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentinel.config import SentinelSettings
from sentinel.dashboard import create_dashboard_app


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def test_create_dashboard_app_accepts_uvicorn_factory_call(monkeypatch):
    monkeypatch.setattr("sentinel.dashboard.get_settings", make_settings)

    app = create_dashboard_app()

    assert isinstance(app, FastAPI)


def test_create_dashboard_app_loads_profile_before_runtime_setup(monkeypatch):
    def fail_profile_load():
        raise FileNotFoundError("missing profile")

    def fail_task_manager(*args, **kwargs):
        raise AssertionError("task manager must not initialize before profile")

    monkeypatch.setattr(
        "sentinel.dashboard.get_profile_config", fail_profile_load, raising=False
    )
    monkeypatch.setattr("sentinel.dashboard.AnalysisTaskManager", fail_task_manager)

    with pytest.raises(FileNotFoundError, match="missing profile"):
        create_dashboard_app(make_settings())


def test_create_dashboard_app_registers_dashboard_routes():
    app = create_dashboard_app(make_settings())

    route_paths = {route.path for route in app.routes}
    route_methods = {}
    for route in app.routes:
        route_methods.setdefault(route.path, set()).update(
            getattr(route, "methods", set())
        )

    assert "/" in route_paths
    assert "/api/events" in route_paths
    assert "/api/stats" in route_paths
    assert "/api/stats/risk-distribution" in route_paths
    assert "/api/stats/source-distribution" in route_paths
    assert "/api/auth/login" in route_paths
    assert "/api/user/info" in route_paths
    assert "/api/dashboard/overview" in route_paths
    assert "/api/graph/person" in route_paths
    assert "/api/blacklist/persons" in route_paths
    assert "/api/blacklist/persons:batch" in route_paths
    assert "/api/blacklist/keywords" in route_paths
    assert "/api/blacklist/keywords:batch" in route_paths
    assert "/api/blacklist/events" in route_paths
    assert "/api/blacklist/events/{sample_id}" in route_paths
    assert "/api/blacklist/events/{sample_id}/enabled" in route_paths
    assert route_methods["/api/blacklist/persons"] == {"GET"}
    assert route_methods["/api/blacklist/persons:batch"] == {"POST"}
    assert route_methods["/api/blacklist/keywords"] == {"GET"}
    assert route_methods["/api/blacklist/keywords:batch"] == {"POST"}
    assert route_methods["/api/blacklist/events"] == {"GET", "POST"}
    assert route_methods["/api/blacklist/events/{sample_id}"] == {"PUT", "DELETE"}
    assert route_methods["/api/blacklist/events/{sample_id}/enabled"] == {"PATCH"}


def test_create_dashboard_app_initializes_runtime_dependencies():
    app = create_dashboard_app(make_settings())

    assert app.state.settings is not None
    assert getattr(app.state, "analysis_task_manager", None) is not None
    assert getattr(app.state, "event_repository_factory", None) is not None


def test_create_dashboard_app_initializes_runtime_settings_manager():
    app = create_dashboard_app(make_settings())

    assert getattr(app.state, "runtime_settings", None) is not None


def test_create_dashboard_app_exposes_runtime_settings_service():
    app = create_dashboard_app(make_settings())

    assert getattr(app.state, "runtime_settings_service", None) is not None


def test_create_dashboard_app_initializes_graph_queries():
    app = create_dashboard_app(make_settings())

    assert getattr(app.state, "graph_queries", None) is not None


@pytest.mark.asyncio
async def test_dashboard_graph_queries_use_read_only_client(monkeypatch):
    calls: list[str] = []

    class FakeReadOnlyGraph:
        def __init__(self) -> None:
            self.driver = self

        async def execute_query(self, query: str, **kwargs):
            del kwargs
            calls.append(query)
            if "count(n)" in query:
                return [{"node_count": 12}], None, None
            return [{"edge_count": 34}], None, None

        async def close(self) -> None:
            calls.append("close")

    async def fake_read_only_client(settings):
        assert settings.neo4j_database == "neo4j"
        calls.append("init_read_only")
        return FakeReadOnlyGraph()

    async def forbidden_graph_client(settings):
        del settings
        raise AssertionError("dashboard graph queries must not initialize Graphiti")

    monkeypatch.setattr(
        "sentinel.dashboard.init_read_only_graph_client",
        fake_read_only_client,
    )
    monkeypatch.setattr("sentinel.graph.init_graph_client", forbidden_graph_client)
    app = create_dashboard_app(make_settings())

    counts = await app.state.graph_queries.fetch_graph_counts()

    assert counts == {"graph_node_count": 12, "graph_edge_count": 34}
    assert calls[0] == "init_read_only"
    assert calls[-1] == "close"


@pytest.mark.asyncio
async def test_dashboard_graph_counts_are_ttl_cached(monkeypatch):
    calls: list[str] = []

    class FakeReadOnlyGraph:
        def __init__(self) -> None:
            self.driver = self

        async def execute_query(self, query: str, **kwargs):
            del kwargs
            calls.append(query)
            if "count(n)" in query:
                return [{"node_count": 12}], None, None
            return [{"edge_count": 34}], None, None

        async def close(self) -> None:
            calls.append("close")

    async def fake_read_only_client(settings):
        del settings
        calls.append("init_read_only")
        return FakeReadOnlyGraph()

    monkeypatch.setattr(
        "sentinel.dashboard.init_read_only_graph_client",
        fake_read_only_client,
    )
    app = create_dashboard_app(make_settings())

    first = await app.state.graph_queries.fetch_graph_counts()
    second = await app.state.graph_queries.fetch_graph_counts()

    assert first == {"graph_node_count": 12, "graph_edge_count": 34}
    assert second == first
    assert calls.count("init_read_only") == 1
    assert calls.count("close") == 1


def test_dashboard_graph_queries_use_configured_graph_group():
    settings = make_settings(graphiti_episode_source="sentinel-prod")
    app = create_dashboard_app(settings)

    assert app.state.graph_queries.group_id == "sentinel-prod"


def test_dashboard_app_closes_runtime_store_bundle_on_shutdown(monkeypatch):
    calls: list[str] = []

    class FakeBundle:
        events = object()

    class FakeTaskManager:
        def __init__(self, **kwargs):
            self._repository = kwargs["repository"]

        async def shutdown(self) -> None:
            calls.append("shutdown")

    async def fake_runtime_store_bundle(config):
        assert config["milvus"]["uri"]
        calls.append("get")
        return FakeBundle()

    async def fake_reset_runtime_store_bundle_cache():
        calls.append("reset")

    monkeypatch.setattr(
        "sentinel.dashboard.get_runtime_store_bundle",
        fake_runtime_store_bundle,
    )
    monkeypatch.setattr(
        "sentinel.dashboard.reset_runtime_store_bundle_cache_async",
        fake_reset_runtime_store_bundle_cache,
        raising=False,
    )
    monkeypatch.setattr("sentinel.dashboard.AnalysisTaskManager", FakeTaskManager)

    with TestClient(create_dashboard_app(make_settings())):
        pass

    assert calls == ["get", "shutdown", "reset"]
