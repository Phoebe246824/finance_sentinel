"""Reusable database-state assertions and diagnostics for the blacklist demo."""

from dataclasses import dataclass
from typing import Any

from sentinel.blacklist.milvus_stash import MilvusStashStore
from sentinel.config import get_settings


# ── Diagnostics ──────────────────────────────────────────────────────────
@dataclass
class MilvusDiagnostics:
    """Structured diagnostics to distinguish failure classes for a missing or inaccessible Milvus row.

    Fields
    ------
    connectivity_ok
        ``True`` if a lightweight Milvus API call (e.g. ``has_collection``) succeeded.
    collection_exists
        ``True`` if the event collection exists in Milvus.
    collection_name
        The event collection name that was checked.
    queried_event_id
        The *event_id* that was looked up (may be ``None`` if not provided).
    row_found
        ``True`` if at least one row matched *queried_event_id*.
    row_data
        The first matching row dict, if any.
    error_type
        Canonical failure class string. One of:
        ``None`` (no error), ``"missing_event_id"``, ``"backend_access_failed"``,
        ``"collection_not_found"``, ``"row_not_found"``.
    error_message
        Human-readable summary of the failure.
    connection_error
        Raw exception message from the connectivity check, if any.
    collection_error
        Raw exception message from the collection / query step, if any.
    all_rows_count
        Total rows in the collection (queried with no filter), or ``None``
        if the query failed.  Helps distinguish ``collection_not_found``
        from ``row_not_found`` when the collection exists but is empty.
    """

    connectivity_ok: bool | None = None
    collection_exists: bool | None = None
    collection_name: str | None = None
    queried_event_id: str | None = None
    row_found: bool | None = None
    row_data: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    connection_error: str | None = None
    collection_error: str | None = None
    all_rows_count: int | None = None


async def diagnose_milvus_failure(
    store: MilvusStashStore | None = None,
    event_id: str | None = None,
) -> MilvusDiagnostics:
    """Diagnose why a Milvus row is missing or inaccessible.

    Returns a :class:`MilvusDiagnostics` with structured fields that
    distinguish the following failure classes:

    * ``missing_event_id`` – no *event_id* was provided.
    * ``backend_access_failed`` – cannot reach the Milvus server at all.
    * ``collection_not_found`` – connection works but the event collection
      does not exist.
    * ``row_not_found`` – collection exists, connection works, but no
      row matches *event_id*.

    When *event_id* is ``None`` or the store cannot connect, the returned
    object's fields reflect exactly where the chain broke.

    Uses the store's canonical collection-read path so the diagnostic probes
    stay aligned with :class:`MilvusCaseInspector` without reaching into the
    store's private helpers directly.
    """
    diag = MilvusDiagnostics(
        queried_event_id=event_id,
    )

    # ---- check 1: event_id present ----------------------------------------
    if not event_id:
        diag.error_type = "missing_event_id"
        diag.error_message = "No event_id provided for diagnosis"
        return diag

    store = store or MilvusStashStore.from_settings(get_settings())
    collection_name: str = store._collection_name
    diag.collection_name = collection_name

    # ---- check 2: connectivity + collection existence ----------------------
    try:
        store.ensure_collection_ready()
        diag.collection_exists = True
        diag.connectivity_ok = True
    except Exception as exc:
        diag.connectivity_ok = False
        # Distinguish "Milvus server unreachable" from "collection missing"
        err_msg = str(exc)
        if "collection not found" in err_msg.lower() or "not exist" in err_msg.lower():
            diag.collection_exists = False
            diag.error_type = "collection_not_found"
        else:
            diag.error_type = "backend_access_failed"
        diag.connection_error = err_msg
        diag.error_message = f"Milvus connectivity / collection check failed: {exc}"
        return diag

    # ---- check 3: query for specific event_id via store's own path ---------
    try:
        raw_rows = store.query_event_rows(
            event_id,
            ["event_id", "person_ids", "is_graph_built", "raw_content"],
        )
        if not raw_rows:
            diag.row_found = False
            diag.error_type = "row_not_found"
            diag.all_rows_count = store.count_rows_for_diagnostics()
            diag.error_message = (
                f"Collection {collection_name!r} exists with "
                f"{diag.all_rows_count} total rows, but no row found for "
                f"event_id={event_id!r}"
            )
            return diag

        diag.row_found = True
        # Use the same dict-shape logic as MilvusCaseInspector.inspect_case
        first = raw_rows[0]
        diag.row_data = {
            "event_id": first.get("event_id"),
            "person_ids": sorted(first.get("person_ids") or []),
            "is_graph_built": first.get("is_graph_built"),
        }
        diag.error_type = None
        diag.error_message = None
    except Exception as exc:
        err_msg = str(exc)
        if "collection not found" in err_msg.lower() or "not exist" in err_msg.lower():
            diag.error_type = "collection_not_found"
            diag.collection_exists = False
        else:
            diag.error_type = "backend_access_failed"
        diag.collection_error = err_msg
        diag.error_message = (
            f"Milvus _query_rows error for event_id={event_id!r}: {err_msg}"
        )
        return diag

    return diag


CASE_TEXT_PERSISTENCE_QUERY = """
MATCH (e:Episodic)
WHERE e.content = $content
RETURN count(e) AS content_count
"""

EPISODIC_CONTENT_SCHEMA_QUERY = """
CALL db.labels() YIELD label
WITH collect(label) AS labels
CALL db.propertyKeys() YIELD propertyKey
WITH labels, collect(propertyKey) AS property_keys
RETURN 'Episodic' IN labels AS episodic_label_exists,
       'content' IN property_keys AS content_property_exists
"""


