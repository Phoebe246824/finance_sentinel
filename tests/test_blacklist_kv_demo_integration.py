import asyncio
import json
import os
import traceback
from dataclasses import asdict
from pathlib import Path

import pytest
from dotenv import load_dotenv

from scripts.blacklist_demo_assertions import (
    MilvusDiagnostics,
    assert_case_state,
    collect_case_state_snapshot,
    diagnose_milvus_failure,
)
from scripts.blacklist_demo_cases import CASES_BY_ID
from scripts.reset_and_seed_demo_state import main as reset_demo_state_main

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_ID = "case_01_low_risk_salary_baseline"
PROCESS_TIMEOUT_SECONDS = int(os.getenv("BLACKLIST_DEMO_PROCESS_TIMEOUT", "300"))
EVIDENCE_DIR = ROOT / ".omo" / "evidence"
EVIDENCE_SUMMARY_PATH = EVIDENCE_DIR / "task-1-feedback-loop.txt"
EVIDENCE_ERROR_PATH = EVIDENCE_DIR / "task-1-feedback-loop-error.txt"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _selected_case() -> dict:
    case_id = os.getenv("BLACKLIST_DEMO_CASE_ID", DEFAULT_CASE_ID)
    try:
        return CASES_BY_ID[case_id]
    except KeyError as exc:
        raise RuntimeError(f"Unknown BLACKLIST_DEMO_CASE_ID: {case_id}") from exc


def _write_evidence(summary: dict, error_text: str = "") -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    EVIDENCE_ERROR_PATH.write_text(error_text, encoding="utf-8")


def _format_assertion_failures(failures: list) -> str:
    return "\n".join(
        (
            f"[{failure.case_id}] {failure.path}: "
            f"expected={failure.expected!r}, observed={failure.observed!r}"
        )
        for failure in failures
    )


async def test_blacklist_kv_demo_database_states():
    load_dotenv(ROOT / ".env")

    if os.getenv("RUN_BLACKLIST_DEMO_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_BLACKLIST_DEMO_INTEGRATION=1 to run live blacklist demo integration test"
        )

    case = _selected_case()
    await reset_demo_state_main()

    import sentinel.main as sentinel_main

    app_settings = sentinel_main.get_settings()
    summary = {
        "command": "RUN_BLACKLIST_DEMO_INTEGRATION=1 uv run pytest tests/test_blacklist_kv_demo_integration.py -v -k blacklist_kv_demo_database_states",
        "selected_case_id": case["id"],
        "selected_case_title": case["title"],
        "failure_class": None,
        "event_id": None,
        "snapshot": None,
    }
    try:
        event_id = await asyncio.wait_for(
            sentinel_main.process_message(case["text"], app_settings),
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
        summary["event_id"] = event_id

        if not event_id:
            summary["failure_class"] = "missing EVENT_ID"
            _write_evidence(summary, "process_message() returned an empty event_id\n")
            pytest.fail(
                "failure_class=missing EVENT_ID: process_message() returned empty event_id"
            )

        processed_case = {**case, "event_id": event_id}
        snapshot = await collect_case_state_snapshot([processed_case])
        summary["snapshot"] = snapshot["cases"].get(case["id"])
        failures = assert_case_state(processed_case, snapshot)
        if failures:
            failure_text = _format_assertion_failures(failures)
            summary["failure_class"] = "assertion mismatch"

            # Enrich evidence with Milvus diagnostics when row is missing
            case_snap = snapshot["cases"].get(case["id"], {})
            case_milvus = case_snap.get("milvus", {})
            if not case_milvus.get("exists"):
                try:
                    _milvus_diag: MilvusDiagnostics = await diagnose_milvus_failure(
                        event_id=event_id,
                    )
                    summary["milvus_diagnostics"] = asdict(_milvus_diag)
                    if _milvus_diag.error_type:
                        summary["failure_class"] = _milvus_diag.error_type
                        summary["failure_origin"] = "assertion mismatch"
                    elif _milvus_diag.row_found:
                        # Diagnostics found the row, but the inspector
                        # (via MilvusCaseInspector) returned exists=False.
                        # This is a probe divergence — possibly Milvus
                        # eventual consistency (different client instances
                        # see different data) or a query filter mismatch.
                        summary["failure_class"] = "inspection_divergence"
                        summary["failure_origin"] = "assertion mismatch"
                except Exception as _diag_exc:
                    summary["milvus_diagnostics"] = {
                        "error_type": "diagnostics_raised",
                        "error_message": f"diagnose_milvus_failure raised: {_diag_exc}",
                    }
            else:
                # Row exists but field mismatch – keep original class
                summary["milvus_diagnostics"] = None

            _write_evidence(summary, failure_text + "\n")
            pytest.fail(f"failure_class={summary['failure_class']}\n{failure_text}")

        summary["failure_class"] = "none"
        _write_evidence(summary)
    except asyncio.TimeoutError as exc:
        summary["failure_class"] = "prompt timeout/subprocess stall"
        error_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        _write_evidence(summary, error_text)
        pytest.fail(f"failure_class=prompt timeout/subprocess stall\n{error_text}")
    except pytest.fail.Exception:
        raise
    except Exception as exc:
        summary["failure_class"] = "backend exception"
        error_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        # Attempt Milvus diagnostics to distinguish Milvus-specific
        # backend failures from other backend exceptions
        try:
            _milvus_diag: MilvusDiagnostics = await diagnose_milvus_failure(
                event_id=summary.get("event_id"),
            )
            summary["milvus_diagnostics"] = asdict(_milvus_diag)
            if _milvus_diag.error_type in (
                "backend_access_failed",
                "collection_not_found",
            ):
                summary["failure_class"] = _milvus_diag.error_type
                summary["failure_origin"] = "backend exception"
        except Exception:
            summary["milvus_diagnostics"] = None
        _write_evidence(summary, error_text)
        pytest.fail(f"failure_class={summary['failure_class']}\n{error_text}")
