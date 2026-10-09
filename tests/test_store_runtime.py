import asyncio

import pytest

from sentinel.blacklist.stores import runtime


class FakeBundle:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self.async_closed = False

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.async_closed = True
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_store_bundle_closes_replaced_and_reset_bundles(
    monkeypatch,
) -> None:
    bundles: list[FakeBundle] = []

    def fake_create_store_bundle(config: dict) -> FakeBundle:
        bundle = FakeBundle(str(config["milvus"]["uri"]))
        bundles.append(bundle)
        return bundle

    await runtime.reset_runtime_store_bundle_cache_async()
    monkeypatch.setattr(runtime, "create_store_bundle", fake_create_store_bundle)

    first = await runtime.get_runtime_store_bundle({"milvus": {"uri": "one"}})
    second = await runtime.get_runtime_store_bundle({"milvus": {"uri": "two"}})

    assert first is bundles[0]
    assert second is bundles[1]
    assert first.closed is True
    assert first.async_closed is True
    assert second.closed is False

    await runtime.reset_runtime_store_bundle_cache_async()

    assert second.closed is True
    assert second.async_closed is True


def test_sync_reset_runtime_store_bundle_cache_closes_async_bundle(
    monkeypatch,
) -> None:
    bundles: list[FakeBundle] = []

    def fake_create_store_bundle(config: dict) -> FakeBundle:
        bundle = FakeBundle(str(config["milvus"]["uri"]))
        bundles.append(bundle)
        return bundle

    asyncio.run(runtime.reset_runtime_store_bundle_cache_async())
    monkeypatch.setattr(runtime, "create_store_bundle", fake_create_store_bundle)
    bundle = asyncio.run(runtime.get_runtime_store_bundle({"milvus": {"uri": "one"}}))

    runtime.reset_runtime_store_bundle_cache()

    assert bundle is bundles[0]
    assert bundle.closed is True
    assert bundle.async_closed is True


@pytest.mark.asyncio
async def test_sync_reset_rejects_async_bundle_inside_running_loop(
    monkeypatch,
) -> None:
    bundles: list[FakeBundle] = []

    def fake_create_store_bundle(config: dict) -> FakeBundle:
        bundle = FakeBundle(str(config["milvus"]["uri"]))
        bundles.append(bundle)
        return bundle

    await runtime.reset_runtime_store_bundle_cache_async()
    monkeypatch.setattr(runtime, "create_store_bundle", fake_create_store_bundle)
    bundle = await runtime.get_runtime_store_bundle({"milvus": {"uri": "one"}})

    with pytest.raises(RuntimeError, match="reset_runtime_store_bundle_cache_async"):
        runtime.reset_runtime_store_bundle_cache()

    cached = await runtime.get_runtime_store_bundle({"milvus": {"uri": "one"}})
    assert cached is bundle
    assert bundle.closed is False
    assert bundle.async_closed is False

    await runtime.reset_runtime_store_bundle_cache_async()
