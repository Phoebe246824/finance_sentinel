import pytest

from scripts.blacklist_demo_assertions import (
    CASE_TEXT_PERSISTENCE_QUERY,
    EPISODIC_CONTENT_SCHEMA_QUERY,
    AssertionFailure,
    MilvusCaseInspector,
    MilvusDiagnostics,
    Neo4jCaseInspector,
    assert_case_state,
    collect_case_state_snapshot,
    diagnose_milvus_failure,
)


def test_assert_case_state_accepts_matching_milvus_and_neo4j_state():
    case = {
        "id": "case_a",
        "expect_state": {
            "milvus": {"exists": True, "person_ids": ["P01"], "is_graph_built": False},
            "neo4j": {"content_count": 0},
        },
    }
    observed = {
        "cases": {
            "case_a": {
                "milvus": {
                    "exists": True,
                    "person_ids": ["P01"],
                    "is_graph_built": False,
                },
                "neo4j": {"content_count": 0},
            }
        }
    }

    failures = assert_case_state(case, observed)

    assert failures == []


def test_assert_case_state_reports_person_id_mismatch():
    case = {
        "id": "case_a",
        "expect_state": {"milvus": {"exists": True, "person_ids": ["P01"]}},
    }
    observed = {
        "cases": {
            "case_a": {
                "milvus": {"exists": True, "person_ids": ["P02"]},
                "neo4j": {"content_count": 0},
            }
        }
    }

    failures = assert_case_state(case, observed)

    assert failures == [
        AssertionFailure(
            case_id="case_a",
            path="milvus.person_ids",
            expected=["P01"],
            observed=["P02"],
        )
    ]


def test_assert_case_state_checks_after_case_expectations():
    case = {
        "id": "case_c",
        "expect_state": {
            "after_case": {
                "case_a": {
                    "milvus": {"is_graph_built": True},
                    "neo4j": {"content_count": 1},
                }
            }
        },
    }
    observed = {
        "cases": {
            "case_c": {"milvus": {"exists": False}, "neo4j": {"content_count": 1}},
            "case_a": {
                "milvus": {"is_graph_built": False},
                "neo4j": {"content_count": 1},
            },
        }
    }

    failures = assert_case_state(case, observed)

    assert failures == [
        AssertionFailure(
            case_id="case_a",
            path="milvus.is_graph_built",
            expected=True,
            observed=False,
        )
    ]


# ── Milvus diagnostics tests ─────────────────────────────────────────────


