from datetime import datetime

import pytest

import sentinel.main as main
from sentinel.config import SentinelSettings
from sentinel.models import EventSource, NormalizedEvent, RiskLevel
from sentinel.pipeline import batch, llm_json


class FakeStashStore:
    def __init__(self, events: list[dict]):
        self.events = events
        self.marked_event_ids: list[str] = []

    async def fetch_related_events(
        self,
        event: NormalizedEvent,
        id_numbers: list[str],
        top_k_semantic: int,
        max_per_person: int,
    ) -> list[dict]:
        return self.events

    async def mark_events_graph_built(self, event_ids: list[str]) -> int:
        self.marked_event_ids.extend(event_ids)
        return len(event_ids)


def make_event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="TRIGGER",
        source=EventSource.NEWS,
        raw_content="trigger P01",
        title="trigger",
        timestamp=datetime(2026, 5, 26, 12, 0, 0),
    )


@pytest.fixture
def app_settings() -> SentinelSettings:
    return SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
        graphiti_dry_run=True,
        graphiti_episode_source="sentinel",
        risk_threshold=0.2,
        search_num_results=10,
        risk_search_num_results=20,
        stash_semantic_top_k=5,
        batch_max_per_person=7,
        stash_rerank_enabled=True,
        stash_rerank_min_score=0.7,
    )


@pytest.mark.asyncio
async def test_evaluate_risk_normalizes_llm_risk_level_to_enum(
    monkeypatch,
    app_settings,
):
    async def fake_generate_text(settings, *, prompt=None, messages=None, **kwargs):
        assert settings is app_settings
        assert "Event type" in (prompt or "")
        assert messages is None
        assert kwargs["model"] == app_settings.llm_model
        return '{"risk_level": "high", "risk_score": "0.91", "reasoning": "需跟进"}'

    monkeypatch.setattr(llm_json, "generate_text", fake_generate_text)

    # When
    result = await main.evaluate_risk(app_settings, make_event())

    # Then
    assert result["risk_level"] is RiskLevel.HIGH


@pytest.mark.asyncio
async def test_batch_graph_dry_run_keeps_consumed_event_records_unmarked(
    monkeypatch, app_settings
):
    stash_store = FakeStashStore(
        [
            {
                "event_id": "E001",
                "raw_content": "history one",
                "person_ids": ["P01"],
                "created_at": "2026-05-25T12:00:00",
            },
            {
                "event_id": "E002",
                "raw_content": "history two",
                "person_ids": ["P01"],
                "created_at": "2026-05-24T12:00:00",
            },
        ]
    )
    batch_inputs = []

    async def fake_init_graph_client(app_settings):
        return object()

    async def fake_close_graph_client(graphiti):
        return None

    async def fake_batch_add_to_graph(
        graphiti, events, group_id, dry_run, app_settings=None
    ):
        del app_settings
        batch_inputs.extend(events)
        return [{"success": True} for _ in events]

    monkeypatch.setattr(batch, "init_graph_client", fake_init_graph_client)
    monkeypatch.setattr(batch, "close_graph_client", fake_close_graph_client)
    monkeypatch.setattr(batch, "batch_add_to_graph", fake_batch_add_to_graph)

    summary = await batch.batch_graph_event_with_related_stash(
        app_settings,
        stash_store,
        ["P01"],
        make_event(),
    )

    assert [item["text"] for item in batch_inputs] == ["history one", "history two"]
    assert stash_store.marked_event_ids == []
    assert summary["fetched_count"] == 2
    assert summary["batched_count"] == 2


