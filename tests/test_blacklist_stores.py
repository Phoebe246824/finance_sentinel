"""Tests for Milvus blacklist stores (PersonsStore, KeywordsStore, EventSamplesStore)."""

import json
from datetime import datetime, timedelta

from sentinel.blacklist.stores.event_samples_store import EventSamplesStore
from sentinel.blacklist.stores.events_store import EventsStore
from sentinel.blacklist.stores.keywords_store import KeywordsStore
from sentinel.blacklist.stores.persons_store import PersonsStore


class FakeMilvusClient:
    """Minimal fake MilvusClient for testing store CRUD."""

    def __init__(self) -> None:
        self._collections: dict[str, list[dict]] = {}
        self._has_collection = True
        self.upsert_calls: list[tuple[str, list[dict]]] = []
        self.query_calls: list[tuple[str, str, list[str], int | None]] = []
        self.search_calls: list[tuple[str, list, str, str | None, int, list[str]]] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.existing_schema: dict | None = None
        self.add_field_calls: list[tuple[str, str, object, dict[str, object]]] = []

    def has_collection(self, name: str) -> bool:
        return self._has_collection and (
            name in self._collections or self.existing_schema is not None
        )

    def create_collection(self, **kwargs: object) -> None:
        name = kwargs.get("collection_name", "")
        if name not in self._collections:
            self._collections[name] = []

    def add_collection_field(
        self,
        collection_name: str,
        field_name: str,
        data_type,
        **kwargs: object,
    ) -> None:
        self.add_field_calls.append(
            (collection_name, field_name, data_type, dict(kwargs))
        )
        del collection_name, data_type, kwargs
        fields = []
        if self.existing_schema is not None:
            fields = list(self.existing_schema.get("fields", []))
        fields.append({"name": field_name})
        if self.existing_schema is None:
            self.existing_schema = {"enable_dynamic_field": False, "fields": fields}
        else:
            self.existing_schema["fields"] = fields

    def describe_collection(self, collection_name: str) -> dict:
        del collection_name
        return self.existing_schema or {}

    def load_collection(self, **kwargs: object) -> None:
        pass

    def upsert(self, collection_name: str, data: list[dict]) -> dict:
        self.upsert_calls.append((collection_name, data))
        if collection_name not in self._collections:
            self._collections[collection_name] = []
        rows = self._collections[collection_name]
        for row in data:
            primary = (
                row.get("person_id")
                or row.get("keyword_id")
                or row.get("sample_id")
                or row.get("event_id")
            )
            rows = [r for r in rows if _primary_key(r) != primary]
            rows.append(row)
        self._collections[collection_name] = rows
        return {"upsert_count": len(data)}

    def query(
        self,
        collection_name: str,
        filter: str,
        output_fields: list[str],
        limit: int | None = None,
    ) -> list[dict]:
        self.query_calls.append((collection_name, filter, output_fields, limit))
        rows = self._collections.get(collection_name, [])
        result = []
        for row in rows:
            if _matches_filter(row, filter):
                filtered = {k: v for k, v in row.items() if k in output_fields}
                result.append(filtered)
                if limit is not None and len(result) >= limit:
                    break
        return result

    def search(
        self,
        collection_name: str,
        data: list,
        anns_field: str,
        filter: str | None,
        limit: int,
        output_fields: list[str],
    ) -> list[list[dict]]:
        self.search_calls.append(
            (collection_name, data, anns_field, filter, limit, output_fields)
        )
        rows = self._collections.get(collection_name, [])
        result = []
        for row in rows:
            if filter and not _matches_filter(row, filter):
                continue
            entity = {
                k: v
                for k, v in row.items()
                if k in output_fields or k in {"event_id", "sample_id"}
            }
            result.append(
                {
                    "id": row.get("event_id") or row.get("sample_id"),
                    "distance": 0.9,
                    "entity": entity,
                }
            )
        return [result[:limit]]

    def delete(self, collection_name: str, filter: str) -> dict:
        self.delete_calls.append((collection_name, filter))
        rows = self._collections.get(collection_name, [])
        kept_rows = [row for row in rows if not _matches_filter(row, filter)]
        deleted_count = len(rows) - len(kept_rows)
        self._collections[collection_name] = kept_rows
        return {"delete_count": deleted_count}

    def flush(self, **kwargs: object) -> None:
        pass


def _primary_key(row: dict) -> str | None:
    return (
        row.get("person_id")
        or row.get("keyword_id")
        or row.get("sample_id")
        or row.get("event_id")
    )


