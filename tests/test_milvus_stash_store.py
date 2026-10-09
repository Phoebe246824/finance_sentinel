"""Tests for the Milvus stash store compatibility wrapper."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import pytest

from sentinel.blacklist.milvus_stash import MilvusStashStore
from sentinel.blacklist.stores.events_schema import events_fields
from sentinel.models import EventSource, NormalizedEvent


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict] = []

    def add_index(self, **kwargs) -> None:
        self.indexes.append(kwargs)


class FakeMilvusSchema:
    def __init__(self, *, auto_id: bool, enable_dynamic_field: bool) -> None:
        self.auto_id = auto_id
        self.enable_dynamic_field = enable_dynamic_field
        self.fields: list[dict] = []

    def add_field(self, **kwargs) -> None:
        self.fields.append(kwargs)


class FakeMilvusClient:
    created_schemas: list[FakeMilvusSchema] = []

    def __init__(self, reject_empty_query_without_limit: bool = False):
        self.rows: dict[str, dict] = {}
        self.created_collections: list[dict] = []
        self.query_calls: list[dict] = []
        self.reject_empty_query_without_limit = reject_empty_query_without_limit
        self.existing_schema: dict | None = None

    @classmethod
    def create_schema(
        cls, *, auto_id: bool, enable_dynamic_field: bool
    ) -> FakeMilvusSchema:
        schema = FakeMilvusSchema(
            auto_id=auto_id,
            enable_dynamic_field=enable_dynamic_field,
        )
        cls.created_schemas.append(schema)
        return schema

    @classmethod
    def prepare_index_params(cls):
        return FakeIndexParams()

    def has_collection(self, collection_name: str) -> bool:
        return bool(self.created_collections) or self.existing_schema is not None

    def create_collection(self, **kwargs) -> None:
        self.created_collections.append(kwargs)

    def describe_collection(self, collection_name: str) -> dict:
        if self.existing_schema is None:
            return {}
        return self.existing_schema

    def create_index(self, **kwargs) -> None:
        return None

    def load_collection(self, **kwargs) -> None:
        return None

    def flush(self, **kwargs) -> None:
        return None

    def upsert(self, collection_name: str, data: list[dict]) -> dict:
        for row in data:
            self.rows[row["event_id"]] = dict(row)
        return {"upsert_count": len(data)}

    def query(
        self,
        collection_name: str,
        filter: str,
        output_fields: list[str],
        limit: int | None = None,
    ) -> list[dict]:
        self.query_calls.append(
            {
                "collection_name": collection_name,
                "filter": filter,
                "output_fields": output_fields,
                "limit": limit,
            }
        )
        if self.reject_empty_query_without_limit and filter == "" and limit is None:
            raise RuntimeError("empty expression should be used with limit")

        rows = [
            {field: row.get(field) for field in output_fields}
            for row in self._filter_rows(filter)
        ]
        return rows[:limit] if limit is not None else rows

    def _filter_rows(self, filter: str) -> list[dict]:
        event_ids = None
        if filter.startswith("event_id in ["):
            event_ids = [
                item.strip().strip('"').strip("'")
                for item in filter.split("[", 1)[1].split("]", 1)[0].split(",")
                if item.strip()
            ]

        is_built = None
        if "is_graph_built == false" in filter:
            is_built = False
        elif "is_graph_built == true" in filter:
            is_built = True

        expire_gt = None
        expire_lte = None
        if "expire_at > " in filter:
            expire_gt = self._extract_quoted_value(filter, "expire_at > ")
        if "expire_at <= " in filter:
            expire_lte = self._extract_quoted_value(filter, "expire_at <= ")
        created_lte = None
        if "created_at <= " in filter:
            created_lte = self._extract_quoted_value(filter, "created_at <= ")
        excluded_event_id = None
        if "event_id != " in filter:
            excluded_event_id = self._extract_quoted_value(filter, "event_id != ")

        return [
            row
            for row in self.rows.values()
            if (
                (event_ids is None or row["event_id"] in event_ids)
                and (excluded_event_id is None or row["event_id"] != excluded_event_id)
                and (is_built is None or row.get("is_graph_built") is is_built)
                and (expire_gt is None or row.get("expire_at", "") > expire_gt)
                and (expire_lte is None or row.get("expire_at", "") <= expire_lte)
                and (created_lte is None or row.get("created_at", "") <= created_lte)
            )
        ]

    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        anns_field: str,
        filter: str,
        limit: int,
        output_fields: list[str],
    ) -> list[list[dict]]:
        query_vector = data[0]

        def score(row: dict) -> float:
            return sum(a * b for a, b in zip(query_vector, row["embedding"]))

        filtered_rows = self._filter_rows(filter)
        ranked = sorted(filtered_rows, key=score, reverse=True)
        hits = []
        for row in ranked[:limit]:
            hits.append(
                {
                    "id": row["event_id"],
                    "distance": score(row),
                    "entity": {field: row.get(field) for field in output_fields},
                }
            )
        return [hits]

    def delete(self, collection_name: str, filter: str) -> dict:
        event_ids = [
            item.strip().strip('"').strip("'")
            for item in filter.split("[", 1)[1].split("]", 1)[0].split(",")
            if item.strip()
        ]
        deleted = 0
        for event_id in event_ids:
            if event_id in self.rows:
                del self.rows[event_id]
                deleted += 1
        return {"delete_count": deleted}

    @staticmethod
    def _extract_quoted_value(filter_expr: str, prefix: str) -> str:
        remainder = filter_expr.split(prefix, 1)[1].strip()
        if remainder[0] in {'"', "'"}:
            quote = remainder[0]
            return remainder[1:].split(quote, 1)[0]
        return remainder.split(" ", 1)[0]


class FakeEventuallyConsistentMilvusClient(FakeMilvusClient):
    def __init__(self):
        super().__init__()
        self.pending_rows: dict[str, dict] = {}
        self.flush_calls: list[dict] = []

    def upsert(self, collection_name: str, data: list[dict]) -> dict:
        del collection_name
        for row in data:
            self.pending_rows[row["event_id"]] = dict(row)
        return {"upsert_count": len(data)}

    def flush(self, **kwargs) -> None:
        self.flush_calls.append(kwargs)
        self.rows.update(self.pending_rows)
        self.pending_rows.clear()


class FakeNoFlushMilvusClient(FakeMilvusClient):
    flush = None


def fake_embed(text: str) -> list[float]:
    if "alpha" in text:
        return [1.0, 0.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


def build_fake_reranker(
    scores: dict[str, float],
) -> Callable[[str, list[str]], list[float] | Awaitable[list[float]]]:
    async def _rerank(query: str, documents: list[str]) -> list[float]:
        del query
        return [scores.get(document, 0.0) for document in documents]

    return _rerank


def test_from_settings_keeps_injected_client_and_functions(now):
    from sentinel.config import SentinelSettings

    client = FakeMilvusClient()

    async def fake_rerank(query: str, documents: list[str]) -> list[float]:
        del query
        return [1.0 for _ in documents]

    settings = SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
        milvus_input_events_collection="custom_stash",
        kv_ttl_days=14,
        embedding_dim=3,
        stash_rerank_min_score=0.2,
    )

    store = MilvusStashStore.from_settings(
        settings,
        client=client,
        embedding_fn=fake_embed,
        rerank_fn=fake_rerank,
        now_fn=lambda: now,
    )

    assert store._client is client
    assert store._collection_name == "custom_stash"
    assert store._ttl_days == 14
    assert store._embedding_dim == 3
    assert store._semantic_score_threshold == 0.2


def test_from_settings_can_disable_stash_rerank(now):
    from sentinel.config import SentinelSettings

    client = FakeMilvusClient()
    settings = SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
        stash_rerank_enabled=False,
        stash_rerank_min_score=0.65,
        search_min_score=0.2,
        embedding_dim=3,
    )

    store = MilvusStashStore.from_settings(
        settings,
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
    )

    assert store._rerank_fn is None
    assert store._semantic_score_threshold == 0.65


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 26, 12, 0, 0)


@pytest.fixture
def client() -> FakeMilvusClient:
    return FakeMilvusClient()


@pytest.fixture
def store(client, now) -> MilvusStashStore:
    return MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )


@pytest.mark.asyncio
async def test_stash_event_initializes_collection_before_first_write(
    monkeypatch, client, now
):
    monkeypatch.setattr(
        "sentinel.blacklist.milvus_stash.MilvusClient",
        FakeMilvusClient,
    )
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
        embedding_dim=3,
    )

    await store.stash_event(make_event("E001", "alpha P01 low signal", now), ["P01"])

    assert client.created_collections
    collection = client.created_collections[0]
    assert collection["collection_name"] == "input_events"
    assert "dimension" not in collection
    assert "schema" in collection


@pytest.mark.asyncio
async def test_stash_event_creates_static_schema_with_all_event_fields(
    monkeypatch, client, now
):

    monkeypatch.setattr(
        "sentinel.blacklist.milvus_stash.MilvusClient",
        FakeMilvusClient,
    )
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
        embedding_dim=3,
    )

    await store.stash_event(make_event("E001", "alpha P01 low signal", now), ["P01"])

    schema = client.created_collections[0]["schema"]
    assert schema.auto_id is False
    assert schema.enable_dynamic_field is False
    assert [field["field_name"] for field in schema.fields] == [
        field.name for field in events_fields(embedding_dim=3)
    ]
    assert schema.fields[0]["is_primary"] is True
    assert schema.fields[-1]["dim"] == 3

    index_params = client.created_collections[0]["index_params"]
    assert index_params.indexes == [
        {
            "field_name": "embedding",
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        }
    ]


@pytest.mark.asyncio
async def test_existing_dynamic_schema_is_rejected_before_write(client, now):
    client.existing_schema = {
        "enable_dynamic_field": True,
        "fields": [
            {"name": "event_id"},
            {"name": "embedding"},
        ],
    }
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
        embedding_dim=3,
    )

    with pytest.raises(RuntimeError, match="uses dynamic fields"):
        await store.stash_event(
            make_event("E001", "alpha P01 low signal", now), ["P01"]
        )

    assert client.rows == {}


def make_event(
    event_id: str,
    raw_content: str,
    timestamp: datetime,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source=EventSource.NEWS,
        raw_content=raw_content,
        title=event_id,
        timestamp=timestamp,
    )


@pytest.mark.asyncio
async def test_stash_event_writes_searchable_document(store, client, now):
    event = make_event("E001", "alpha P01 low signal", now)

    result = await store.stash_event(event, ["p01"])

    assert result == 1
    row = client.rows["E001"]
    assert row["event_id"] == "E001"
    assert row["person_ids"] == ["P01"]
    assert row["raw_content"] == "alpha P01 low signal"
    assert row["created_at"] == now.isoformat()
    assert row["expire_at"] == (now + timedelta(days=30)).isoformat()
    assert row["embedding"] == [1.0, 0.0, 0.0]
    assert row["is_graph_built"] is False


@pytest.mark.asyncio
async def test_stash_event_allows_empty_person_ids(store, client, now):
    event = make_event("E001", "alpha no person", now)

    result = await store.stash_event(event, [])

    assert result == 1
    assert client.rows["E001"]["person_ids"] == []


@pytest.mark.asyncio
async def test_stash_event_flushes_before_immediate_inspection(now):
    client = FakeEventuallyConsistentMilvusClient()
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )

    await store.stash_event(make_event("E001", "alpha no person", now), [])

    inspector_store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )
    rows = inspector_store._query_rows(
        'event_id in ["E001"]',
        ["event_id", "person_ids", "is_graph_built"],
    )

    assert rows == [
        {
            "event_id": "E001",
            "person_ids": [],
            "is_graph_built": False,
        }
    ]
    assert client.flush_calls == [{"collection_name": "input_events"}]


@pytest.mark.asyncio
async def test_stash_event_supports_clients_without_flush(now):
    client = FakeNoFlushMilvusClient()
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )

    result = await store.stash_event(make_event("E001", "alpha no flush", now), ["P01"])

    assert result == 1
    assert client.rows["E001"]["person_ids"] == ["P01"]


@pytest.mark.asyncio
async def test_fetch_related_events_returns_union_with_match_sources(
    store, client, now
):
    await store.stash_event(make_event("E001", "alpha same person", now), ["P01"])
    await store.stash_event(make_event("E002", "alpha semantic only", now), ["P99"])
    await store.stash_event(make_event("E003", "beta same person", now), ["P01"])
    trigger = make_event("E999", "alpha trigger P01", now)

    results = await store.fetch_related_events(
        trigger,
        ["P01"],
        top_k_semantic=2,
        max_per_person=10,
    )

    assert [item["event_id"] for item in results] == ["E001", "E003", "E002"]
    assert [item["match_source"] for item in results] == [
        "both",
        "person_match",
        "semantic_match",
    ]


@pytest.mark.asyncio
async def test_fetch_related_events_filters_semantic_matches_by_rerank_threshold(
    client, now
):
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        rerank_fn=build_fake_reranker(
            {
                "alpha strong semantic": 0.9,
                "alpha weak semantic": 0.2,
            }
        ),
        semantic_score_threshold=0.5,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(make_event("E001", "alpha strong semantic", now), ["P99"])
    await store.stash_event(make_event("E002", "alpha weak semantic", now), ["P98"])

    results = await store.fetch_related_events(
        make_event("E999", "alpha trigger", now),
        [],
        top_k_semantic=2,
        max_per_person=10,
    )

    assert [item["event_id"] for item in results] == ["E001"]
    assert results[0]["match_source"] == "semantic_match"
    assert results[0]["semantic_score"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_fetch_related_events_keeps_multiple_taxonomy_match_sources(client, now):
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        rerank_fn=build_fake_reranker(
            {
                "alpha both": 0.95,
                "alpha semantic": 0.8,
                "beta person only": 0.1,
            }
        ),
        semantic_score_threshold=0.5,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(make_event("E001", "alpha both", now), ["P01"])
    await store.stash_event(make_event("E002", "alpha semantic", now), ["P99"])
    await store.stash_event(make_event("E003", "beta person only", now), ["P01"])

    results = await store.fetch_related_events(
        make_event("E999", "alpha trigger P01", now),
        ["P01"],
        top_k_semantic=3,
        max_per_person=10,
    )

    assert [(item["event_id"], item["match_source"]) for item in results] == [
        ("E001", "both"),
        ("E003", "person_match"),
        ("E002", "semantic_match"),
    ]


@pytest.mark.asyncio
async def test_fetch_related_events_keeps_person_matches_when_rerank_below_threshold(
    client, now
):
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        rerank_fn=build_fake_reranker({"alpha same person": 0.1}),
        semantic_score_threshold=0.5,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(make_event("E001", "alpha same person", now), ["P01"])

    results = await store.fetch_related_events(
        make_event("E999", "alpha trigger P01", now),
        ["P01"],
        top_k_semantic=1,
        max_per_person=10,
    )

    assert [item["event_id"] for item in results] == ["E001"]
    assert results[0]["match_source"] == "person_match"
    assert "semantic_score" not in results[0]


@pytest.mark.asyncio
async def test_semantic_search_filters_eligible_rows_before_top_k(client, now):
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        rerank_fn=build_fake_reranker({"beta eligible": 0.9}),
        semantic_score_threshold=0.5,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(make_event("BUILT", "alpha already built", now), ["P99"])
    await store.mark_events_graph_built(["BUILT"])
    await store.stash_event(make_event("VALID", "beta eligible", now), ["P98"])

    results = await store.fetch_related_events(
        make_event("CURRENT", "alpha trigger", now),
        [],
        top_k_semantic=1,
        max_per_person=10,
    )

    assert [item["event_id"] for item in results] == ["VALID"]


@pytest.mark.asyncio
async def test_fetch_related_events_filters_current_expired_and_built_events(
    store, client, now
):
    await store.stash_event(make_event("CURRENT", "alpha current", now), ["P01"])
    await store.stash_event(
        make_event("EXPIRED", "alpha expired", now - timedelta(days=40)), ["P01"]
    )
    await store.stash_event(make_event("BUILT", "alpha built", now), ["P01"])
    await store.mark_events_graph_built(["BUILT"])
    await store.stash_event(make_event("VALID", "alpha valid", now), ["P01"])

    results = await store.fetch_related_events(
        make_event("CURRENT", "alpha trigger", now),
        ["P01"],
        top_k_semantic=10,
        max_per_person=10,
    )

    assert [item["event_id"] for item in results] == ["VALID"]


@pytest.mark.asyncio
async def test_mark_events_graph_built_prevents_future_recall(store, now):
    await store.stash_event(make_event("E001", "alpha same person", now), ["P01"])

    await store.mark_events_graph_built(["E001"])
    results = await store.fetch_related_events(
        make_event("E999", "alpha trigger", now),
        ["P01"],
        top_k_semantic=10,
        max_per_person=10,
    )

    assert results == []


@pytest.mark.asyncio
async def test_stash_event_preserves_existing_graph_built_state(store, client, now):
    event = make_event("E001", "alpha same person", now)
    await store.stash_event(event, ["P01"])
    await store.mark_events_graph_built(["E001"])

    await store.stash_event(event, ["P01"])

    assert client.rows["E001"]["is_graph_built"] is True


@pytest.mark.asyncio
async def test_mark_events_graph_built_queries_by_event_id_without_full_scan(now):
    client = FakeMilvusClient(reject_empty_query_without_limit=True)
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(make_event("E001", "alpha same person", now), ["P01"])
    await store.stash_event(make_event("E002", "beta other person", now), ["P02"])

    marked_count = await store.mark_events_graph_built(["E001"])

    assert marked_count == 1
    assert client.rows["E001"]["is_graph_built"] is True
    assert client.rows["E002"]["is_graph_built"] is False
    assert client.query_calls[-1]["filter"] == 'event_id in ["E001"]'
    assert client.query_calls[-1]["limit"] is None


@pytest.mark.asyncio
async def test_cleanup_expired_uses_filtered_queries_without_full_scan(now):
    client = FakeMilvusClient(reject_empty_query_without_limit=True)
    store = MilvusStashStore(
        client=client,
        embedding_fn=fake_embed,
        now_fn=lambda: now,
        ttl_days=30,
    )
    await store.stash_event(
        make_event("EXPIRED", "alpha expired", now - timedelta(days=40)), ["P01"]
    )
    await store.stash_event(
        make_event("BUILT", "alpha built", now - timedelta(days=10)), ["P01"]
    )
    await store.mark_events_graph_built(["BUILT"])
    await store.stash_event(make_event("VALID", "alpha valid", now), ["P01"])

    deleted = await store.cleanup_expired(graph_built_retention_days=7)

    assert deleted == 2
    assert "EXPIRED" not in client.rows
    assert "BUILT" not in client.rows
    assert "VALID" in client.rows
    assert client.query_calls[-2]["filter"] == 'expire_at <= "2026-05-26T12:00:00"'
    assert client.query_calls[-1]["filter"] == (
        'is_graph_built == true and created_at <= "2026-05-19T12:00:00"'
    )
