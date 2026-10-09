import pytest

from scripts import reset_and_seed_demo_state as reset_script
from scripts.reset_and_seed_demo_state import (
    DemoStateResetSummary,
    reset_milvus_collection,
    reset_neo4j_graph,
)


class FakeNeo4jResult:
    def __init__(self, node_count: int) -> None:
        self._node_count = node_count

    async def single(self) -> dict[str, int]:
        return {"node_count": self._node_count}


class FakeNeo4jSession:
    def __init__(self, node_count: int) -> None:
        self.node_count = node_count
        self.query = ""

    async def __aenter__(self) -> "FakeNeo4jSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def run(self, query: str) -> FakeNeo4jResult:
        self.query = query
        return FakeNeo4jResult(self.node_count)


class FakeNeo4jDriver:
    def __init__(self, node_count: int) -> None:
        self.closed = False
        self.session_kwargs: dict[str, str] = {}
        self.session_obj = FakeNeo4jSession(node_count)

    def session(self, **kwargs: str) -> FakeNeo4jSession:
        self.session_kwargs = kwargs
        return self.session_obj

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_reset_neo4j_graph_deletes_all_nodes_and_closes_driver() -> None:
    driver = FakeNeo4jDriver(node_count=7)
    factory_calls: list[tuple[str, tuple[str, str]]] = []

    def driver_factory(uri: str, auth: tuple[str, str]) -> FakeNeo4jDriver:
        factory_calls.append((uri, auth))
        return driver

    deleted_count = await reset_neo4j_graph(
        uri="bolt://neo4j:7687",
        user="neo4j",
        password="password",
        database="neo4j",
        driver_factory=driver_factory,
    )

    assert deleted_count == 7
    assert factory_calls == [("bolt://neo4j:7687", ("neo4j", "password"))]
    assert driver.session_kwargs == {"database": "neo4j"}
    assert "DETACH DELETE" in driver.session_obj.query
    assert driver.closed is True


class FakeMilvusClient:
    def __init__(self, *, uri: str, token: str | None) -> None:
        self.uri = uri
        self.token = token
        self.collections = {"input_events"}
        self.dropped: list[str] = []
        self.closed = False

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def drop_collection(self, collection_name: str) -> None:
        self.collections.remove(collection_name)
        self.dropped.append(collection_name)

    def close(self) -> None:
        self.closed = True


def test_reset_milvus_collection_drops_existing_collection() -> None:
    clients: list[FakeMilvusClient] = []

    def client_factory(*, uri: str, token: str | None) -> FakeMilvusClient:
        client = FakeMilvusClient(uri=uri, token=token)
        clients.append(client)
        return client

    dropped = reset_milvus_collection(
        uri="http://localhost:19530",
        token="",
        collection_name="input_events",
        client_factory=client_factory,
    )

    assert dropped is True
    assert clients[0].token is None
    assert clients[0].dropped == ["input_events"]
    assert clients[0].closed is True


@pytest.mark.asyncio
async def test_reset_and_seed_demo_state_resets_all_databases_and_uses_batch_seed(
    monkeypatch,
) -> None:
    reset_calls: list[str] = []

    class FakeSettings:
        neo4j_uri = "bolt://neo4j:7687"
        neo4j_user = "neo4j"
        neo4j_database = "neo4j"
        milvus_uri = "http://milvus.local:19530"
        milvus_input_events_collection = "input_events"
        kv_ttl_days = 90
        stash_semantic_top_k = 10
        stash_rerank_min_score = 0.7
        stash_rerank_enabled = True
        batch_max_per_person = 20
        embedding_dim = 3
        embedder_model = "embedder"
        effective_embedder_api_base = "https://embedder.local/v1"

        def require_neo4j_password(self) -> str:
            return "neo4j-password"

        def optional_milvus_token(self) -> str:
            return "token"

        def effective_embedder_api_key_value(self) -> str:
            return "embed-key"

    class FakePersons:
        def __init__(self) -> None:
            self.person_batches: list[list[str]] = []

        async def append_person(self, person_id: str) -> None:
            raise AssertionError("seed persons should use append_persons()")

        async def append_persons(self, person_ids: list[str]) -> int:
            self.person_batches.append(person_ids)
            return len(person_ids)

    class FakeKeywords:
        def __init__(self) -> None:
            self.keyword_batches: list[list[str]] = []

        async def append_keyword(self, keyword: str) -> None:
            raise AssertionError("seed keywords should use append_keywords()")

        async def append_keywords(self, keywords: list[str]) -> int:
            self.keyword_batches.append(keywords)
            return len(keywords)

    class FakeEvents:
        def __init__(self) -> None:
            self.event_batches: list[list[tuple[str, str]]] = []

        async def append_event(self, event_id: str, summary: str) -> None:
            raise AssertionError("seed events should use append_events()")

        async def append_events(self, events: list[tuple[str, str]]) -> int:
            self.event_batches.append(events)
            return len(events)

    class FakeBundle:
        def __init__(self) -> None:
            self.persons = FakePersons()
            self.keywords = FakeKeywords()
            self.event_samples = FakeEvents()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    fake_bundle = FakeBundle()

    async def fake_reset_neo4j_graph(**kwargs: object) -> int:
        return 7

    def fake_reset_milvus_collection(
        *, uri: str, token: str, collection_name: str
    ) -> bool:
        assert uri == "http://milvus.local:19530"
        assert token == "token"
        reset_calls.append(collection_name)
        return collection_name != "blacklist_event_samples"

    monkeypatch.setattr(reset_script, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(reset_script, "reset_neo4j_graph", fake_reset_neo4j_graph)
    monkeypatch.setattr(
        reset_script,
        "milvus_collection_names",
        lambda config: ("blacklist_event_samples", "input_events"),
    )
    monkeypatch.setattr(
        reset_script, "reset_milvus_collection", fake_reset_milvus_collection
    )
    monkeypatch.setattr(reset_script, "create_store_bundle", lambda config: fake_bundle)

    summary = await reset_script.reset_and_seed_demo_state()

    assert isinstance(summary, DemoStateResetSummary)
    assert summary.neo4j_database == "neo4j"
    assert summary.deleted_neo4j_nodes == 7
    assert summary.dropped_milvus_collections == {
        "blacklist_event_samples": False,
        "input_events": True,
    }
    assert summary.person_count == len(reset_script.PERSON_SEEDS)
    assert summary.keyword_count == len(reset_script.KEYWORD_SEEDS)
    assert summary.event_count == len(reset_script.EVENT_SEEDS)
    assert reset_calls == ["blacklist_event_samples", "input_events"]
    assert fake_bundle.persons.person_batches == [reset_script.PERSON_SEEDS]
    assert fake_bundle.keywords.keyword_batches == [reset_script.KEYWORD_SEEDS]
    assert fake_bundle.event_samples.event_batches == [reset_script.EVENT_SEEDS]
    assert fake_bundle.closed is True


def test_format_reset_summary_lists_destructive_targets() -> None:
    summary = DemoStateResetSummary(
        neo4j_database="neo4j",
        deleted_neo4j_nodes=7,
        dropped_milvus_collections={
            "blacklist_event_samples": False,
            "input_events": True,
        },
        person_count=1,
        keyword_count=35,
        event_count=9,
    )

    lines = reset_script.format_reset_summary(summary)

    assert lines == [
        "Reset demo state and seeded blacklist Milvus:",
        "  Neo4j (neo4j): deleted 7 graph nodes",
        "  Seeded 1 persons, 35 keywords, 9 events",
        "  Milvus collection blacklist_event_samples: not found",
        "  Milvus collection input_events: dropped",
    ]