@pytest.mark.asyncio
async def test_batch_graph_marks_only_consumed_event_records_on_success(
    monkeypatch, app_settings
):
    app_settings = app_settings.model_copy(update={"graphiti_dry_run": False})
    stash_store = FakeStashStore(
        [
            {
                "event_id": "E001",
                "raw_content": "history one",
                "person_ids": ["P01"],
                "created_at": "2026-05-25T12:00:00",
            },
            {
                "event_id": "E002",
                "raw_content": "history two",
                "person_ids": ["P01"],
                "created_at": "2026-05-24T12:00:00",
            },
        ]
    )
    batch_inputs = []

    async def fake_init_graph_client(app_settings):
        return object()

    async def fake_close_graph_client(graphiti):
        return None

    async def fake_graph_episode_content_count(graphiti, raw_content, group_id):
        return 0

    async def fake_batch_add_to_graph(
        graphiti, events, group_id, dry_run, app_settings=None
    ):
        del app_settings
        batch_inputs.extend(events)
        return [{"success": True} for _ in events]

    monkeypatch.setattr(batch, "init_graph_client", fake_init_graph_client)
    monkeypatch.setattr(batch, "close_graph_client", fake_close_graph_client)
    monkeypatch.setattr(
        batch, "graph_episode_content_count", fake_graph_episode_content_count
    )
    monkeypatch.setattr(batch, "batch_add_to_graph", fake_batch_add_to_graph)

    summary = await batch.batch_graph_event_with_related_stash(
        app_settings,
        stash_store,
        ["P01"],
        make_event(),
    )

    assert [item["text"] for item in batch_inputs] == ["history one", "history two"]
    assert stash_store.marked_event_ids == ["E001", "E002"]
    assert summary["fetched_count"] == 2
    assert summary["batched_count"] == 2


@pytest.mark.asyncio
async def test_batch_graph_skips_when_no_event_records(monkeypatch, app_settings):
    stash_store = FakeStashStore([])
    called = {"batch": 0}

    async def fake_init_graph_client(app_settings):
        return object()

    async def fake_close_graph_client(graphiti):
        return None

    async def fake_batch_add_to_graph(
        graphiti, events, group_id, dry_run, app_settings=None
    ):
        del app_settings
        called["batch"] += 1
        return [{"success": True} for _ in events]

    monkeypatch.setattr(batch, "init_graph_client", fake_init_graph_client)
    monkeypatch.setattr(batch, "close_graph_client", fake_close_graph_client)
    monkeypatch.setattr(batch, "batch_add_to_graph", fake_batch_add_to_graph)

    summary = await batch.batch_graph_event_with_related_stash(
        app_settings,
        stash_store,
        ["P01"],
        make_event(),
    )

    assert called["batch"] == 0
    assert stash_store.marked_event_ids == []
    assert summary["fetched_count"] == 0
    assert summary["batched_count"] == 0


@pytest.mark.asyncio
async def test_batch_graph_keeps_event_records_unmarked_on_failure(
    monkeypatch, app_settings
):
    stash_store = FakeStashStore(
        [
            {
                "event_id": "E001",
                "raw_content": "history one",
                "person_ids": ["P01"],
                "created_at": "2026-05-25T12:00:00",
            }
        ]
    )

    async def fake_init_graph_client(app_settings):
        return object()

    async def fake_close_graph_client(graphiti):
        return None

    async def fake_batch_add_to_graph(
        graphiti, events, group_id, dry_run, app_settings=None
    ):
        del app_settings
        return [{"success": False}]

    monkeypatch.setattr(batch, "init_graph_client", fake_init_graph_client)
    monkeypatch.setattr(batch, "close_graph_client", fake_close_graph_client)
    monkeypatch.setattr(batch, "batch_add_to_graph", fake_batch_add_to_graph)

    summary = await batch.batch_graph_event_with_related_stash(
        app_settings,
        stash_store,
        ["P01"],
        make_event(),
    )

    assert stash_store.marked_event_ids == []
    assert summary["success"] is False


