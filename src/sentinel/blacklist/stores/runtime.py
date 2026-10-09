"""黑名单 store 组合（bundle）的构建与进程级缓存入口。"""

import asyncio
import json
from typing import Any

from sentinel.blacklist.stores.factory import StoreBundle, create_store_bundle
from sentinel.utils.async_resources import close_resource

_STORE_BUNDLE: StoreBundle | None = None
_STORE_SIGNATURE: str | None = None
_LOCK = asyncio.Lock()


async def get_runtime_store_bundle(config: dict[str, Any]) -> StoreBundle:
    global _STORE_BUNDLE, _STORE_SIGNATURE

    signature = _store_config_signature(config)
    if _STORE_BUNDLE is not None and _STORE_SIGNATURE == signature:
        return _STORE_BUNDLE

    async with _LOCK:
        if _STORE_BUNDLE is not None and _STORE_SIGNATURE == signature:
            return _STORE_BUNDLE
        if _STORE_BUNDLE is not None:
            await close_resource(_STORE_BUNDLE)
        _STORE_BUNDLE = create_store_bundle(config)
        _STORE_SIGNATURE = signature
        return _STORE_BUNDLE


async def reset_runtime_store_bundle_cache_async() -> None:
    global _STORE_BUNDLE, _STORE_SIGNATURE

    bundle = _STORE_BUNDLE
    _STORE_BUNDLE = None
    _STORE_SIGNATURE = None
    await close_resource(bundle)


def reset_runtime_store_bundle_cache() -> None:
    global _STORE_BUNDLE, _STORE_SIGNATURE

    bundle = _STORE_BUNDLE
    if bundle is None:
        _STORE_SIGNATURE = None
        return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _STORE_BUNDLE = None
        _STORE_SIGNATURE = None
        asyncio.run(close_resource(bundle))
        return

    raise RuntimeError(
        "reset_runtime_store_bundle_cache() cannot close async resources inside "
        "a running event loop; use reset_runtime_store_bundle_cache_async() instead."
    )


def _store_config_signature(config: dict[str, Any]) -> str:
    return json.dumps(
        {
            "milvus": config.get("milvus", {}),
            "embedder": config.get("embedder", {}),
        },
        sort_keys=True,
    )