class FakeMilvusDiagnosticsStore:
    """Fake *MilvusStashStore* that exposes ``_ensure_collection()`` and
    ``_query_rows()`` — the same surface ``diagnose_milvus_failure`` uses.

    Each test constructs this with the *rows* it should return and optionally
    an *ensure_collection_error* to simulate connection failures.

    .. note::

       The name ``FakeMilvusDiagnosticsStore`` (not ``FakeMilvusStore``)
       avoids a name collision with the unrelated ``FakeMilvusStore`` at
       the bottom of this file that is used by the inspector tests.
    """

    def __init__(
        self,
        rows: list[dict] | None = None,
        collection_name: str = "input_events",
        ensure_collection_error: str | None = None,
        query_error: str | None = None,
    ):
        self._rows = list(rows) if rows else []
        self._collection_name = collection_name
        self._ensure_collection_error = ensure_collection_error
        self._query_error = query_error
        self._collection_ready = False

    def _ensure_collection(self) -> None:
        if self._ensure_collection_error is not None:
            raise ConnectionError(self._ensure_collection_error)
        self._collection_ready = True

    def ensure_collection_ready(self) -> None:
        self._ensure_collection()

    def _query_rows(
        self,
        filter_expr: str,
        output_fields: list[str],
        limit: int | None = None,
    ) -> list[dict]:
        if self._query_error is not None:
            raise RuntimeError(self._query_error)
        # Support 'event_id != ""' (all-rows) filter
        if 'event_id != ""' in filter_expr:
            return [{"event_id": r["event_id"]} for r in self._rows]
        # Support 'event_id in ["X"]' filter
        for row in self._rows:
            if filter_expr == f'event_id in ["{row.get("event_id")}"]':
                return [{f: row.get(f) for f in output_fields if f in row}]
        return []

    def query_event_rows(
        self,
        event_id: str,
        output_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._query_rows(
            f'event_id in ["{event_id}"]',
            output_fields,
            limit=limit,
        )

    def count_rows_for_diagnostics(self, *, limit: int = 10000) -> int | None:
        del limit
        return len(self._rows)


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_missing_event_id():
    """Missing *event_id* → error_type='missing_event_id'."""
    diag = await diagnose_milvus_failure(event_id=None)
    assert isinstance(diag, MilvusDiagnostics)
    assert diag.error_type == "missing_event_id"
    assert diag.queried_event_id is None


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_backend_access_failed():
    """Connection error → error_type='backend_access_failed'."""
    store = FakeMilvusDiagnosticsStore(
        ensure_collection_error="connection refused: Milvus not reachable",
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type == "backend_access_failed"
    assert diag.connectivity_ok is False
    assert "connection refused" in (diag.connection_error or "").lower()


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_collection_not_found():
    """Collection missing → error_type='collection_not_found'."""
    store = FakeMilvusDiagnosticsStore(
        ensure_collection_error="collection not found: input_events",
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type == "collection_not_found"
    assert diag.collection_exists is False


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_row_not_found():
    """Collection exists but no matching row → error_type='row_not_found'."""
    store = FakeMilvusDiagnosticsStore(
        rows=[{"event_id": "OTHER"}],
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type == "row_not_found"
    assert diag.row_found is False
    assert diag.collection_exists is True
    assert diag.all_rows_count == 1


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_row_found():
    """Collection exists and row found → error_type=None, row_found=True."""
    store = FakeMilvusDiagnosticsStore(
        rows=[
            {
                "event_id": "E001",
                "person_ids": ["P01"],
                "is_graph_built": False,
                "raw_content": "test",
            }
        ],
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type is None
    assert diag.row_found is True
    assert diag.row_data is not None
    assert diag.row_data.get("event_id") == "E001"
    assert diag.row_data.get("person_ids") == ["P01"]


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_query_error():
    """Collection exists but query raises → error_type='backend_access_failed'."""
    store = FakeMilvusDiagnosticsStore(
        rows=[{"event_id": "E001"}],
        query_error="internal error during query",
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type == "backend_access_failed"
    assert diag.collection_error is not None


@pytest.mark.asyncio
async def test_diagnose_milvus_failure_all_rows_count_on_error():
    """When _query_rows for specific ID fails, all_rows_count should still
    be populated if possible."""
    store = FakeMilvusDiagnosticsStore(
        rows=[{"event_id": "OTHER"}],
        # The all-rows query (_query_rows with event_id != "") works,
        # but the specific ID query should fail by returning no match.
    )
    # This tests that row_not_found correctly reports all_rows_count
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    assert diag.error_type == "row_not_found"
    assert diag.all_rows_count == 1


@pytest.mark.asyncio
async def test_diagnose_milvus_diagnostics_frozen_default():
    """MilvusDiagnostics default fields are None."""
    d = MilvusDiagnostics()
    assert d.error_type is None
    assert d.row_found is None
    assert d.collection_name is None


@pytest.mark.asyncio
async def test_diagnose_milvus_divergence_classification_contract():
    store = FakeMilvusDiagnosticsStore(
        rows=[
            {
                "event_id": "E001",
                "person_ids": ["P01"],
                "is_graph_built": False,
                "raw_content": "divergence test",
            }
        ],
    )
    diag = await diagnose_milvus_failure(store=store, event_id="E001")
    failure_class = "assertion mismatch"
    if diag.error_type:
        failure_class = diag.error_type
    elif diag.row_found:
        failure_class = "inspection_divergence"

    assert diag.row_found is True
    assert diag.error_type is None
    assert failure_class == "inspection_divergence"


class FakeMilvusInspector:
    def __init__(self):
        self.rows = {
            "case_a": {"exists": True, "person_ids": ["P01"], "is_graph_built": False},
            "case_b": {"exists": False, "person_ids": [], "is_graph_built": None},
        }

    async def inspect_case(self, case):
        return self.rows[case["id"]]


class FakeNeo4jInspector:
    def __init__(self):
        self.rows = {
            "case_a": {"content_count": 0, "duplicate_content": False},
            "case_b": {"content_count": 1, "duplicate_content": False},
        }

    async def inspect_case(self, case):
        return self.rows[case["id"]]


class FakeNeo4jResult:
    def __init__(self, record: dict[str, object]) -> None:
        self._record = record

    async def single(self) -> dict[str, object]:
        return self._record


class FakeNeo4jSession:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = list(records)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> "FakeNeo4jSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def run(self, query: str, **parameters: object) -> FakeNeo4jResult:
        self.calls.append((query, parameters))
        return FakeNeo4jResult(self._records.pop(0))


class FakeNeo4jDriver:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.closed = False
        self.session_kwargs: dict[str, str | None] = {}
        self.session_obj = FakeNeo4jSession(records)

    def session(self, **kwargs: str | None) -> FakeNeo4jSession:
        self.session_kwargs = kwargs
        return self.session_obj

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_collect_case_state_snapshot_uses_inspectors():
    cases = [
        {"id": "case_a", "text": "alpha", "event_id": "E001"},
        {"id": "case_b", "text": "beta", "event_id": "E002"},
    ]

    snapshot = await collect_case_state_snapshot(
        cases,
        milvus_inspector=FakeMilvusInspector(),
        neo4j_inspector=FakeNeo4jInspector(),
    )

    assert snapshot == {
        "cases": {
            "case_a": {
                "milvus": {
                    "exists": True,
                    "person_ids": ["P01"],
                    "is_graph_built": False,
                },
                "neo4j": {"content_count": 0, "duplicate_content": False},
            },
            "case_b": {
                "milvus": {"exists": False, "person_ids": [], "is_graph_built": None},
                "neo4j": {"content_count": 1, "duplicate_content": False},
            },
        }
    }


class FakeMilvusStore:
    """Minimal fake for ``MilvusCaseInspector`` tests. Uses ``_query_rows``
    to capture the filter expression that was sent."""

    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def _quote_literal(self, value):
        return f'"{value}"'

    def _query_rows(self, filter_expr, output_fields):
        del output_fields
        self.filters.append(filter_expr)
        return list(self.rows)

    def query_event_rows(self, event_id, output_fields, *, limit=None):
        del limit
        return self._query_rows(f'event_id in ["{event_id}"]', output_fields)


@pytest.mark.asyncio
async def test_milvus_case_inspector_queries_by_event_id():
    inspector = MilvusCaseInspector(
        store=FakeMilvusStore(
            [
                {
                    "event_id": "E001",
                    "person_ids": ["P01"],
                    "is_graph_built": False,
                },
            ]
        )
    )

    result = await inspector.inspect_case(
        {"id": "case_x", "text": "alpha", "event_id": "E001"}
    )

    assert result == {
        "exists": True,
        "person_ids": ["P01"],
        "is_graph_built": False,
        "event_id": "E001",
    }
    assert inspector._store.filters == ['event_id in ["E001"]']


@pytest.mark.asyncio
async def test_neo4j_case_inspector_queries_episodic_content_only() -> None:
    driver = FakeNeo4jDriver(
        records=[
            {"episodic_label_exists": True, "content_property_exists": True},
            {"content_count": 1},
        ]
    )
    factory_calls: list[tuple[str, tuple[str, str]]] = []

    def driver_factory(uri: str, auth: tuple[str, str]) -> FakeNeo4jDriver:
        factory_calls.append((uri, auth))
        return driver

    inspector = Neo4jCaseInspector(
        uri="bolt://neo4j:7687",
        user="neo4j",
        password="password",
        database="neo4j",
        driver_factory=driver_factory,
    )

    result = await inspector.inspect_case({"id": "case_x", "text": "alpha"})

    assert result == {
        "content_count": 1,
        "duplicate_content": False,
        "episodic_label_exists": True,
        "content_property_exists": True,
    }
    assert factory_calls == [("bolt://neo4j:7687", ("neo4j", "password"))]
    assert driver.session_kwargs == {"database": "neo4j"}
    assert driver.session_obj.calls == [
        (EPISODIC_CONTENT_SCHEMA_QUERY, {}),
        (CASE_TEXT_PERSISTENCE_QUERY, {"content": "alpha"}),
    ]
    assert driver.closed is True


@pytest.mark.asyncio
async def test_neo4j_case_inspector_skips_content_query_when_schema_absent() -> None:
    driver = FakeNeo4jDriver(
        records=[
            {"episodic_label_exists": False, "content_property_exists": False},
        ]
    )

    inspector = Neo4jCaseInspector(
        uri="bolt://neo4j:7687",
        user="neo4j",
        password="password",
        database="neo4j",
        driver_factory=lambda uri, auth: driver,
    )

    result = await inspector.inspect_case({"id": "case_x", "text": "alpha"})

    assert result == {
        "content_count": 0,
        "duplicate_content": False,
        "episodic_label_exists": False,
        "content_property_exists": False,
    }
    assert driver.session_obj.calls == [(EPISODIC_CONTENT_SCHEMA_QUERY, {})]
    assert driver.closed is True