@pytest.mark.asyncio
async def test_single_graph_build_dry_run_keeps_current_event_unmarked(
    monkeypatch, app_settings
):
    event = make_event()
    stash_store = FakeStashStore([])

    async def fake_execute_single_graph_build(app_settings, normalized_event):
        return [{"event_id": normalized_event.event_id, "success": True}]

    monkeypatch.setattr(
        main, "execute_single_graph_build", fake_execute_single_graph_build
    )

    flow = main.SentinelPipelineFlow(
        app_settings,
        event,
        stash_store=stash_store,
        id_numbers=["P01"],
    )

    result = await flow.single_graph_build()

    assert result == {"event_id": "TRIGGER", "success": True}
    assert stash_store.marked_event_ids == []


@pytest.mark.asyncio
async def test_single_graph_build_marks_current_event_after_real_write(
    monkeypatch, app_settings
):
    app_settings = app_settings.model_copy(update={"graphiti_dry_run": False})
    event = make_event()
    stash_store = FakeStashStore([])

    async def fake_execute_single_graph_build(app_settings, normalized_event):
        return [{"event_id": normalized_event.event_id, "success": True}]

    monkeypatch.setattr(
        main, "execute_single_graph_build", fake_execute_single_graph_build
    )

    flow = main.SentinelPipelineFlow(
        app_settings,
        event,
        stash_store=stash_store,
        id_numbers=["P01"],
    )

    result = await flow.single_graph_build()

    assert result == {"event_id": "TRIGGER", "success": True}
    assert stash_store.marked_event_ids == ["TRIGGER"]


@pytest.mark.asyncio
async def test_low_risk_flow_reuses_first_context_and_skips_batch_path(
    monkeypatch, app_settings
):
    event = make_event()
    dashboard_calls = []
    batch_calls = []

    async def fake_execute_classification(app_settings, normalized_event):
        normalized_event.event_type = "社区活动"
        normalized_event.summary = "低风险事件"
        return normalized_event

    async def fake_simulate_graph_build(app_settings, normalized_event):
        return [{"event_id": normalized_event.event_id, "success": True}]

    async def fake_evaluate_risk(app_settings, normalized_event, results=None):
        return {
            "risk_level": RiskLevel.LOW,
            "risk_score": 0.1,
            "reasoning": "低风险",
        }

    async def fake_simulate_search(app_settings, normalized_event, num_results=None):
        return {
            "results": [{"type": "edge", "text": "first context"}],
            "reranked_edges": [{"text": "first context"}],
            "reranked_episodes": [],
        }

    async def fake_batch_graph_event_with_related_stash(
        app_settings, stash_store, id_numbers, normalized_event
    ):
        batch_calls.append(normalized_event.event_id)
        return {"success": True}

    async def fake_simulate_dashboard(app_settings, normalized_event, results):
        dashboard_calls.append(normalized_event.event_id)
        return None

    monkeypatch.setattr(main, "execute_classification", fake_execute_classification)
    monkeypatch.setattr(main, "execute_single_graph_build", fake_simulate_graph_build)
    monkeypatch.setattr(main, "evaluate_risk", fake_evaluate_risk)
    monkeypatch.setattr(main, "execute_search", fake_simulate_search)
    monkeypatch.setattr(
        main,
        "batch_graph_event_with_related_stash",
        fake_batch_graph_event_with_related_stash,
    )
    monkeypatch.setattr(main, "execute_dashboard", fake_simulate_dashboard)

    stash_store = FakeStashStore([])
    flow = main.SentinelPipelineFlow(
        app_settings,
        event,
        stash_store=stash_store,
        id_numbers=["P01"],
    )

    await flow.kickoff_async()

    assert batch_calls == []
    assert dashboard_calls == []
    assert stash_store.marked_event_ids == []