def _matches_filter(row: dict, filter_expr: str) -> bool:
    for field_name in (
        "person_id",
        "keyword_id",
        "sample_id",
        "event_id",
        "analysis_status",
    ):
        in_expr = f"{field_name} in ["
        if in_expr in filter_expr:
            values_text = filter_expr.split(in_expr, 1)[1].split("]", 1)[0]
            values = json.loads(f"[{values_text}]")
            if row.get(field_name) not in values:
                return False
    for field_name in ("analysis_status", "source", "risk_level", "event_type"):
        equality_expr = f"{field_name} == "
        if equality_expr in filter_expr:
            value_text = filter_expr.split(equality_expr, 1)[1].split(" and ", 1)[0]
            if row.get(field_name) != json.loads(value_text):
                return False
    if "enabled == true" in filter_expr:
        if not row.get("enabled", True):
            return False
    if "enabled == false" in filter_expr:
        if row.get("enabled", True):
            return False
    if "person_id ==" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "person_id ==" in part:
                val = part.split("==")[1].strip().strip('"')
                if row.get("person_id") != val:
                    return False
    if "keyword_id ==" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "keyword_id ==" in part:
                val = part.split("==")[1].strip().strip('"')
                if row.get("keyword_id") != val:
                    return False
    if "sample_id ==" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "sample_id ==" in part:
                val = part.split("==")[1].strip().strip('"')
                if row.get("sample_id") != val:
                    return False
    if "event_id !=" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "event_id !=" in part:
                val = part.split("!=")[1].strip().strip('"')
                if row.get("event_id") == val:
                    return False
    if "is_graph_built == true" in filter_expr:
        if row.get("is_graph_built") is not True:
            return False
    if "is_graph_built == false" in filter_expr:
        if row.get("is_graph_built") is not False:
            return False
    if "expire_at >" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "expire_at >" in part:
                val = part.split(">", maxsplit=1)[1].strip().strip('"')
                if str(row.get("expire_at", "")) <= val:
                    return False
    if "expire_at <=" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "expire_at <=" in part:
                val = part.split("<=", maxsplit=1)[1].strip().strip('"')
                if str(row.get("expire_at", "")) > val:
                    return False
    if "created_at <=" in filter_expr:
        for part in filter_expr.split("and"):
            part = part.strip()
            if "created_at <=" in part:
                val = part.split("<=", maxsplit=1)[1].strip().strip('"')
                if str(row.get("created_at", "")) > val:
                    return False
    if 'person_id != ""' in filter_expr:
        if not row.get("person_id"):
            return False
    if 'keyword_id != ""' in filter_expr:
        if not row.get("keyword_id"):
            return False
    if 'sample_id != ""' in filter_expr:
        if not row.get("sample_id"):
            return False
    if 'event_id != ""' in filter_expr:
        if not row.get("event_id"):
            return False
    if " like " in filter_expr:
        clauses = [part.strip("() ") for part in filter_expr.split(" or ")]
        if any(" like " in clause for clause in clauses):
            matched_like = False
            for clause in clauses:
                if " like " not in clause:
                    continue
                field_name, pattern_text = clause.split(" like ", 1)
                field_name = field_name.strip()
                pattern = json.loads(pattern_text.strip())
                needle = pattern.strip("%").lower()
                if needle in str(row.get(field_name, "")).lower():
                    matched_like = True
                    break
            if not matched_like:
                return False
    return True


def fake_embed(text: str) -> list[float]:
    return [0.1, 0.2, 0.3]


# ── EventsStore ───────────────────────────────────────────────────────


