"""未命中输入事件的 Milvus 暂存与回捞。"""

import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from pymilvus import MilvusClient

from sentinel.blacklist.stores.base import FieldSpec
from sentinel.blacklist.stores.events_schema import events_fields
from sentinel.config import SentinelSettings, get_settings
from sentinel.models import NormalizedEvent
from sentinel.utils.litellm_embedding import embed_text
from sentinel.utils.litellm_rerank import rerank_scores

logger = logging.getLogger(__name__)

EmbeddingFn = Callable[[str], list[float] | Awaitable[list[float]]]
RerankFn = Callable[[str, list[str]], list[float] | Awaitable[list[float]]]
NowFn = Callable[[], datetime]


def _default_embedding(text: str) -> list[float]:
    """Generate deterministic local vectors when no embedder is injected."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [int.from_bytes(digest[i : i + 4], "big") for i in range(0, 32, 4)]
    scale = max(values) or 1
    return [value / scale for value in values]


class MilvusStashStore:
    """Milvus-backed input event store with related-event recall helpers."""

    DEFAULT_COLLECTION = "input_events"
    OUTPUT_FIELDS = [
        "event_id",
        "person_ids",
        "raw_content",
        "created_at",
        "expire_at",
        "is_graph_built",
    ]

    def __init__(
        self,
        client: Any | None = None,
        collection_name: str | None = None,
        embedding_fn: EmbeddingFn | None = None,
        rerank_fn: RerankFn | None = None,
        semantic_score_threshold: float | None = None,
        now_fn: NowFn | None = None,
        ttl_days: int | None = None,
        embedding_dim: int | None = None,
    ) -> None:
        self._client = client or self._create_default_client()
        self._collection_name = collection_name or self.DEFAULT_COLLECTION
        self._embedding_fn = embedding_fn or _default_embedding
        self._rerank_fn = rerank_fn
        self._now_fn = now_fn or datetime.now
        self._ttl_days = ttl_days or 90
        self._embedding_dim = embedding_dim or 1024
        self._semantic_score_threshold = (
            semantic_score_threshold if semantic_score_threshold is not None else 0.0
        )
        self._collection_ready = False

    @classmethod
    def from_settings(
        cls,
        settings: SentinelSettings,
        *,
        client: Any | None = None,
        embedding_fn: EmbeddingFn | None = None,
        rerank_fn: RerankFn | None = None,
        now_fn: NowFn | None = None,
    ) -> "MilvusStashStore":
        resolved_client = client or cls._create_client_from_settings(settings)
        resolved_embedding_fn = embedding_fn or cls._create_embedding_fn(settings)
        resolved_rerank_fn = rerank_fn
        if resolved_rerank_fn is None and settings.stash_rerank_enabled:
            resolved_rerank_fn = cls._create_rerank_fn(settings)
        return cls(
            client=resolved_client,
            collection_name=settings.milvus_input_events_collection,
            embedding_fn=resolved_embedding_fn,
            rerank_fn=resolved_rerank_fn,
            semantic_score_threshold=settings.stash_rerank_min_score,
            now_fn=now_fn,
            ttl_days=settings.kv_ttl_days,
            embedding_dim=settings.embedding_dim,
        )

    @staticmethod
    def _create_embedding_fn(settings: SentinelSettings) -> EmbeddingFn:
        async def _embed(text: str) -> list[float]:
            return await embed_text(settings, text)

        return _embed

    @staticmethod
    def _create_default_client() -> Any:
        return MilvusStashStore._create_client_from_settings(get_settings())

    @staticmethod
    def _create_rerank_fn(settings: SentinelSettings) -> RerankFn:
        async def _rerank(query: str, documents: list[str]) -> list[float]:
            return await rerank_scores(
                query=query,
                documents=documents,
                model=settings.effective_reranker_model,
                api_key=settings.effective_reranker_api_key_value(),
                base_url=settings.effective_reranker_base_url,
            )

        return _rerank

    @staticmethod
    def _create_client_from_settings(settings: SentinelSettings) -> Any:
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError(
                "pymilvus is required for MilvusStashStore without an injected client"
            ) from exc

        kwargs = {"uri": settings.milvus_uri}
        token = settings.optional_milvus_token()
        if token:
            kwargs["token"] = token
        return MilvusClient(**kwargs)

    async def stash_event(
        self,
        event: NormalizedEvent,
        id_numbers: list[str],
    ) -> int:
        created_at = event.timestamp
        expire_at = created_at + timedelta(days=self._ttl_days)
        is_graph_built = self._existing_graph_built_state(event.event_id)
        row = {
            "event_id": event.event_id,
            "person_ids": sorted({pid.upper() for pid in id_numbers}),
            "raw_content": event.raw_content,
            "created_at": created_at.isoformat(),
            "expire_at": expire_at.isoformat(),
            "embedding": await self._embed_text(event.raw_content),
            "is_graph_built": is_graph_built,
        }
        self._ensure_collection()
        self._client.upsert(collection_name=self._collection_name, data=[row])
        self._flush_collection()
        logger.info("stored event_id=%s to Milvus event collection", event.event_id)
        return 1

    def ensure_collection_ready(self) -> None:
        self._ensure_collection()

    def query_event_rows(
        self,
        event_id: str,
        output_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._query_rows(
            self._event_id_filter([event_id]),
            output_fields,
            limit=limit,
        )

    def _existing_graph_built_state(self, event_id: str) -> bool:
        rows = self.query_event_rows(
            event_id,
            ["event_id", "is_graph_built"],
            limit=1,
        )
        return bool(rows and rows[0].get("is_graph_built") is True)

    def count_rows_for_diagnostics(self, *, limit: int = 10000) -> int | None:
        try:
            rows = self._query_rows('event_id != ""', ["event_id"], limit=limit)
        except Exception:
            return None
        return len(rows) if rows else 0

    async def fetch_related_events(
        self,
        event: NormalizedEvent,
        id_numbers: list[str],
        top_k_semantic: int = 10,
        max_per_person: int = 20,
    ) -> list[dict]:
        now = self._now_fn()
        eligible_rows = self._eligible_rows(event.event_id, now)
        person_ids = {pid.upper() for pid in id_numbers}

        person_matches = self._person_matches(eligible_rows, person_ids, max_per_person)
        semantic_matches = await self._semantic_matches(
            event,
            top_k_semantic,
            eligible_event_ids={row["event_id"] for row in eligible_rows},
        )

        merged: dict[str, dict] = {}
        for row in person_matches:
            merged[row["event_id"]] = {**row, "match_source": "person_match"}
        for row in semantic_matches:
            existing = merged.get(row["event_id"])
            if existing:
                existing["match_source"] = "both"
                existing["semantic_score"] = row.get("semantic_score")
            else:
                merged[row["event_id"]] = {**row, "match_source": "semantic_match"}

        return sorted(
            merged.values(),
            key=lambda item: (
                self._source_rank(item["match_source"]),
                item.get("created_at", ""),
                item.get("semantic_score", 0.0),
            ),
            reverse=True,
        )

    async def mark_events_graph_built(self, event_ids: list[str]) -> int:
        unique_ids = sorted({event_id for event_id in event_ids if event_id})
        if not unique_ids:
            return 0

        rows_by_id = {
            row["event_id"]: row
            for row in self._query_rows(
                self._event_id_filter(unique_ids),
                [*self.OUTPUT_FIELDS, "embedding"],
            )
            if row.get("event_id") in unique_ids
        }
        rows = []
        for event_id in unique_ids:
            row = rows_by_id.get(event_id)
            if not row:
                continue
            rows.append({**row, "is_graph_built": True})

        if rows:
            self._client.upsert(collection_name=self._collection_name, data=rows)
            self._flush_collection()
        logger.info("marked %d Milvus event rows as graph built", len(rows))
        return len(rows)

    async def cleanup_expired(
        self, graph_built_retention_days: int | None = None
    ) -> int:
        now = self._now_fn()
        delete_ids = []
        expired_rows = self._query_rows(
            f"expire_at <= {self._quote_literal(now.isoformat())}",
            ["event_id"],
        )
        delete_ids.extend(
            row["event_id"] for row in expired_rows if row.get("event_id")
        )
        if graph_built_retention_days is not None:
            retention_cutoff = now - timedelta(days=graph_built_retention_days)
            built_rows = self._query_rows(
                " and ".join(
                    [
                        "is_graph_built == true",
                        f"created_at <= {self._quote_literal(retention_cutoff.isoformat())}",
                    ]
                ),
                ["event_id"],
            )
            delete_ids.extend(
                row["event_id"] for row in built_rows if row.get("event_id")
            )

        if not delete_ids:
            return 0
        result = self._client.delete(
            collection_name=self._collection_name,
            filter=self._event_id_filter(delete_ids),
        )
        return int(result.get("delete_count", len(delete_ids)))

    def _eligible_rows(self, current_event_id: str, now: datetime) -> list[dict]:
        return self._query_rows(
            " and ".join(
                [
                    "is_graph_built == false",
                    f"expire_at > {self._quote_literal(now.isoformat())}",
                    f"event_id != {self._quote_literal(current_event_id)}",
                ]
            ),
            self.OUTPUT_FIELDS,
        )

    def _person_matches(
        self,
        rows: list[dict],
        person_ids: set[str],
        max_per_person: int,
    ) -> list[dict]:
        if not person_ids:
            return []

        matched = []
        seen = set()
        for row in sorted(
            rows, key=lambda item: item.get("created_at", ""), reverse=True
        ):
            row_person_ids = {pid.upper() for pid in row.get("person_ids", [])}
            if not person_ids.intersection(row_person_ids):
                continue
            if row["event_id"] in seen:
                continue
            matched.append(row)
            seen.add(row["event_id"])
            if len(matched) >= max_per_person * len(person_ids):
                break
        return matched

    async def _semantic_matches(
        self,
        event: NormalizedEvent,
        top_k: int,
        eligible_event_ids: set[str],
    ) -> list[dict]:
        if top_k <= 0 or not eligible_event_ids:
            return []

        self._ensure_collection()
        result = self._client.search(
            collection_name=self._collection_name,
            data=[await self._embed_text(event.raw_content)],
            anns_field="embedding",
            filter=self._event_id_filter(sorted(eligible_event_ids)),
            limit=top_k,
            output_fields=self.OUTPUT_FIELDS,
        )
        rows = []
        for hit in result[0] if result else []:
            entity = dict(hit.get("entity", {}))
            event_id = entity.get("event_id") or hit.get("id")
            if event_id not in eligible_event_ids:
                continue
            entity["event_id"] = event_id
            entity["semantic_score"] = hit.get("distance", 0.0)
            rows.append(entity)
        return await self._rerank_semantic_matches(event.raw_content, rows)

    async def _rerank_semantic_matches(
        self,
        query: str,
        rows: list[dict],
    ) -> list[dict]:
        if not rows:
            return []
        if self._rerank_fn is None:
            logger.warning(
                "semantic reranker not configured, keeping Milvus semantic matches without rerank filtering"
            )
            return rows

        documents = [str(row.get("raw_content", "")) for row in rows]
        scores = self._rerank_fn(query, documents)
        if inspect.isawaitable(scores):
            scores = await scores

        reranked_rows: list[dict] = []
        for row, score in zip(rows, scores, strict=False):
            normalized_score = float(score)
            if normalized_score < self._semantic_score_threshold:
                continue
            reranked_rows.append({**row, "semantic_score": normalized_score})

        reranked_rows.sort(
            key=lambda item: (
                item.get("semantic_score", 0.0),
                item.get("created_at", ""),
            ),
            reverse=True,
        )
        return reranked_rows

    def _query_rows(
        self,
        filter_expr: str,
        output_fields: list[str],
        limit: int | None = None,
    ) -> list[dict]:
        if not filter_expr or not filter_expr.strip():
            raise ValueError("query filter must be non-empty")
        self._ensure_collection()
        return self._client.query(
            collection_name=self._collection_name,
            filter=filter_expr,
            output_fields=output_fields,
            limit=limit,
        )

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        has_collection = getattr(self._client, "has_collection", None)
        if has_collection is None:
            self._collection_ready = True
            return
        if has_collection(self._collection_name):
            self._validate_existing_collection()
            self._collection_ready = True
            return

        self._client.create_collection(
            collection_name=self._collection_name,
            schema=self._create_static_schema(),
            index_params=self._create_vector_index_params(),
        )
        load_collection = getattr(self._client, "load_collection", None)
        if load_collection is not None:
            load_collection(collection_name=self._collection_name)
        self._collection_ready = True

    @staticmethod
    def _add_schema_field(schema: Any, field: FieldSpec) -> None:
        kwargs: dict[str, Any] = {
            "field_name": field.name,
            "datatype": field.dtype,
            "is_primary": field.is_primary,
        }
        if field.max_length is not None:
            kwargs["max_length"] = field.max_length
        if field.max_capacity is not None:
            kwargs["max_capacity"] = field.max_capacity
        if field.element_type is not None:
            kwargs["element_type"] = field.element_type
        if field.dim is not None:
            kwargs["dim"] = field.dim
        if field.default_value is not None:
            kwargs["default_value"] = field.default_value

        schema.add_field(**kwargs)

    def _create_static_schema(self) -> Any:
        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        for field in events_fields(self._embedding_dim):
            self._add_schema_field(schema, field)
        return schema

    @staticmethod
    def _create_vector_index_params() -> Any:
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        return index_params

    def _validate_existing_collection(self) -> None:
        describe_collection = getattr(self._client, "describe_collection", None)
        if describe_collection is None:
            return

        description = describe_collection(collection_name=self._collection_name)
        if not description:
            return

        if self._dynamic_fields_enabled(description):
            raise RuntimeError(
                f"Milvus collection {self._collection_name!r} uses dynamic fields; "
                "reset or migrate the collection before writing event records."
            )

        expected_fields = {field.name for field in events_fields(self._embedding_dim)}
        actual_fields = {
            str(field.get("name"))
            for field in description.get("fields", [])
            if field.get("name")
        }
        missing_fields = sorted(expected_fields - actual_fields)
        if missing_fields:
            raise RuntimeError(
                f"Milvus collection {self._collection_name!r} is missing static "
                f"event fields: {', '.join(missing_fields)}"
            )

        embedding_dim = self._field_dim(description, "embedding")
        if embedding_dim is not None and embedding_dim != self._embedding_dim:
            raise RuntimeError(
                f"Milvus collection {self._collection_name!r} embedding dim is "
                f"{embedding_dim}, expected {self._embedding_dim}."
            )

    @staticmethod
    def _dynamic_fields_enabled(description: dict[str, Any]) -> bool:
        value = description.get("enable_dynamic_field")
        if value is None:
            value = description.get("schema", {}).get("enable_dynamic_field")
        return bool(value)

    @staticmethod
    def _field_dim(description: dict[str, Any], field_name: str) -> int | None:
        for field in description.get("fields", []):
            if field.get("name") != field_name:
                continue
            params = field.get("params") or {}
            dim = params.get("dim") or field.get("dim")
            return int(dim) if dim is not None else None
        return None

    def _flush_collection(self) -> None:
        flush = getattr(self._client, "flush", None)
        if flush is not None:
            flush(collection_name=self._collection_name)

    async def _embed_text(self, text: str) -> list[float]:
        embedding = self._embedding_fn(text)
        if inspect.isawaitable(embedding):
            embedding = await embedding
        return list(embedding)

    @staticmethod
    def _source_rank(source: str) -> int:
        return {"both": 3, "person_match": 2, "semantic_match": 1}.get(source, 0)

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError(f"invalid datetime value: {value!r}")

    @staticmethod
    def _event_id_filter(event_ids: list[str]) -> str:
        quoted = ", ".join(f'"{event_id}"' for event_id in event_ids)
        return f"event_id in [{quoted}]"

    @staticmethod
    def _quote_literal(value: str) -> str:
        return json.dumps(value)