@pytest.mark.asyncio
async def test_high_risk_flow_uses_second_context_after_batch_graph(
    monkeypatch, app_settings
):
    event = make_event()
    search_calls = []
    batch_calls = []
    second_risk_calls = []
    dashboard_context_sizes = []

    async def fake_execute_classification(app_settings, normalized_event):
        normalized_event.event_type = "公共安全"
        normalized_event.summary = "高风险事件"
        return normalized_event

    async def fake_simulate_graph_build(app_settings, normalized_event):
        return [{"event_id": normalized_event.event_id, "success": True}]

    async def fake_evaluate_risk(app_settings, normalized_event, results=None):
        return {
            "risk_level": RiskLevel.HIGH,
            "risk_score": 0.9,
            "reasoning": "首次超阈值",
        }

    async def fake_batch_graph_event_with_related_stash(
        app_settings, stash_store, id_numbers, normalized_event
    ):
        batch_calls.append(normalized_event.event_id)
        return {"success": True, "fetched_count": 2, "batched_count": 2}

    async def fake_simulate_search(app_settings, normalized_event, num_results=None):
        search_calls.append(num_results)
        if len(search_calls) == 1:
            return {
                "results": [{"type": "edge", "text": "first context"}],
                "reranked_edges": [{"text": "first context"}],
                "reranked_episodes": [],
            }
        return {
            "results": [{"type": "edge", "text": "second context"}],
            "reranked_edges": [{"text": "second context"}],
            "reranked_episodes": [],
        }

    async def fake_second_evaluate_risk(app_settings, normalized_event, results):
        second_risk_calls.append(len(results.get("results", [])))
        return {
            "risk_level": RiskLevel.MEDIUM,
            "risk_score": 0.6,
            "reasoning": "二次评估",
        }

    async def fake_simulate_dashboard(app_settings, normalized_event, results):
        dashboard_context_sizes.append(len(results.get("results", [])))
        return None

    monkeypatch.setattr(main, "execute_classification", fake_execute_classification)
    monkeypatch.setattr(main, "execute_single_graph_build", fake_simulate_graph_build)
    monkeypatch.setattr(main, "evaluate_risk", fake_evaluate_risk)
    monkeypatch.setattr(
        main,
        "batch_graph_event_with_related_stash",
        fake_batch_graph_event_with_related_stash,
    )
    monkeypatch.setattr(main, "execute_search", fake_simulate_search)
    monkeypatch.setattr(main, "second_evaluate_risk", fake_second_evaluate_risk)
    monkeypatch.setattr(main, "execute_dashboard", fake_simulate_dashboard)

    stash_store = FakeStashStore([])
    flow = main.SentinelPipelineFlow(
        app_settings,
        event,
        stash_store=stash_store,
        id_numbers=["P01"],
    )

    await flow.kickoff_async()

    assert batch_calls == ["TRIGGER"]
    assert search_calls == [20, 20]
    assert second_risk_calls == [1]
    assert dashboard_context_sizes == [1]
    assert stash_store.marked_event_ids == []