@dataclass(frozen=True)
class AssertionFailure:
    case_id: str
    path: str
    expected: Any
    observed: Any


def assert_case_state(
    case: dict[str, Any], observed: dict[str, Any]
) -> list[AssertionFailure]:
    expected = case.get("expect_state", {})
    case_id = case["id"]
    failures: list[AssertionFailure] = []
    failures.extend(_assert_expected_for_case(case_id, expected, observed))

    for related_case_id, related_expected in expected.get("after_case", {}).items():
        failures.extend(
            _assert_expected_for_case(related_case_id, related_expected, observed)
        )

    return failures


def _assert_expected_for_case(
    case_id: str,
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> list[AssertionFailure]:
    state = observed.get("cases", {}).get(case_id, {})
    failures: list[AssertionFailure] = []

    milvus_expected = expected.get("milvus", {})
    milvus_state = state.get("milvus", {})
    for key in ("exists", "person_ids", "is_graph_built"):
        if key in milvus_expected:
            observed_value = milvus_state.get(key)
            expected_value = milvus_expected[key]
            if key == "person_ids" and observed_value is not None:
                observed_value = sorted(observed_value)
                expected_value = sorted(expected_value)
            if observed_value != expected_value:
                failures.append(
                    AssertionFailure(
                        case_id, f"milvus.{key}", expected_value, observed_value
                    )
                )

    neo4j_expected = expected.get("neo4j", {})
    neo4j_state = state.get("neo4j", {})
    if (
        "content_count" in neo4j_expected
        and neo4j_state.get("content_count") != neo4j_expected["content_count"]
    ):
        failures.append(
            AssertionFailure(
                case_id,
                "neo4j.content_count",
                neo4j_expected["content_count"],
                neo4j_state.get("content_count"),
            )
        )
    if "content_count_at_most" in neo4j_expected:
        observed_count = neo4j_state.get("content_count")
        if (
            observed_count is None
            or observed_count > neo4j_expected["content_count_at_most"]
        ):
            failures.append(
                AssertionFailure(
                    case_id,
                    "neo4j.content_count_at_most",
                    neo4j_expected["content_count_at_most"],
                    observed_count,
                )
            )
    if (
        neo4j_expected.get("no_duplicate_content") is True
        and neo4j_state.get("duplicate_content") is True
    ):
        failures.append(
            AssertionFailure(case_id, "neo4j.no_duplicate_content", True, False)
        )

    return failures


async def collect_case_state_snapshot(
    cases: list[dict[str, Any]],
    milvus_inspector: Any | None = None,
    neo4j_inspector: Any | None = None,
) -> dict[str, Any]:
    milvus_inspector = milvus_inspector or MilvusCaseInspector()
    neo4j_inspector = neo4j_inspector or Neo4jCaseInspector()
    snapshot: dict[str, Any] = {"cases": {}}
    for case in cases:
        snapshot["cases"][case["id"]] = {
            "milvus": await milvus_inspector.inspect_case(case),
            "neo4j": await neo4j_inspector.inspect_case(case),
        }
    return snapshot


class MilvusCaseInspector:
    def __init__(self, store: MilvusStashStore | None = None):
        self._store = store or self._create_store_from_settings()

    @staticmethod
    def _create_store_from_settings() -> MilvusStashStore:
        return MilvusStashStore.from_settings(get_settings())

    async def inspect_case(self, case: dict[str, Any]) -> dict[str, Any]:
        event_id = case.get("event_id")
        if not event_id:
            return {"exists": False, "person_ids": [], "is_graph_built": None}

        rows = self._store.query_event_rows(
            event_id,
            ["event_id", "person_ids", "is_graph_built"],
        )
        if not rows:
            return {"exists": False, "person_ids": [], "is_graph_built": None}
        row = rows[0]
        return {
            "exists": True,
            "person_ids": sorted(row.get("person_ids") or []),
            "is_graph_built": row.get("is_graph_built"),
            "event_id": row.get("event_id"),
        }


class Neo4jCaseInspector:
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        driver_factory: Any | None = None,
    ):
        if uri is None or user is None or password is None or database is None:
            settings = get_settings()
            uri = uri or settings.neo4j_uri
            user = user or settings.neo4j_user
            password = password or settings.require_neo4j_password()
            database = database or settings.neo4j_database
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver_factory = driver_factory

    async def inspect_case(self, case: dict[str, Any]) -> dict[str, Any]:
        from neo4j import AsyncGraphDatabase

        if not self._password:
            raise RuntimeError("NEO4J_PASSWORD is required for demo state validation")

        driver_factory = self._driver_factory or AsyncGraphDatabase.driver
        driver = driver_factory(self._uri, auth=(self._user, self._password))
        try:
            async with driver.session(database=self._database) as session:
                schema_result = await session.run(EPISODIC_CONTENT_SCHEMA_QUERY)
                schema_record = await schema_result.single() or {}
                episodic_label_exists = bool(schema_record.get("episodic_label_exists"))
                content_property_exists = bool(
                    schema_record.get("content_property_exists")
                )

                if episodic_label_exists and content_property_exists:
                    result = await session.run(
                        CASE_TEXT_PERSISTENCE_QUERY,
                        content=case["text"],
                    )
                    record = await result.single()
                    content_count = int(record["content_count"] if record else 0)
                else:
                    content_count = 0
        finally:
            await driver.close()

        return {
            "content_count": content_count,
            "duplicate_content": content_count > 1,
            "episodic_label_exists": episodic_label_exists,
            "content_property_exists": content_property_exists,
        }