class TestEventsStore:
    def _make_store(self) -> tuple[EventsStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = EventsStore(client, embedding_fn=fake_embed, embedding_dim=3)
        return store, client

    def test_existing_dynamic_collection_is_rejected_before_write(self):
        store, client = self._make_store()
        client.existing_schema = {
            "enable_dynamic_field": True,
            "fields": [
                {"name": "event_id"},
                {"name": "embedding", "params": {"dim": 3}},
            ],
        }

        try:
            store.ensure_collection()
        except RuntimeError as exc:
            assert "uses dynamic fields" in str(exc)
        else:
            raise AssertionError("dynamic stash collection should be rejected")

    def test_existing_collection_missing_static_fields_is_rejected(self):
        store, client = self._make_store()
        client.existing_schema = {
            "enable_dynamic_field": False,
            "fields": [
                {"name": "event_id"},
                {"name": "embedding", "params": {"dim": 3}},
            ],
        }

        try:
            store.ensure_collection()
        except RuntimeError as exc:
            assert "missing static event fields" in str(exc)
            assert "raw_content" in str(exc)
        else:
            raise AssertionError("incomplete stash collection should be rejected")

    def test_existing_collection_with_only_analysis_fields_missing_is_auto_extended(
        self,
    ):
        store, client = self._make_store()
        client.existing_schema = {
            "enable_dynamic_field": False,
            "fields": [
                {"name": "event_id"},
                {"name": "person_ids"},
                {"name": "raw_content"},
                {"name": "created_at"},
                {"name": "expire_at"},
                {"name": "is_graph_built"},
                {"name": "embedding", "params": {"dim": 3}},
            ],
        }

        store.ensure_collection()

        field_names = {
            str(field.get("name"))
            for field in client.existing_schema["fields"]
            if field.get("name")
        }
        assert set(store.ANALYSIS_FIELDS).issubset(field_names)
        assert client.add_field_calls
        assert all(call[3].get("nullable") is True for call in client.add_field_calls)

    def test_existing_collection_with_wrong_embedding_dim_is_rejected(self):
        store, client = self._make_store()
        client.existing_schema = {
            "enable_dynamic_field": False,
            "fields": [
                {"name": "event_id"},
                {"name": "person_ids"},
                {"name": "raw_content"},
                {"name": "created_at"},
                {"name": "expire_at"},
                {"name": "is_graph_built"},
                {"name": "analysis_status"},
                {"name": "analyzed_at"},
                {"name": "source"},
                {"name": "event_type"},
                {"name": "risk_level"},
                {"name": "risk_score"},
                {"name": "summary"},
                {"name": "reasoning"},
                {"name": "title"},
                {"name": "event_timestamp"},
                {"name": "key_entities_json"},
                {"name": "dimension_scores_json"},
                {"name": "trend_report_json"},
                {"name": "graph_summary_json"},
                {"name": "pipeline_message"},
                {"name": "embedding", "params": {"dim": 1024}},
            ],
        }

        try:
            store.ensure_collection()
        except RuntimeError as exc:
            assert "embedding dim is 1024, expected 3" in str(exc)
        else:
            raise AssertionError("wrong-dimension stash collection should be rejected")

    async def test_stash_event_preserves_existing_graph_built_state(self):
        store, client = self._make_store()
        created_at = "2026-01-01T00:00:00"

        await store.stash_event(
            "E001",
            "alpha same person",
            ["P01"],
            datetime.fromisoformat(created_at),
        )
        await store.mark_events_graph_built(["E001"])
        await store.stash_event(
            "E001",
            "alpha same person",
            ["P01"],
            datetime.fromisoformat(created_at),
        )

        rows = client._collections[store.collection_name]
        assert len(rows) == 1
        assert rows[0]["is_graph_built"] is True

    async def test_stash_event_falls_back_when_embedding_times_out(self):
        client = FakeMilvusClient()

        async def timeout_embed(text: str) -> list[float]:
            raise TimeoutError()

        store = EventsStore(client, embedding_fn=timeout_embed, embedding_dim=3)

        await store.stash_event(
            "E001",
            "timeout text",
            ["P01"],
            datetime(2026, 1, 1, 12, 0, 0),
        )

        rows = client._collections[store.collection_name]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "E001"
        assert rows[0]["person_ids"] == ["P01"]
        assert len(rows[0]["embedding"]) == 3

    async def test_fetch_related_events_accepts_normalized_event(self):
        from sentinel.models import EventSource, NormalizedEvent

        store, _ = self._make_store()
        now = datetime.now()
        current_event = NormalizedEvent(
            event_id="CURRENT",
            source=EventSource.NEWS,
            raw_content="alpha trigger",
            title="current",
            timestamp=now,
        )

        await store.stash_event("CURRENT", "alpha trigger", ["P01"], now)
        await store.stash_event("RELATED", "alpha same person", ["P01"], now)
        await store.stash_event("OTHER", "alpha other person", ["P02"], now)

        results = await store.fetch_related_events(
            current_event,
            ["P01"],
            top_k_semantic=0,
            max_per_person=10,
        )

        assert [row["event_id"] for row in results] == ["RELATED"]

    async def test_fetch_related_events_excludes_current_built_and_expired_rows(self):
        from sentinel.models import EventSource, NormalizedEvent

        store, _ = self._make_store()
        current_time = datetime.now()
        current_event = NormalizedEvent(
            event_id="CURRENT",
            source=EventSource.NEWS,
            raw_content="alpha trigger",
            title="current",
            timestamp=current_time,
        )

        await store.stash_event("CURRENT", "alpha trigger", ["P01"], current_time)
        await store.stash_event("ELIGIBLE", "alpha same person", ["P01"], current_time)
        await store.stash_event("BUILT", "alpha built person", ["P01"], current_time)
        await store.mark_events_graph_built(["BUILT"])
        await store.stash_event(
            "EXPIRED",
            "alpha expired person",
            ["P01"],
            current_time - timedelta(days=120),
        )

        results = await store.fetch_related_events(
            current_event,
            ["P01"],
            top_k_semantic=10,
            max_per_person=10,
        )

        assert [row["event_id"] for row in results] == ["ELIGIBLE"]

    async def test_fetch_related_events_keeps_low_distance_semantic_candidates(self):
        from sentinel.models import EventSource, NormalizedEvent

        client = FakeMilvusClient()
        store = EventsStore(
            client,
            embedding_fn=fake_embed,
            embedding_dim=3,
            semantic_score_threshold=0.95,
        )
        current_time = datetime.now()
        current_event = NormalizedEvent(
            event_id="CURRENT",
            source=EventSource.NEWS,
            raw_content="alpha trigger",
            title="current",
            timestamp=current_time,
        )

        await store.stash_event("CURRENT", "alpha trigger", [], current_time)
        await store.stash_event("SEMANTIC", "alpha related", [], current_time)

        results = await store.fetch_related_events(
            current_event,
            [],
            top_k_semantic=10,
            max_per_person=10,
        )

        assert [row["event_id"] for row in results] == ["SEMANTIC"]
        assert results[0]["semantic_score"] == 0.9

    async def test_stash_event_keeps_only_person_prefixed_ids(self):
        store, client = self._make_store()

        await store.stash_event(
            "E001",
            "mixed identifiers",
            ["p01", "L02", "C03", "P01", "P04"],
            datetime(2026, 1, 1, 12, 0, 0),
        )

        rows = client._collections[store.collection_name]
        assert rows[0]["person_ids"] == ["P01", "P04"]

    def test_events_schema_includes_web_analysis_fields(self):
        from sentinel.blacklist.stores.events_schema import events_fields

        field_names = {field.name for field in events_fields(embedding_dim=3)}

        assert {
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
        }.issubset(field_names)

    async def test_update_analysis_result_preserves_existing_event_row(self):
        store, client = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        await store.stash_event("E001", "raw text", ["P01"], created_at)
        await store.update_analysis_result(
            "E001",
            {
                "analysis_status": "analyzed",
                "analyzed_at": "2026-01-01T12:01:00",
                "source": "news",
                "event_type": "负面舆情",
                "risk_level": "high",
                "risk_score": 0.91,
                "summary": "摘要",
                "reasoning": "推理",
                "title": "标题",
                "event_timestamp": "2026-01-01T12:00:00",
                "key_entities_json": "[]",
                "dimension_scores_json": '{"risk": 0.91}',
                "trend_report_json": '{"severity_name": "严重"}',
                "graph_summary_json": "{}",
                "pipeline_message": "分析完成",
            },
        )

        rows = client._collections[store.collection_name]
        assert len(rows) == 1
        row = rows[0]
        assert row["event_id"] == "E001"
        assert row["raw_content"] == "raw text"
        assert row["person_ids"] == ["P01"]
        assert row["embedding"] == [0.1, 0.2, 0.3]
        assert row["analysis_status"] == "analyzed"
        assert row["risk_score"] == 0.91

    async def test_mark_events_graph_built_preserves_analysis_fields(self):
        store, client = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        await store.stash_event("E001", "raw text", ["P01"], created_at)
        await store.update_analysis_result(
            "E001",
            {
                "analysis_status": "analyzed",
                "analyzed_at": "2026-01-01T12:01:00",
                "source": "news",
                "event_type": "负面舆情",
                "risk_level": "high",
                "risk_score": 0.91,
                "summary": "摘要",
                "reasoning": "推理",
                "title": "标题",
                "event_timestamp": "2026-01-01T12:00:00",
                "key_entities_json": "[]",
                "dimension_scores_json": '{"risk": 0.91}',
                "trend_report_json": '{"severity_name": "严重"}',
                "graph_summary_json": "{}",
                "pipeline_message": "分析完成",
            },
        )

        await store.mark_events_graph_built(["E001"])

        row = client._collections[store.collection_name][0]
        assert row["is_graph_built"] is True
        assert row["analysis_status"] == "analyzed"
        assert row["summary"] == "摘要"

    async def test_update_analysis_result_raises_for_missing_event(self):
        store, _ = self._make_store()

        try:
            await store.update_analysis_result(
                "MISSING",
                {
                    "analysis_status": "failed",
                    "analyzed_at": "2026-01-01T12:01:00",
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
                    "pipeline_message": "missing",
                },
            )
        except KeyError as exc:
            assert "MISSING" in str(exc)
        else:
            raise AssertionError("missing event row should raise KeyError")

    async def test_list_analysis_rows_returns_completed_rows_only(self):
        store, client = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        await store.stash_event("PENDING", "pending text", [], created_at)
        await store.stash_event("DONE", "done text", [], created_at)
        await store.update_analysis_result(
            "DONE",
            {
                "analysis_status": "analyzed",
                "analyzed_at": "2026-01-01T12:01:00",
                "source": "news",
                "event_type": "负面舆情",
                "risk_level": "high",
                "risk_score": 0.8,
                "summary": "done",
                "reasoning": "",
                "title": "",
                "event_timestamp": "2026-01-01T12:00:00",
                "key_entities_json": "[]",
                "dimension_scores_json": "{}",
                "trend_report_json": "{}",
                "graph_summary_json": "{}",
                "pipeline_message": "complete",
            },
        )

        rows = store.list_analysis_rows(limit=100)

        assert [row["event_id"] for row in rows] == ["DONE"]
        assert client.query_calls[-1][1] == 'analysis_status in ["stashed", "analyzed"]'

    async def test_list_analysis_rows_filters_completed_rows_before_limit(self):
        store, _ = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        await store.stash_event("PENDING-1", "pending one", [], created_at)
        await store.stash_event("PENDING-2", "pending two", [], created_at)
        await store.stash_event("DONE", "done text", [], created_at)
        await store.update_analysis_result(
            "DONE",
            {
                "analysis_status": "analyzed",
                "analyzed_at": "2026-01-01T12:01:00",
                "source": "news",
                "event_type": "负面舆情",
                "risk_level": "high",
                "risk_score": 0.8,
                "summary": "done",
                "reasoning": "",
                "title": "",
                "event_timestamp": "2026-01-01T12:00:00",
                "key_entities_json": "[]",
                "dimension_scores_json": "{}",
                "trend_report_json": "{}",
                "graph_summary_json": "{}",
                "pipeline_message": "complete",
            },
        )

        rows = store.list_analysis_rows(limit=1)

        assert [row["event_id"] for row in rows] == ["DONE"]

    async def test_list_analysis_rows_pushes_web_filters_before_limit(self):
        store, client = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        for event_id, source, risk_level, event_type in [
            ("NEWS-HIGH", "news", "high", "负面舆情"),
            ("NEWS-LOW", "news", "low", "负面舆情"),
            ("TX-HIGH", "transaction", "high", "交易异常"),
        ]:
            await store.stash_event(event_id, event_id, [], created_at)
            await store.update_analysis_result(
                event_id,
                {
                    "analysis_status": "analyzed",
                    "analyzed_at": "2026-01-01T12:01:00",
                    "source": source,
                    "event_type": event_type,
                    "risk_level": risk_level,
                    "risk_score": 0.8,
                    "summary": event_id,
                    "reasoning": "",
                    "title": "",
                    "event_timestamp": "2026-01-01T12:00:00",
                    "key_entities_json": "[]",
                    "dimension_scores_json": "{}",
                    "trend_report_json": "{}",
                    "graph_summary_json": "{}",
                    "pipeline_message": "complete",
                },
            )

        rows = store.list_analysis_rows(
            limit=1,
            source="news",
            risk_level="high",
            event_type="负面舆情",
        )

        assert [row["event_id"] for row in rows] == ["NEWS-HIGH"]
        assert (
            client.query_calls[-1][1] == 'analysis_status == "analyzed"'
            ' and risk_level == "high"'
            ' and source == "news"'
            f" and event_type == {json.dumps('负面舆情')}"
        )

    async def test_list_analysis_rows_filters_unassessed_by_effective_status(self):
        store, client = self._make_store()
        created_at = datetime(2026, 1, 1, 12, 0, 0)

        await store.stash_event("LEGACY-STASH", "legacy stashed", [], created_at)
        await store.update_analysis_result(
            "LEGACY-STASH",
            {
                "analysis_status": "stashed",
                "analyzed_at": "2026-01-01T12:01:00",
                "source": "news",
                "event_type": "未触发",
                "risk_level": "medium",
                "risk_score": 0.5,
                "summary": "legacy",
                "reasoning": "",
                "title": "",
                "event_timestamp": "2026-01-01T12:00:00",
                "key_entities_json": "[]",
                "dimension_scores_json": '{"risk":0.5}',
                "trend_report_json": "{}",
                "graph_summary_json": "{}",
                "pipeline_message": "stashed",
            },
        )

        unassessed_rows = store.list_analysis_rows(limit=10, risk_level="unassessed")
        medium_rows = store.list_analysis_rows(limit=10, risk_level="medium")

        assert [row["event_id"] for row in unassessed_rows] == ["LEGACY-STASH"]
        assert medium_rows == []
        assert client.query_calls[-2][1] == 'analysis_status == "stashed"'
        assert (
            client.query_calls[-1][1]
            == 'analysis_status == "analyzed" and risk_level == "medium"'
        )


# ── PersonsStore ──────────────────────────────────────────────────────


class TestPersonsStore:
    def _make_store(self) -> tuple[PersonsStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = PersonsStore(client, embedding_dim=3)
        return store, client

    def test_query_person_returns_none_when_missing(self):
        store, _ = self._make_store()
        result = store.query_rows(
            'person_id == "P99" and enabled == true',
            ["person_id", "hit_count"],
            limit=1,
        )
        assert result == []

    def test_append_person_upserts(self):
        store, client = self._make_store()
        count = store.upsert_rows(
            [
                {
                    "person_id": "P01",
                    "summary": "test",
                    "description": "",
                    "hit_count": 1,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ]
        )
        assert count == 1
        assert len(client.upsert_calls) == 1

    async def test_append_persons_batches_lookup_and_upsert(self):
        store, client = self._make_store()
        client.upsert(
            "blacklist_persons",
            [
                {
                    "person_id": "P05",
                    "summary": "old",
                    "description": "old description",
                    "hit_count": 2,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        client.upsert_calls.clear()
        client.query_calls.clear()

        count = await store.append_persons(["p05", "P06", "p05"])

        assert count == 2
        assert len(client.query_calls) == 1
        assert len(client.upsert_calls) == 1
        collection_name, rows = client.upsert_calls[0]
        assert collection_name == "blacklist_persons"
        assert {row["person_id"] for row in rows} == {"P05", "P06"}
        rows_by_person = {row["person_id"]: row for row in rows}
        assert rows_by_person["P05"]["hit_count"] == 3
        assert rows_by_person["P05"]["created_at"] == "2026-01-01T00:00:00"
        assert rows_by_person["P06"]["hit_count"] == 1

    def test_query_person_returns_hit(self):
        store, client = self._make_store()
        client.upsert(
            "blacklist_persons",
            [
                {
                    "person_id": "P05",
                    "summary": "test person",
                    "description": "",
                    "hit_count": 3,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        rows = store.query_rows(
            'person_id == "P05" and enabled == true',
            ["person_id", "hit_count"],
            limit=1,
        )
        assert len(rows) == 1
        assert rows[0]["person_id"] == "P05"

    def test_remove_person_sets_disabled(self):
        store, client = self._make_store()
        client.upsert(
            "blacklist_persons",
            [
                {
                    "person_id": "P01",
                    "summary": "",
                    "description": "",
                    "hit_count": 1,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        rows = store.query_rows(
            'person_id == "P01"',
            [
                "person_id",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
            ],
            limit=1,
        )
        row = dict(rows[0])
        row.update({"enabled": False, "updated_at": "2026-06-01T00:00:00"})
        store.upsert_rows([row])

        query_result = store.query_rows(
            'person_id == "P01" and enabled == true',
            ["person_id"],
            limit=1,
        )
        assert len(query_result) == 0

    def test_get_person_stats(self):
        store, client = self._make_store()
        for pid in ["P01", "P02"]:
            client.upsert(
                "blacklist_persons",
                [
                    {
                        "person_id": pid,
                        "summary": "",
                        "description": "",
                        "hit_count": 5,
                        "enabled": True,
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                ],
            )
        rows = store.query_rows(
            'person_id != "" and enabled == true',
            ["person_id", "hit_count"],
            limit=10000,
        )
        stats = {str(r["person_id"]): float(r.get("hit_count") or 1.0) for r in rows}
        assert stats["P01"] == 5.0
        assert stats["P02"] == 5.0

    async def test_person_management_upsert_defaults_hit_count_zero_and_hard_deletes(
        self,
    ):
        store, client = self._make_store()

        await store.upsert_management_person(
            {
                "person_id": "p900",
                "summary": "manual person",
                "description": "managed from dashboard",
                "enabled": True,
            }
        )

        rows = store.list_management_items(limit=10)
        assert rows[0]["person_id"] == "P900"
        assert rows[0]["hit_count"] == 0
        assert rows[0]["enabled"] is True

        deleted = store.hard_delete_persons(["P900"])

        assert deleted == 1
        assert client.delete_calls[-1] == ("blacklist_persons", 'person_id in ["P900"]')
        assert store.list_management_items(limit=10) == []

    async def test_management_upsert_uses_subsecond_updated_at_for_conflicts(self):
        store, _ = self._make_store()

        await store.upsert_management_person(
            {
                "person_id": "P901",
                "summary": "first",
                "description": "",
                "enabled": True,
            }
        )
        first = store.get_management_item("P901")

        await store.upsert_management_person(
            {
                "person_id": "P901",
                "summary": "second",
                "description": "",
                "enabled": True,
            }
        )
        second = store.get_management_item("P901")

        assert first["updated_at"] != second["updated_at"]


# ── KeywordsStore ─────────────────────────────────────────────────────


class TestKeywordsStore:
    def _make_store(self) -> tuple[KeywordsStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = KeywordsStore(client, embedding_dim=3)
        return store, client

    def test_keyword_id_is_deterministic(self):
        kid1 = KeywordsStore.keyword_id("制裁")
        kid2 = KeywordsStore.keyword_id("制裁")
        assert kid1 == kid2
        assert len(kid1) == 64

    def test_append_keyword_upserts(self):
        store, client = self._make_store()
        count = store.upsert_rows(
            [
                {
                    "keyword_id": KeywordsStore.keyword_id("制裁"),
                    "keyword": "制裁",
                    "summary": "",
                    "description": "",
                    "hit_count": 1,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ]
        )
        assert count == 1

    async def test_append_keywords_batches_lookup_and_upsert(self):
        store, client = self._make_store()
        existing_keyword = "制裁"
        existing_id = KeywordsStore.keyword_id(existing_keyword)
        client.upsert(
            "blacklist_keywords",
            [
                {
                    "keyword_id": existing_id,
                    "keyword": existing_keyword,
                    "summary": "old",
                    "description": "old description",
                    "hit_count": 2,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        client.upsert_calls.clear()
        client.query_calls.clear()

        count = await store.append_keywords(["制裁", "爆炸", "制裁"])

        assert count == 2
        assert len(client.query_calls) == 1
        assert len(client.upsert_calls) == 1
        collection_name, rows = client.upsert_calls[0]
        assert collection_name == "blacklist_keywords"
        assert {row["keyword"] for row in rows} == {"制裁", "爆炸"}
        rows_by_keyword = {row["keyword"]: row for row in rows}
        assert rows_by_keyword["制裁"]["hit_count"] == 3
        assert rows_by_keyword["制裁"]["created_at"] == "2026-01-01T00:00:00"
        assert rows_by_keyword["爆炸"]["hit_count"] == 1

    def test_query_keywords_returns_list(self):
        store, client = self._make_store()
        for kw in ["制裁", "爆炸"]:
            client.upsert(
                "blacklist_keywords",
                [
                    {
                        "keyword_id": KeywordsStore.keyword_id(kw),
                        "keyword": kw,
                        "summary": "",
                        "description": "",
                        "hit_count": 1,
                        "enabled": True,
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                ],
            )
        rows = store.query_rows(
            'keyword_id != "" and enabled == true',
            ["keyword", "updated_at"],
            limit=10000,
        )
        keywords = [str(r["keyword"]) for r in rows]
        assert "制裁" in keywords
        assert "爆炸" in keywords

    def test_remove_keyword_sets_disabled(self):
        store, client = self._make_store()
        kw = "制裁"
        kid = KeywordsStore.keyword_id(kw)
        client.upsert(
            "blacklist_keywords",
            [
                {
                    "keyword_id": kid,
                    "keyword": kw,
                    "summary": "",
                    "description": "",
                    "hit_count": 1,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        rows = store.query_rows(
            f'keyword_id == "{kid}"',
            [
                "keyword_id",
                "keyword",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
            ],
            limit=1,
        )
        row = dict(rows[0])
        row.update({"enabled": False, "updated_at": "2026-06-01T00:00:00"})
        store.upsert_rows([row])

        query_result = store.query_rows(
            f'keyword_id == "{kid}" and enabled == true',
            ["keyword_id"],
            limit=1,
        )
        assert len(query_result) == 0

    def test_remove_keyword_returns_false_when_missing(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            f'keyword_id == "{KeywordsStore.keyword_id("不存在")}"',
            [
                "keyword_id",
                "keyword",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
            ],
            limit=1,
        )
        assert len(rows) == 0

    async def test_keyword_management_migrates_keyword_id_without_incrementing_hits(
        self,
    ):
        store, _ = self._make_store()
        old_id = KeywordsStore.keyword_id("旧关键词")

        await store.upsert_management_keyword(
            {
                "keyword": "旧关键词",
                "summary": "old",
                "description": "",
                "enabled": True,
            }
        )
        row = store.get_management_item(old_id)
        assert row is not None
        row["keyword"] = "新关键词"

        await store.upsert_management_keyword(row)

        new_id = KeywordsStore.keyword_id("新关键词")
        assert store.get_management_item(new_id)["hit_count"] == 0


# ── EventSamplesStore ────────────────────────────────────────────────


class TestEventSamplesStore:
    def _make_store(self) -> tuple[EventSamplesStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = EventSamplesStore(client, embedding_fn=fake_embed, embedding_dim=3)
        return store, client

    def test_append_event_upserts_with_embedding(self):
        store, client = self._make_store()
        count = store.upsert_rows(
            [
                {
                    "sample_id": "E001",
                    "summary": "test event",
                    "description": "test event",
                    "embedding": [0.1, 0.2, 0.3],
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ]
        )
        assert count == 1

    async def test_append_events_batches_lookup_embeddings_and_upsert(self):
        embedded_texts: list[object] = []

        async def tracking_embed(
            text: str | list[str],
        ) -> list[float] | list[list[float]]:
            embedded_texts.append(text)
            if isinstance(text, list):
                return [[float(len(item)), 0.2, 0.3] for item in text]
            return [float(len(text)), 0.2, 0.3]

        client = FakeMilvusClient()
        store = EventSamplesStore(client, embedding_fn=tracking_embed, embedding_dim=3)
        client.upsert(
            "blacklist_event_samples",
            [
                {
                    "sample_id": "E001",
                    "summary": "old summary",
                    "description": "old description",
                    "embedding": [0.1, 0.2, 0.3],
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        client.upsert_calls.clear()
        client.query_calls.clear()

        count = await store.append_events(
            [
                ("E001", "updated summary"),
                ("E002", "new summary", "new description"),
                ("E001", "duplicate summary"),
            ]
        )

        assert count == 2
        assert embedded_texts == [["updated summary", "new summary"]]
        assert len(client.query_calls) == 1
        assert len(client.upsert_calls) == 1
        collection_name, rows = client.upsert_calls[0]
        assert collection_name == "blacklist_event_samples"
        assert {row["sample_id"] for row in rows} == {"E001", "E002"}
        rows_by_sample = {row["sample_id"]: row for row in rows}
        assert rows_by_sample["E001"]["created_at"] == "2026-01-01T00:00:00"
        assert rows_by_sample["E002"]["created_at"] != "2026-01-01T00:00:00"
        assert rows_by_sample["E002"]["description"] == "new description"

    async def test_append_events_prefers_batch_embedding_fn(self):
        client = FakeMilvusClient()
        batch_calls: list[list[str]] = []

        async def tracking_embed_batch(texts: list[str]) -> list[list[float]]:
            batch_calls.append(texts)
            return [[float(len(text)), 0.2, 0.3] for text in texts]

        store = EventSamplesStore(
            client,
            embedding_fn=tracking_embed_batch,
            embedding_dim=3,
        )

        count = await store.append_events(
            [
                ("E001", "summary one", "description one"),
                ("E002", "summary two", "description two"),
            ]
        )

        assert count == 2
        assert batch_calls == [["summary one", "summary two"]]

    async def test_append_events_falls_back_when_batch_embedding_times_out(self):
        client = FakeMilvusClient()

        async def timeout_embed(texts: list[str]) -> list[list[float]]:
            raise TimeoutError()

        store = EventSamplesStore(
            client,
            embedding_fn=timeout_embed,
            embedding_dim=3,
        )

        count = await store.append_events(
            [
                ("E001", "summary one", "description one"),
                ("E002", "summary two", "description two"),
            ]
        )

        assert count == 2
        rows = client._collections[store.collection_name]
        assert {row["sample_id"] for row in rows} == {"E001", "E002"}
        assert all(len(row["embedding"]) == 3 for row in rows)

    async def test_find_best_match_falls_back_when_query_embedding_times_out(self):
        client = FakeMilvusClient()

        async def timeout_embed(text: str) -> list[float]:
            raise TimeoutError()

        store = EventSamplesStore(
            client,
            embedding_fn=timeout_embed,
            embedding_dim=3,
        )
        client.upsert(
            "blacklist_event_samples",
            [
                {
                    "sample_id": "E001",
                    "summary": "test event",
                    "description": "test event",
                    "embedding": [0.1, 0.2, 0.3],
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )

        match = await store.find_best_match("timeout query", threshold=0.5)

        assert match is not None
        assert match.event_id == "E001"

    def test_get_event_count(self):
        store, client = self._make_store()
        for eid in ["E001", "E002", "E003"]:
            client.upsert(
                "blacklist_event_samples",
                [
                    {
                        "sample_id": eid,
                        "summary": f"event {eid}",
                        "description": "",
                        "embedding": [0.1, 0.2, 0.3],
                        "enabled": True,
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                ],
            )
        rows = store.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id"],
            limit=10000,
        )
        assert len(rows) == 3

    def test_get_event_summaries(self):
        store, client = self._make_store()
        client.upsert(
            "blacklist_event_samples",
            [
                {
                    "sample_id": "E001",
                    "summary": "刀具事件",
                    "description": "",
                    "embedding": [0.1, 0.2, 0.3],
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
        )
        rows = store.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id", "summary"],
            limit=10000,
        )
        summaries = {str(r["sample_id"]): str(r.get("summary") or "") for r in rows}
        assert summaries["E001"] == "刀具事件"

    def test_match_from_hit_above_threshold(self):
        hit = {"distance": 0.8, "entity": {"sample_id": "E001", "summary": "test"}}
        result = EventSamplesStore._match_from_hit(hit, threshold=0.5)
        assert result is not None
        assert result.hit is True
        assert result.score == 0.8
        assert result.event_id == "E001"

    def test_match_from_hit_below_threshold(self):
        hit = {"distance": 0.3, "entity": {"sample_id": "E001", "summary": "test"}}
        result = EventSamplesStore._match_from_hit(hit, threshold=0.5)
        assert result is None

    def test_match_from_hit_exact_threshold_returns_none(self):
        hit = {"distance": 0.5, "entity": {"sample_id": "E001", "summary": "test"}}
        result = EventSamplesStore._match_from_hit(hit, threshold=0.5)
        assert result is None

    async def test_event_sample_management_embeds_summary_only_and_can_reuse_embedding(
        self,
    ):
        embedded_inputs: list[object] = []

        async def tracking_embed(
            text: str | list[str],
        ) -> list[float] | list[list[float]]:
            embedded_inputs.append(text)
            if isinstance(text, list):
                return [[float(len(item)), 0.2, 0.3] for item in text]
            return [float(len(text)), 0.2, 0.3]

        client = FakeMilvusClient()
        store = EventSamplesStore(client, embedding_fn=tracking_embed, embedding_dim=3)

        embedding = await store.embed_management_summary("摘要文本")
        await store.upsert_management_event(
            {
                "sample_id": "E-MANAGED",
                "summary": "摘要文本",
                "description": "不会进入向量",
                "embedding": embedding.vector,
                "enabled": True,
            }
        )

        row = store.get_management_item("E-MANAGED")
        assert embedding.status == "computed"
        assert row["embedding"] == [4.0, 0.2, 0.3]
        assert embedded_inputs == ["摘要文本"]

        row["sample_id"] = "E-MANAGED-RENAMED"
        await store.upsert_management_event(row)
        assert store.get_management_item("E-MANAGED-RENAMED")["embedding"] == [
            4.0,
            0.2,
            0.3,
        ]

    async def test_management_lists_filter_keyword_enabled_and_limit(self):
        store, _ = self._make_store()
        await store.upsert_management_event(
            {
                "sample_id": "E001",
                "summary": "alpha needle",
                "description": "",
                "embedding": [0.1, 0.2, 0.3],
                "enabled": True,
            }
        )
        await store.upsert_management_event(
            {
                "sample_id": "E002",
                "summary": "beta",
                "description": "needle note",
                "embedding": [0.1, 0.2, 0.3],
                "enabled": False,
            }
        )
        await store.upsert_management_event(
            {
                "sample_id": "E003",
                "summary": "gamma needle",
                "description": "",
                "embedding": [0.1, 0.2, 0.3],
                "enabled": True,
            }
        )

        rows = store.list_management_items(
            keyword="needle",
            enabled=True,
            limit=1,
        )

        assert len(rows) == 1
        assert rows[0]["enabled"] is True
        assert "needle" in rows[0]["summary"]


# ── Async integration tests ─────────────────────────────────────────


class TestPersonsStoreAsync:
    def _make_store(self) -> tuple[PersonsStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = PersonsStore(client, embedding_dim=3)
        return store, client

    def test_query_person_returns_none_for_missing(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            'person_id == "P99" and enabled == true',
            ["person_id", "hit_count"],
            limit=1,
        )
        assert rows == []

    def test_get_person_stats_empty(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            'person_id != "" and enabled == true',
            ["person_id", "hit_count"],
            limit=10000,
        )
        assert rows == []


class TestKeywordsStoreAsync:
    def _make_store(self) -> tuple[KeywordsStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = KeywordsStore(client, embedding_dim=3)
        return store, client

    def test_get_keyword_stats_empty(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            'keyword_id != "" and enabled == true',
            ["keyword", "hit_count"],
            limit=10000,
        )
        assert rows == []


class TestEventSamplesStoreAsync:
    def _make_store(self) -> tuple[EventSamplesStore, FakeMilvusClient]:
        client = FakeMilvusClient()
        store = EventSamplesStore(client, embedding_fn=fake_embed, embedding_dim=3)
        return store, client

    def test_get_event_count_empty(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id"],
            limit=10000,
        )
        assert rows == []

    def test_get_event_summaries_empty(self):
        store, _ = self._make_store()
        rows = store.query_rows(
            'sample_id != "" and enabled == true',
            ["sample_id", "summary"],
            limit=10000,
        )
        assert rows == []