@pytest.mark.asyncio
async def test_second_risk_below_threshold_completes_without_dashboard(
    monkeypatch, app_settings
):
    event = make_event()
    dashboard_calls = []

    async def fake_execute_classification(app_settings, normalized_event):
        normalized_event.event_type = "公共安全"
        normalized_event.summary = "高风险事件"
        return normalized_event

    async def fake_simulate_graph_build(app_settings, normalized_event):
        return [{"event_id": normalized_event.event_id, "success": True}]

    async def fake_evaluate_risk(app_settings, normalized_event, results=None):
        return {
            "risk_level": RiskLevel.HIGH,
            "risk_score": 0.9,
            "reasoning": "首次超阈值",
        }

    async def fake_batch_graph_event_with_related_stash(
        app_settings, stash_store, id_numbers, normalized_event
    ):
        return {"success": True, "fetched_count": 1, "batched_count": 1}

    async def fake_simulate_search(app_settings, normalized_event, num_results=None):
        return {
            "results": [{"type": "edge", "text": "context"}],
            "reranked_edges": [{"text": "context"}],
            "reranked_episodes": [],
        }

    async def fake_second_evaluate_risk(app_settings, normalized_event, results):
        return {
            "risk_level": RiskLevel.MEDIUM,
            "risk_score": 0.2,
            "reasoning": "二次评估回落到阈值",
        }

    async def fake_simulate_dashboard(app_settings, normalized_event, results):
        dashboard_calls.append(normalized_event.event_id)
        return None

    monkeypatch.setattr(main, "execute_classification", fake_execute_classification)
    monkeypatch.setattr(main, "execute_single_graph_build", fake_simulate_graph_build)
    monkeypatch.setattr(main, "evaluate_risk", fake_evaluate_risk)
    monkeypatch.setattr(
        main,
        "batch_graph_event_with_related_stash",
        fake_batch_graph_event_with_related_stash,
    )
    monkeypatch.setattr(main, "execute_search", fake_simulate_search)
    monkeypatch.setattr(main, "second_evaluate_risk", fake_second_evaluate_risk)
    monkeypatch.setattr(main, "execute_dashboard", fake_simulate_dashboard)

    flow = main.SentinelPipelineFlow(
        app_settings,
        event,
        stash_store=FakeStashStore([]),
        id_numbers=["P01"],
    )
    await flow.kickoff_async()

    assert dashboard_calls == []


# =====================================================================
# Regression: sentinel.graph must be import-safe (no ValueError
# raised at module level when LLM_API_KEY / Neo4j creds are missing).
# =====================================================================


def test_import_graph_without_llm_key():
    """`import sentinel.graph` must not raise ValueError
    when LLM_API_KEY is missing from the environment."""
    import os
    import subprocess
    import sys

    workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    env.pop("LLM_API_KEY", None)

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; os.environ.pop('LLM_API_KEY', None); "
            "import sys; sys.path.insert(0, '.'); "
            "import sentinel.graph as graph; "
            'print("IMPORT_OK")',
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=workdir,
        timeout=15,
    )
    assert "IMPORT_OK" in proc.stdout, (
        f"subprocess stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_init_graph_client_rejects_missing_llm_key():
    from pydantic import ValidationError

    from sentinel.config import SentinelSettings

    with pytest.raises(ValidationError, match="llm_api_key"):
        SentinelSettings(
            _env_file=None,
            neo4j_password="neo4j",
            llm_api_key="",
        )


@pytest.mark.asyncio
async def test_init_graph_client_uses_settings_for_database(monkeypatch):
    from sentinel.config import SentinelSettings
    from sentinel.graph import init_graph_client

    captured = {}

    class FakeGraphiti:
        def __init__(self, *args, **kwargs):
            captured["graphiti_args"] = args
            captured["graphiti_kwargs"] = kwargs
            self.llm_client = kwargs["llm_client"]
            self.embedder = kwargs["embedder"]
            self.cross_encoder = kwargs["cross_encoder"]
            self.driver = kwargs["graph_driver"]

        async def build_indices_and_constraints(self):
            captured["built"] = True

    class FakeNeo4jDriver:
        def __init__(self, uri, user, password, *, database):
            captured["neo4j_driver"] = {
                "uri": uri,
                "user": user,
                "password": password,
                "database": database,
            }

    monkeypatch.setattr("sentinel.graph.client.Graphiti", FakeGraphiti)
    monkeypatch.setattr("sentinel.graph.client.Neo4jDriver", FakeNeo4jDriver)

    settings = SentinelSettings(
        _env_file=None,
        neo4j_uri="bolt://neo4j.example:7687",
        neo4j_user="neo4j-user",
        neo4j_password="neo4j-secret",
        neo4j_database="sentinel_test",
        llm_api_key="llm-secret",
        llm_model="gpt-test",
        llm_base_url="https://llm.example/v1",
    )

    graphiti = await init_graph_client(settings)

    assert graphiti is not None
    assert captured["built"] is True
    assert captured["neo4j_driver"]["database"] == "sentinel_test"
