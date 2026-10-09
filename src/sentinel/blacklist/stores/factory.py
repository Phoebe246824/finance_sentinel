"""按配置构建黑名单 Milvus store 的工厂。"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from sentinel.blacklist.milvus_client import (
    create_milvus_client,
    milvus_config_from_app,
)
from sentinel.blacklist.stores.base import EmbeddingFn
from sentinel.blacklist.stores.event_samples_store import EventSamplesStore
from sentinel.blacklist.stores.events_schema import EVENTS_COLLECTION
from sentinel.blacklist.stores.events_store import EventsStore
from sentinel.blacklist.stores.keywords_store import KeywordsStore
from sentinel.blacklist.stores.persons_store import PersonsStore
from sentinel.blacklist.stores.review_actions_store import ReviewActionsStore
from sentinel.utils.async_resources import close_inner_http_client


@dataclass(slots=True)
class StoreBundle:
    events: EventsStore
    persons: PersonsStore
    keywords: KeywordsStore
    event_samples: EventSamplesStore
    review_actions: ReviewActionsStore

    embedder: Any | None = None
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self.events.close_client()
        self._closed = True

    async def aclose(self) -> None:
        if self._closed:
            return
        try:
            await close_inner_http_client(self.embedder)
        finally:
            self.close()


def events_collection_from_config(config: dict[str, Any] | None = None) -> str:
    milvus_config = config.get("milvus", {}) if isinstance(config, dict) else {}
    return str(
        milvus_config.get("input_events_collection")
        or os.getenv("MILVUS_INPUT_EVENTS_COLLECTION")
        or EVENTS_COLLECTION
    )


def milvus_collection_names(config: dict[str, Any] | None = None) -> tuple[str, ...]:
    configured_events = events_collection_from_config(config)
    names = {
        EVENTS_COLLECTION,
        configured_events,
        ReviewActionsStore.collection_name,
        PersonsStore.collection_name,
        KeywordsStore.collection_name,
        EventSamplesStore.collection_name,
    }
    return tuple(sorted(names))


def create_embedder(config: dict[str, Any]) -> Any:
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

    return OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model=str(config.get("model") or "BAAI/bge-m3"),
            api_key=str(config.get("api_key") or ""),
            base_url=str(config.get("api_base") or "https://api.openai.com/v1"),
        )
    )


def create_embedding_fn(
    config: dict[str, Any],
    *,
    embedder: Any | None = None,
) -> EmbeddingFn:
    embedder = embedder or create_embedder(config)
    timeout_seconds = float(config.get("timeout_seconds") or 30)

    async def _embed(
        input_data: str | list[str],
    ) -> list[float] | list[list[float]]:
        if isinstance(input_data, list) and hasattr(embedder, "create_batch"):
            request = embedder.create_batch(input_data)
        else:
            request = embedder.create(input_data)
        return await asyncio.wait_for(request, timeout=timeout_seconds)

    return _embed


def create_store_bundle(config: dict[str, Any]) -> StoreBundle:
    client = create_milvus_client(milvus_config_from_app(config))
    milvus_config = config.get("milvus", {})
    embedding_dim = int(milvus_config.get("embedding_dim") or 1024)
    ttl_days = int(
        milvus_config.get("kv_ttl_days") or milvus_config.get("stash_ttl_days") or 90
    )
    embedder_config = config.get("embedder", {})
    embedder = create_embedder(embedder_config)
    embedding_fn = create_embedding_fn(embedder_config, embedder=embedder)
    return StoreBundle(
        events=EventsStore(
            client=client,
            embedding_fn=embedding_fn,
            embedding_dim=embedding_dim,
            ttl_days=ttl_days,
            collection_name=events_collection_from_config(config),
        ),
        persons=PersonsStore(client=client, embedding_dim=embedding_dim),
        keywords=KeywordsStore(client=client, embedding_dim=embedding_dim),
        event_samples=EventSamplesStore(
            client=client,
            embedding_fn=embedding_fn,
            embedding_dim=embedding_dim,
        ),
        review_actions=ReviewActionsStore(client=client, embedding_dim=embedding_dim),
        embedder=embedder,
    )
