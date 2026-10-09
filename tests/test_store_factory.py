import asyncio

import pytest

from sentinel.blacklist.stores import factory


class FakeMilvusClient:
    def close(self) -> None:
        return None


class FakeEmbedder:
    async def create(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0]

    async def create_batch(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0, 0.0] for text in texts]


def test_create_store_bundle_uses_canonical_event_store_config_keys(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        factory, "create_milvus_client", lambda config: FakeMilvusClient()
    )
    monkeypatch.setattr(factory, "create_embedder", lambda config: FakeEmbedder())

    bundle = factory.create_store_bundle(
        {
            "milvus": {
                "uri": "http://localhost:19530",
                "input_events_collection": "demo_stash",
                "embedding_dim": 3,
                "kv_ttl_days": 14,
                "stash_rerank_min_score": 0.65,
            },
            "embedder": {
                "model": "embedder",
                "api_key": "key",
                "api_base": "https://embedder.local/v1",
            },
        }
    )

    assert bundle.events.collection_name == "demo_stash"
    assert bundle.events._ttl_days == 14


def test_create_store_bundle_reuses_single_embedder_instance(monkeypatch) -> None:
    created_embedders: list[FakeEmbedder] = []

    def fake_create_embedder(config):
        embedder = FakeEmbedder()
        created_embedders.append(embedder)
        return embedder

    monkeypatch.setattr(
        factory, "create_milvus_client", lambda config: FakeMilvusClient()
    )
    monkeypatch.setattr(factory, "create_embedder", fake_create_embedder)

    bundle = factory.create_store_bundle(
        {
            "milvus": {"embedding_dim": 3},
            "embedder": {
                "model": "embedder",
                "api_key": "key",
                "api_base": "https://embedder.local/v1",
            },
        }
    )

    assert len(created_embedders) == 1
    assert bundle.embedder is created_embedders[0]


def test_create_embedding_fn_enforces_asyncio_timeout(monkeypatch) -> None:
    class SlowEmbedder:
        async def create(self, text: str) -> list[float]:
            await asyncio.sleep(0.05)
            return [1.0, 0.0, 0.0]

    monkeypatch.setattr(factory, "create_embedder", lambda config: SlowEmbedder())

    embedding_fn = factory.create_embedding_fn(
        {
            "model": "embedder",
            "api_key": "key",
            "api_base": "https://embedder.local/v1",
            "timeout_seconds": 0.01,
        }
    )

    with pytest.raises(TimeoutError):
        asyncio.run(embedding_fn("slow text"))


@pytest.mark.asyncio
async def test_create_embedding_fn_uses_batch_when_available(monkeypatch) -> None:
    calls: list[list[str]] = []

    class BatchEmbedder:
        async def create(self, text: str) -> list[float]:
            raise AssertionError("single create should not be used for batch input")

        async def create_batch(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(len(text)), 0.0, 0.0] for text in texts]

    monkeypatch.setattr(factory, "create_embedder", lambda config: BatchEmbedder())

    embedding_fn = factory.create_embedding_fn(
        {
            "model": "embedder",
            "api_key": "key",
            "api_base": "https://embedder.local/v1",
            "timeout_seconds": 1,
        }
    )

    result = await embedding_fn(["alpha", "beta"])

    assert calls == [["alpha", "beta"]]
    assert result == [[5.0, 0.0, 0.0], [4.0, 0.0, 0.0]]


@pytest.mark.asyncio
async def test_store_bundle_aclose_closes_embedder_client(monkeypatch) -> None:
    class FakeEmbedderClient:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class FakeEmbedder:
        def __init__(self) -> None:
            self.client = FakeEmbedderClient()

        async def create(self, text: str) -> list[float]:
            return [float(len(text)), 0.0, 0.0]

    fake_client = FakeMilvusClient()
    fake_embedder = FakeEmbedder()

    monkeypatch.setattr(factory, "create_milvus_client", lambda config: fake_client)
    monkeypatch.setattr(factory, "create_embedder", lambda config: fake_embedder)

    bundle = factory.create_store_bundle({"milvus": {"embedding_dim": 3}})

    await bundle.aclose()

    assert fake_embedder.client.closed is True
