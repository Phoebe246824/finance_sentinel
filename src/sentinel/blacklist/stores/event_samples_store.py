"""输入事件样本在 Milvus 中的匹配与存取。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pymilvus import DataType
from pymilvus.exceptions import MilvusException

from sentinel.blacklist.stores.base import EmbeddingFn, FieldSpec, MilvusBaseStore
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EventSampleMatch:
    hit: bool
    score: float
    event_id: str
    summary: str
    threshold: float


@dataclass(frozen=True, slots=True)
class ManagementEmbedding:
    vector: list[float]
    status: str


class EventSamplesStore(MilvusBaseStore):
    collection_name = "blacklist_event_samples"
    primary_field = "sample_id"
    vector_field = "embedding"
    MANAGEMENT_FIELDS = [
        "sample_id",
        "summary",
        "description",
        "embedding",
        "enabled",
        "created_at",
        "updated_at",
    ]

    def __init__(
        self,
        client: Any,
        *,
        embedding_fn: EmbeddingFn,
        embedding_dim: int = 1024,
    ) -> None:
        super().__init__(client, embedding_dim=embedding_dim)
        self._embedding_fn = embedding_fn

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec("sample_id", DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSpec("summary", DataType.VARCHAR, max_length=2048),
            FieldSpec("description", DataType.VARCHAR, max_length=8192),
            FieldSpec("embedding", DataType.FLOAT_VECTOR, dim=self._embedding_dim),
            FieldSpec("enabled", DataType.BOOL),
            FieldSpec("created_at", DataType.VARCHAR, max_length=64),
            FieldSpec("updated_at", DataType.VARCHAR, max_length=64),
        ]

    async def append_event(
        self,
        event_id: str,
        summary: str,
        description: str = "",
    ) -> int:
        return await self.append_events([(event_id, summary, description)])

    async def append_events(
        self,
        events: Sequence[tuple[str, str] | tuple[str, str, str]],
    ) -> int:
        unique_events: dict[str, tuple[str, str]] = {}
        for event in events:
            event_id, summary, *description_parts = event
            if event_id in unique_events:
                continue
            description = description_parts[0] if description_parts else ""
            unique_events[event_id] = (summary, description)
        if not unique_events:
            return 0

        now = self.now_iso()
        existing_rows = self._find_sample_rows(list(unique_events))
        texts = [summary for summary, _description in unique_events.values()]
        try:
            embeddings = await self.resolve_embeddings(self._embedding_fn, texts)
        except Exception as exc:
            embeddings = [
                self.fallback_embedding(text, self._embedding_dim) for text in texts
            ]
            logger.warning(
                "event samples batch embedding failed, using fallback vectors: %s",
                exc,
            )
        rows = []
        for index, (event_id, (summary, description)) in enumerate(
            unique_events.items()
        ):
            existing = existing_rows.get(event_id, {})
            rows.append(
                {
                    "sample_id": event_id,
                    "summary": summary,
                    "description": description,
                    "embedding": embeddings[index],
                    "enabled": True,
                    "created_at": (
                        str(existing.get("created_at") or now) if existing else now
                    ),
                    "updated_at": now,
                }
            )
        return self.upsert_rows(rows)

    async def remove_event(self, event_id: str) -> bool:
        row = self._find_sample_row(event_id)
        if not row:
            return False
        row.update({"enabled": False, "updated_at": self.now_iso()})
        return self.upsert_rows([row]) > 0

    async def get_event_count(self) -> int:
        rows = self.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id"],
            limit=10000,
        )
        return len(rows)

    async def get_event_summaries(self) -> dict[str, str]:
        rows = self.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id", "summary"],
            limit=10000,
        )
        return {str(row["sample_id"]): str(row.get("summary") or "") for row in rows}

    async def find_best_match(
        self,
        query: str,
        *,
        threshold: float,
    ) -> EventSampleMatch | None:
        if await self.get_event_count() == 0:
            return None
        self.ensure_collection()
        try:
            try:
                query_embedding = await self.resolve_embedding(
                    self._embedding_fn, query
                )
            except Exception as exc:
                logger.warning(
                    "event samples query embedding failed, using fallback vector: %s",
                    exc,
                )
                query_embedding = self.fallback_embedding(query, self._embedding_dim)
            result = self._client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                anns_field=self.vector_field,
                filter="enabled == true",
                limit=1,
                output_fields=["sample_id", "summary", "description"],
            )
        except MilvusException as error:
            if not self._is_collection_not_found(error):
                raise
            self._recreate_collection()
            result = self._client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                anns_field=self.vector_field,
                filter="enabled == true",
                limit=1,
                output_fields=["sample_id", "summary", "description"],
            )
        hits = result[0] if result else []
        if not hits:
            return None
        return self._match_from_hit(hits[0], threshold)

    def list_items(self) -> list[dict[str, Any]]:
        rows = self.query_rows(
            'sample_id != "" and enabled == true',
            [
                "sample_id",
                "summary",
                "description",
                "enabled",
                "created_at",
                "updated_at",
            ],
            limit=10000,
        )
        return [
            {**row, "value": row["sample_id"]}
            for row in sorted(
                rows,
                key=lambda item: str(item.get("updated_at") or ""),
                reverse=True,
            )
        ]

    def list_management_items(
        self,
        *,
        keyword: str | None = None,
        enabled: bool | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        clauses = ['sample_id != ""']
        if enabled is not None:
            clauses.append(f"enabled == {str(enabled).lower()}")
        if keyword:
            clauses.append(
                self.like_filter(["sample_id", "summary", "description"], keyword)
            )
        rows = self.query_rows(
            " and ".join(clause for clause in clauses if clause),
            self.MANAGEMENT_FIELDS,
            limit=limit,
        )
        return sorted(
            rows,
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )

    def get_management_item(self, sample_id: str) -> dict[str, Any] | None:
        rows = self.query_rows(
            f"sample_id == {self.quote(sample_id)}",
            self.MANAGEMENT_FIELDS,
            limit=1,
        )
        return dict(rows[0]) if rows else None

    async def embed_management_summary(self, summary: str) -> ManagementEmbedding:
        try:
            return ManagementEmbedding(
                vector=await self.resolve_embedding(self._embedding_fn, summary),
                status="computed",
            )
        except Exception as exc:
            logger.warning(
                "event sample management embedding failed, using fallback vector: %s",
                exc,
            )
            return ManagementEmbedding(
                vector=self.fallback_embedding(summary, self._embedding_dim),
                status="fallback",
            )

    async def upsert_management_event(self, row: dict[str, Any]) -> int:
        now = self.now_iso()
        sample_id = str(row["sample_id"])
        existing = self.get_management_item(sample_id)
        payload = {
            "sample_id": sample_id,
            "summary": str(row.get("summary") or ""),
            "description": str(row.get("description") or ""),
            "embedding": list(row.get("embedding") or []),
            "enabled": bool(row.get("enabled", True)),
            "created_at": str(
                row.get("created_at") or (existing or {}).get("created_at") or now
            ),
            "updated_at": now,
        }
        return self.upsert_rows([payload])

    def hard_delete_events(self, sample_ids: list[str]) -> int:
        normalized = sorted({sample_id for sample_id in sample_ids if sample_id})
        if not normalized:
            return 0
        return self.delete_rows(self.id_filter("sample_id", normalized))

    def _find_sample_row(self, sample_id: str) -> dict[str, Any]:
        return self._find_sample_rows([sample_id]).get(sample_id, {})

    def _find_sample_rows(self, sample_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not sample_ids:
            return {}
        rows = self.query_rows(
            self.id_filter("sample_id", sample_ids),
            [
                "sample_id",
                "summary",
                "description",
                "embedding",
                "enabled",
                "created_at",
            ],
            limit=len(sample_ids),
        )
        return {str(row["sample_id"]): dict(row) for row in rows}

    @staticmethod
    def _match_from_hit(
        hit: dict[str, Any],
        threshold: float,
    ) -> EventSampleMatch | None:
        score = float(hit.get("distance") or 0.0)
        if score <= threshold:
            return None
        entity = hit.get("entity") or {}
        sample_id = str(entity.get("sample_id") or hit.get("id") or "")
        summary = str(entity.get("summary") or entity.get("description") or "")
        return EventSampleMatch(
            hit=True,
            score=score,
            event_id=sample_id,
            summary=summary,
            threshold=threshold,
        )
