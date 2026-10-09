"""Milvus-backed input event store and related-event recall helpers."""

import inspect
from datetime import datetime, timedelta
from typing import Any

from pymilvus.exceptions import MilvusException

from sentinel.blacklist.stores.base import EmbeddingFn, FieldSpec, MilvusBaseStore
from sentinel.blacklist.stores.events_schema import (
    EVENTS_COLLECTION,
    EVENTS_PRIMARY_FIELD,
    EVENTS_VECTOR_FIELD,
    events_fields,
)
from sentinel.models import NormalizedEvent
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


class EventsStore(MilvusBaseStore):
    """Milvus-backed input event store with related-event recall helpers."""

    collection_name = EVENTS_COLLECTION
    primary_field = EVENTS_PRIMARY_FIELD
    vector_field = EVENTS_VECTOR_FIELD
    OUTPUT_FIELDS = [
        "event_id",
        "person_ids",
        "raw_content",
        "created_at",
        "expire_at",
        "is_graph_built",
    ]
    ANALYSIS_FIELDS = [
        "analysis_status",
        "analyzed_at",
        "source",
        "event_type",
        "risk_level",
        "risk_score",
        "summary",
        "reasoning",
        "title",
        "event_timestamp",
        "key_entities_json",
        "dimension_scores_json",
        "trend_report_json",
        "graph_summary_json",
        "pipeline_message",
    ]
    WEB_OUTPUT_FIELDS = [*OUTPUT_FIELDS, *ANALYSIS_FIELDS]
    WEB_LIST_OUTPUT_FIELDS = [
        "event_id",
        "created_at",
        "analysis_status",
        "analyzed_at",
        "source",
        "event_type",
        "risk_level",
        "risk_score",
        "summary",
        "event_timestamp",
    ]

    def __init__(
        self,
        client: Any,
        *,
        embedding_fn: EmbeddingFn,
        embedding_dim: int = 1024,
        ttl_days: int = 90,
        collection_name: str | None = None,
        semantic_score_threshold: float = 0.0,
    ) -> None:
        del semantic_score_threshold
        super().__init__(client, embedding_dim=embedding_dim)
        self._embedding_fn = embedding_fn
        self._ttl_days = ttl_days
        if collection_name:
            self.collection_name = collection_name

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def fields(self) -> list[FieldSpec]:
        return events_fields(self._embedding_dim)

    def ensure_collection(self) -> None:
        if not self._collection_ready and self._client.has_collection(
            self.collection_name
        ):
            self._validate_existing_collection()
        super().ensure_collection()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stash_event(
        self,
        event_id: str,
        raw_content: str,
        person_ids: list[str],
        created_at: datetime | None = None,
    ) -> int:
        now = created_at or datetime.now()
        expire_at = now + timedelta(days=self._ttl_days)
        is_graph_built = self._existing_graph_built_state(event_id)
        row = {
            "event_id": event_id,
            "person_ids": sorted(
                {pid.upper() for pid in person_ids if pid.upper().startswith("P")}
            ),
            "raw_content": raw_content,
            "created_at": now.isoformat(timespec="seconds"),
            "expire_at": expire_at.isoformat(timespec="seconds"),
            "embedding": await self._embed(raw_content),
            "is_graph_built": is_graph_built,
            **self._empty_analysis_fields(),
        }
        return self.upsert_rows([row])

    def query_event_rows(
        self,
        event_id: str,
        output_fields: list[str] | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.query_rows(
            self._id_filter([event_id]),
            output_fields or self.OUTPUT_FIELDS,
            limit=limit,
        )

    async def update_analysis_result(
        self,
        event_id: str,
        fields: dict[str, Any],
    ) -> int:
        allowed = set(self.ANALYSIS_FIELDS)
        unexpected = sorted(set(fields) - allowed)
        if unexpected:
            raise ValueError("unknown analysis result fields: " + ", ".join(unexpected))

        rows = self.query_event_rows(
            event_id,
            [*self.OUTPUT_FIELDS, *self.ANALYSIS_FIELDS, "embedding"],
            limit=1,
        )
        if not rows:
            raise KeyError(f"event row not found: {event_id}")

        row = {
            **self._empty_analysis_fields(),
            **rows[0],
            **fields,
            "event_id": event_id,
        }
        return self.upsert_rows([row])

    def get_analysis_row(self, event_id: str) -> dict[str, Any] | None:
        rows = self.query_event_rows(event_id, self.WEB_OUTPUT_FIELDS, limit=1)
        return rows[0] if rows else None

    def list_analysis_rows(
        self,
        *,
        limit: int = 10000,
        source: str | None = None,
        risk_level: str | None = None,
        event_type: str | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.query_rows(
            self._analysis_rows_filter(
                source=source,
                risk_level=risk_level,
                event_type=event_type,
            ),
            output_fields or self.WEB_LIST_OUTPUT_FIELDS,
            limit=limit,
        )
        return sorted(
            rows,
            key=lambda row: str(row.get("analyzed_at") or row.get("created_at") or ""),
            reverse=True,
        )

    def _analysis_rows_filter(
        self,
        *,
        source: str | None = None,
        risk_level: str | None = None,
        event_type: str | None = None,
    ) -> str:
        if risk_level == "unassessed":
            clauses = ['analysis_status == "stashed"']
        elif risk_level:
            clauses = [
                'analysis_status == "analyzed"',
                f"risk_level == {self.quote(risk_level)}",
            ]
        else:
            clauses = ['analysis_status in ["stashed", "analyzed"]']
        if source:
            clauses.append(f"source == {self.quote(source)}")
        if event_type:
            clauses.append(f"event_type == {self.quote(event_type)}")
        return " and ".join(clauses)

    def count_rows_for_diagnostics(self, *, limit: int = 10000) -> int | None:
        try:
            rows = self.query_rows('event_id != ""', ["event_id"], limit=limit)
        except MilvusException:
            logger.warning(
                "count_rows_for_diagnostics: Milvus query failed for %s",
                self.collection_name,
                exc_info=True,
            )
            return None
        return len(rows) if rows else 0

    async def fetch_related_events(
        self,
        event: NormalizedEvent,
        id_numbers: list[str],
        top_k_semantic: int = 10,
        max_per_person: int = 20,
    ) -> list[dict[str, Any]]:
        now = datetime.now()
        eligible_rows = self._eligible_rows(event.event_id, now)
        person_ids = {pid.upper() for pid in id_numbers}

        person_matches = self._person_matches(eligible_rows, person_ids, max_per_person)
        semantic_matches = await self._semantic_matches(
            event.raw_content,
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
        unique_ids = sorted({eid for eid in event_ids if eid})
        if not unique_ids:
            return 0

        rows_by_id = {
            row["event_id"]: row
            for row in self.query_rows(
                self._id_filter(unique_ids),
                [*self.OUTPUT_FIELDS, *self.ANALYSIS_FIELDS, "embedding"],
            )
            if row.get("event_id") in unique_ids
        }
        rows = []
        for event_id in unique_ids:
            row = rows_by_id.get(event_id)
            if not row:
                logger.warning(
                    "mark_events_graph_built: event_id=%s not found in event collection",
                    event_id,
                )
                continue
            rows.append({**row, "is_graph_built": True})

        if rows:
            self.upsert_rows(rows)
        logger.info("marked %d Milvus event rows as graph built", len(rows))
        return len(rows)

    async def cleanup_expired(
        self, graph_built_retention_days: int | None = None
    ) -> int:
        now = datetime.now()
        delete_ids: list[str] = []

        expired_rows = self.query_rows(
            f"expire_at <= {self.quote(now.isoformat())}",
            ["event_id"],
        )
        delete_ids.extend(
            row["event_id"] for row in expired_rows if row.get("event_id")
        )

        if graph_built_retention_days is not None:
            retention_cutoff = now - timedelta(days=graph_built_retention_days)
            built_rows = self.query_rows(
                " and ".join(
                    [
                        "is_graph_built == true",
                        f"created_at <= {self.quote(retention_cutoff.isoformat())}",
                    ]
                ),
                ["event_id"],
            )
            delete_ids.extend(
                row["event_id"] for row in built_rows if row.get("event_id")
            )

        if not delete_ids:
            return 0
        return self.delete_rows(self._id_filter(delete_ids))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _existing_graph_built_state(self, event_id: str) -> bool:
        rows = self.query_event_rows(event_id, ["event_id", "is_graph_built"], limit=1)
        return bool(rows and rows[0].get("is_graph_built") is True)

    @staticmethod
    def _empty_analysis_fields() -> dict[str, Any]:
        return {
            "analysis_status": "stored",
            "analyzed_at": "",
            "source": "",
            "event_type": "",
            "risk_level": "",
            "risk_score": 0.0,
            "summary": "",
            "reasoning": "",
            "title": "",
            "event_timestamp": "",
            "key_entities_json": "[]",
            "dimension_scores_json": "{}",
            "trend_report_json": "{}",
            "graph_summary_json": "{}",
            "pipeline_message": "",
        }

    def _eligible_rows(
        self, current_event_id: str, now: datetime
    ) -> list[dict[str, Any]]:
        return self.query_rows(
            " and ".join(
                [
                    "is_graph_built == false",
                    f"expire_at > {self.quote(now.isoformat())}",
                    f"event_id != {self.quote(current_event_id)}",
                ]
            ),
            self.OUTPUT_FIELDS,
        )

    def _person_matches(
        self,
        rows: list[dict[str, Any]],
        person_ids: set[str],
        max_per_person: int,
    ) -> list[dict[str, Any]]:
        if not person_ids:
            return []

        matched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in sorted(
            rows, key=lambda item: item.get("created_at", ""), reverse=True
        ):
            row_person_ids = {pid.upper() for pid in row.get("person_ids", [])}
            if not person_ids.intersection(row_person_ids):
                continue
            eid = row["event_id"]
            if eid in seen:
                continue
            matched.append(row)
            seen.add(eid)
            if len(matched) >= max_per_person * len(person_ids):
                break
        return matched

    async def _semantic_matches(
        self,
        query_text: str,
        top_k: int,
        eligible_event_ids: set[str],
    ) -> list[dict[str, Any]]:
        if top_k <= 0 or not eligible_event_ids:
            return []

        self.ensure_collection()
        try:
            result = self._client.search(
                collection_name=self.collection_name,
                data=[await self._embed(query_text)],
                anns_field=self.vector_field,
                filter=self._id_filter(sorted(eligible_event_ids)),
                limit=top_k,
                output_fields=self.OUTPUT_FIELDS,
            )
        except MilvusException as error:
            if not self._is_collection_not_found(error):
                raise
            self._recreate_collection()
            result = self._client.search(
                collection_name=self.collection_name,
                data=[await self._embed(query_text)],
                anns_field=self.vector_field,
                filter=self._id_filter(sorted(eligible_event_ids)),
                limit=top_k,
                output_fields=self.OUTPUT_FIELDS,
            )
        rows: list[dict[str, Any]] = []
        for hit in result[0] if result else []:
            entity = dict(hit.get("entity", {}))
            event_id = entity.get("event_id") or hit.get("id")
            if event_id not in eligible_event_ids:
                continue
            entity["event_id"] = event_id
            entity["semantic_score"] = hit.get("distance", 0.0)
            rows.append(entity)
        rows.sort(
            key=lambda item: (
                item.get("semantic_score", 0.0),
                item.get("created_at", ""),
            ),
            reverse=True,
        )
        return rows

    async def _embed(self, text: str) -> list[float]:
        try:
            embedding = self._embedding_fn(text)
            if inspect.isawaitable(embedding):
                embedding = await embedding
            return [float(v) for v in embedding]
        except Exception as exc:
            logger.warning(
                "events store embedding failed, using fallback vector: %s",
                exc,
            )
            return self.fallback_embedding(text, self._embedding_dim)

    def _validate_existing_collection(self) -> None:
        describe_collection = getattr(self._client, "describe_collection", None)
        if describe_collection is None:
            return

        description = describe_collection(collection_name=self.collection_name)
        if not description:
            return

        if self._dynamic_fields_enabled(description):
            raise RuntimeError(
                f"Milvus collection {self.collection_name!r} uses dynamic fields; "
                "reset or migrate the collection before writing event records."
            )

        expected_fields = {field.name for field in events_fields(self._embedding_dim)}
        expected_specs = {
            field.name: field for field in events_fields(self._embedding_dim)
        }
        actual_fields = {
            str(field.get("name"))
            for field in description.get("fields", [])
            if field.get("name")
        }
        missing_fields = sorted(expected_fields - actual_fields)
        if missing_fields:
            if set(missing_fields).issubset(set(self.ANALYSIS_FIELDS)):
                self._add_missing_fields(
                    [expected_specs[name] for name in missing_fields],
                )
                return
            raise RuntimeError(
                f"Milvus collection {self.collection_name!r} is missing static "
                f"event fields: {', '.join(missing_fields)}"
            )

        embedding_dim = self._field_dim(description, self.vector_field)
        if embedding_dim is not None and embedding_dim != self._embedding_dim:
            raise RuntimeError(
                f"Milvus collection {self.collection_name!r} embedding dim is "
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

    @staticmethod
    def _source_rank(source: str) -> int:
        return {"both": 3, "person_match": 2, "semantic_match": 1}.get(source, 0)

    @staticmethod
    def _id_filter(event_ids: list[str]) -> str:
        return MilvusBaseStore.id_filter("event_id", event_ids)

    def _add_missing_fields(self, fields: list[FieldSpec]) -> None:
        add_field = getattr(self._client, "add_collection_field", None)
        if add_field is None:
            missing_names = ", ".join(field.name for field in fields)
            raise RuntimeError(
                f"Milvus collection {self.collection_name!r} is missing static "
                f"event fields: {missing_names}"
            )
        for field in fields:
            kwargs: dict[str, Any] = {}
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
            kwargs["nullable"] = True
            add_field(
                collection_name=self.collection_name,
                field_name=field.name,
                data_type=field.dtype,
                **kwargs,
            )
