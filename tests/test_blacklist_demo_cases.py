from collections import Counter

from scripts.blacklist_demo_cases import CASES_BY_ID, TEST_CASES


def test_demo_cases_have_unique_ids_and_texts() -> None:
    case_ids = [case["id"] for case in TEST_CASES]
    duplicated_ids = [
        case_id for case_id, count in Counter(case_ids).items() if count > 1
    ]
    duplicated_texts = [
        text
        for text, count in Counter(case["text"] for case in TEST_CASES).items()
        if count > 1
    ]

    assert duplicated_ids == []
    assert duplicated_texts == []
    assert len(CASES_BY_ID) == len(TEST_CASES)


def test_demo_case_ids_use_full_event_store_language() -> None:
    stale_ids = [case["id"] for case in TEST_CASES if "stash" in case["id"]]

    assert stale_ids == []


def test_demo_cases_expect_milvus_full_event_store_rows() -> None:
    missing_rows = [
        case["id"]
        for case in TEST_CASES
        if case.get("expect_state", {}).get("milvus", {}).get("exists") is not True
    ]

    assert missing_rows == []
