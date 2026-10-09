from sentinel.blacklist.management import (
    BlacklistConflictError,
    BlacklistDuplicateError,
    BlacklistManagementService,
    BlacklistNotFoundError,
    BlacklistValidationError,
)
from sentinel.blacklist.stores.event_samples_store import EventSamplesStore
from sentinel.blacklist.stores.keywords_store import KeywordsStore
from sentinel.blacklist.stores.persons_store import PersonsStore
from tests.test_blacklist_stores import FakeMilvusClient


async def fake_embed(text: str) -> list[float]:
    return [float(len(text)), 0.2, 0.3]


async def failing_embed(text: str) -> list[float]:
    del text
    raise RuntimeError("embedding unavailable")


class SwitchableEmbedder:
    def __init__(self) -> None:
        self.fail = False

    async def __call__(self, text: str) -> list[float]:
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return await fake_embed(text)


class DelayedEmbedder:
    def __init__(self) -> None:
        self.calls = 0
        self.on_second_call = None

    async def __call__(self, text: str) -> list[float]:
        self.calls += 1
        if self.calls == 2 and self.on_second_call is not None:
            await self.on_second_call()
        return await fake_embed(text)


class Bundle:
    def __init__(self, embedding_fn=fake_embed) -> None:
        client = FakeMilvusClient()
        self.persons = PersonsStore(client, embedding_dim=3)
        self.keywords = KeywordsStore(client, embedding_dim=3)
        self.event_samples = EventSamplesStore(
            client,
            embedding_fn=embedding_fn,
            embedding_dim=3,
        )


async def test_apply_person_changeset_creates_updates_and_hard_deletes():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {
            "person_id": "P001",
            "summary": "old",
            "description": "",
            "enabled": True,
        }
    )
    existing = bundle.persons.get_management_item("P001")

    result = await service.apply_person_changeset(
        {
            "created": [
                {
                    "person_id": "P002",
                    "summary": "new",
                    "description": "created",
                    "enabled": True,
                    "hit_count": 99,
                }
            ],
            "updated": [
                {
                    "old_key": "P001",
                    "expected_updated_at": existing["updated_at"],
                    "person_id": "P010",
                    "summary": "renamed",
                    "description": "updated",
                    "enabled": False,
                    "hit_count": 42,
                }
            ],
            "deleted": [],
        }
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert bundle.persons.get_management_item("P001") is None
    assert bundle.persons.get_management_item("P010")["hit_count"] == 0
    assert bundle.persons.get_management_item("P010")["enabled"] is False
    assert bundle.persons.get_management_item("P002")["hit_count"] == 0


async def test_keyword_changeset_rejects_duplicate_new_keys():
    service = BlacklistManagementService(Bundle())

    try:
        await service.apply_keyword_changeset(
            {
                "created": [
                    {
                        "keyword": "重复",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    },
                    {
                        "keyword": "重复",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    },
                ],
                "updated": [],
                "deleted": [],
            }
        )
    except BlacklistDuplicateError as exc:
        assert "重复" in str(exc)
    else:
        raise AssertionError("duplicate keyword should fail")


async def test_keyword_changeset_rejects_blank_keyword():
    service = BlacklistManagementService(Bundle())

    try:
        await service.apply_keyword_changeset(
            {
                "created": [
                    {
                        "keyword": "   ",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "updated": [],
                "deleted": [],
            }
        )
    except BlacklistValidationError as exc:
        assert "keyword" in str(exc)
    else:
        raise AssertionError("blank keyword should fail")


async def test_person_changeset_rejects_blank_person_id():
    service = BlacklistManagementService(Bundle())

    try:
        await service.apply_person_changeset(
            {
                "created": [
                    {
                        "person_id": "   ",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "updated": [],
                "deleted": [],
            }
        )
    except BlacklistValidationError as exc:
        assert "person_id" in str(exc)
    else:
        raise AssertionError("blank person id should fail")


async def test_keyword_changeset_migrates_key_and_preserves_existing_hit_count():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.keywords.upsert_management_keyword(
        {
            "keyword": "旧关键词",
            "summary": "old",
            "description": "",
            "hit_count": 7,
            "enabled": True,
        }
    )
    old_id = KeywordsStore.keyword_id("旧关键词")
    existing = bundle.keywords.get_management_item(old_id)

    result = await service.apply_keyword_changeset(
        {
            "created": [
                {
                    "keyword": "新建关键词",
                    "summary": "created",
                    "description": "",
                    "enabled": True,
                    "hit_count": 88,
                }
            ],
            "updated": [
                {
                    "old_key": "旧关键词",
                    "expected_updated_at": existing["updated_at"],
                    "keyword": "迁移关键词",
                    "summary": "migrated",
                    "description": "updated",
                    "enabled": False,
                    "hit_count": 99,
                }
            ],
            "deleted": [],
        }
    )

    new_id = KeywordsStore.keyword_id("迁移关键词")
    created_id = KeywordsStore.keyword_id("新建关键词")
    assert result == {"created": 1, "updated": 1, "deleted": 1}
    assert bundle.keywords.get_management_item(old_id) is None
    assert bundle.keywords.get_management_item(new_id)["hit_count"] == 7
    assert bundle.keywords.get_management_item(new_id)["enabled"] is False
    assert bundle.keywords.get_management_item(created_id)["hit_count"] == 0


async def test_person_changeset_allows_chained_key_migration():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {"person_id": "P001", "summary": "one", "description": "", "enabled": True}
    )
    await bundle.persons.upsert_management_person(
        {"person_id": "P002", "summary": "two", "description": "", "enabled": True}
    )
    row_one = bundle.persons.get_management_item("P001")
    row_two = bundle.persons.get_management_item("P002")

    result = await service.apply_person_changeset(
        {
            "created": [],
            "updated": [
                {
                    "old_key": "P001",
                    "expected_updated_at": row_one["updated_at"],
                    "person_id": "P002",
                    "summary": "one migrated",
                    "description": "",
                    "enabled": True,
                },
                {
                    "old_key": "P002",
                    "expected_updated_at": row_two["updated_at"],
                    "person_id": "P003",
                    "summary": "two migrated",
                    "description": "",
                    "enabled": False,
                },
            ],
            "deleted": [],
        }
    )

    assert result == {"created": 0, "updated": 2, "deleted": 2}
    assert bundle.persons.get_management_item("P001") is None
    assert bundle.persons.get_management_item("P002")["summary"] == "one migrated"
    assert bundle.persons.get_management_item("P003")["summary"] == "two migrated"
    assert bundle.persons.get_management_item("P003")["enabled"] is False


async def test_management_lists_filter_and_page_rows():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {
            "person_id": "P001",
            "summary": "alpha",
            "description": "",
            "enabled": True,
        }
    )
    await bundle.persons.upsert_management_person(
        {
            "person_id": "P002",
            "summary": "beta",
            "description": "needle",
            "enabled": False,
        }
    )
    await bundle.persons.upsert_management_person(
        {
            "person_id": "P003",
            "summary": "needle",
            "description": "",
            "enabled": True,
        }
    )
    await bundle.keywords.upsert_management_keyword(
        {
            "keyword": "风险词一",
            "summary": "needle",
            "description": "",
            "enabled": True,
        }
    )
    await bundle.keywords.upsert_management_keyword(
        {
            "keyword": "风险词二",
            "summary": "other",
            "description": "",
            "enabled": False,
        }
    )
    await service.create_event(
        {
            "sample_id": "E001",
            "summary": "needle event",
            "description": "",
            "enabled": True,
        }
    )
    await service.create_event(
        {
            "sample_id": "E002",
            "summary": "other event",
            "description": "needle note",
            "enabled": False,
        }
    )

    persons = service.list_persons(keyword="needle", enabled=True, page=1, page_size=1)
    keywords = service.list_keywords(keyword="needle", enabled=True)
    events = service.list_events(keyword="needle", enabled=False)

    assert persons["total"] == 1
    assert persons["items"][0]["person_id"] == "P003"
    assert keywords["total"] == 1
    assert keywords["items"][0]["keyword"] == "风险词一"
    assert events["total"] == 1
    assert events["items"][0]["sample_id"] == "E002"
    assert "embedding" not in events["items"][0]


async def test_keyword_changeset_allows_swapping_keys():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.keywords.upsert_management_keyword(
        {"keyword": "甲", "summary": "a", "description": "", "enabled": True}
    )
    await bundle.keywords.upsert_management_keyword(
        {"keyword": "乙", "summary": "b", "description": "", "enabled": True}
    )
    row_a = bundle.keywords.get_management_item(KeywordsStore.keyword_id("甲"))
    row_b = bundle.keywords.get_management_item(KeywordsStore.keyword_id("乙"))

    result = await service.apply_keyword_changeset(
        {
            "created": [],
            "updated": [
                {
                    "old_key": "甲",
                    "expected_updated_at": row_a["updated_at"],
                    "keyword": "乙",
                    "summary": "a migrated",
                    "description": "",
                    "enabled": True,
                },
                {
                    "old_key": "乙",
                    "expected_updated_at": row_b["updated_at"],
                    "keyword": "甲",
                    "summary": "b migrated",
                    "description": "",
                    "enabled": False,
                },
            ],
            "deleted": [],
        }
    )

    assert result == {"created": 0, "updated": 2, "deleted": 2}
    assert (
        bundle.keywords.get_management_item(KeywordsStore.keyword_id("乙"))["summary"]
        == "a migrated"
    )
    assert (
        bundle.keywords.get_management_item(KeywordsStore.keyword_id("甲"))["summary"]
        == "b migrated"
    )


async def test_person_changeset_allows_created_key_released_by_delete():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {
            "person_id": "P001",
            "summary": "old",
            "description": "",
            "hit_count": 5,
            "enabled": True,
        }
    )
    existing = bundle.persons.get_management_item("P001")

    result = await service.apply_person_changeset(
        {
            "created": [
                {
                    "person_id": "P001",
                    "summary": "replacement",
                    "description": "new row",
                    "enabled": False,
                }
            ],
            "updated": [],
            "deleted": [
                {
                    "key": "P001",
                    "expected_updated_at": existing["updated_at"],
                }
            ],
        }
    )

    replacement = bundle.persons.get_management_item("P001")
    assert result == {"created": 1, "updated": 0, "deleted": 1}
    assert replacement["summary"] == "replacement"
    assert replacement["hit_count"] == 0
    assert replacement["enabled"] is False


async def test_changeset_validates_all_rows_before_any_write():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {"person_id": "P001", "summary": "old", "description": "", "enabled": True}
    )
    existing = bundle.persons.get_management_item("P001")

    try:
        await service.apply_person_changeset(
            {
                "created": [
                    {
                        "person_id": "P002",
                        "summary": "new",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "updated": [],
                "deleted": [
                    {
                        "key": "P001",
                        "expected_updated_at": f"{existing['updated_at']}-stale",
                    }
                ],
            }
        )
    except BlacklistConflictError:
        pass
    else:
        raise AssertionError("stale delete should fail")

    assert bundle.persons.get_management_item("P002") is None
    assert bundle.persons.get_management_item("P001") is not None


async def test_person_changeset_rejects_stale_update():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {"person_id": "P001", "summary": "old", "description": "", "enabled": True}
    )

    try:
        await service.apply_person_changeset(
            {
                "created": [],
                "updated": [
                    {
                        "old_key": "P001",
                        "expected_updated_at": "stale",
                        "person_id": "P001",
                        "summary": "new",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "deleted": [],
            }
        )
    except BlacklistConflictError as exc:
        assert "P001" in str(exc)
    else:
        raise AssertionError("stale update should fail")


async def test_changeset_rejects_duplicate_old_keys():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {"person_id": "P001", "summary": "old", "description": "", "enabled": True}
    )
    existing = bundle.persons.get_management_item("P001")

    try:
        await service.apply_person_changeset(
            {
                "created": [],
                "updated": [
                    {
                        "old_key": "P001",
                        "expected_updated_at": existing["updated_at"],
                        "person_id": "P010",
                        "summary": "new",
                        "description": "",
                        "enabled": True,
                    },
                    {
                        "old_key": "P001",
                        "expected_updated_at": existing["updated_at"],
                        "person_id": "P011",
                        "summary": "newer",
                        "description": "",
                        "enabled": True,
                    },
                ],
                "deleted": [],
            }
        )
    except BlacklistDuplicateError as exc:
        assert "P001" in str(exc)
    else:
        raise AssertionError("duplicate old keys should fail")


async def test_changeset_rejects_delete_count_mismatch():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await bundle.persons.upsert_management_person(
        {"person_id": "P001", "summary": "old", "description": "", "enabled": True}
    )
    existing = bundle.persons.get_management_item("P001")
    original_delete = bundle.persons.hard_delete_persons

    def partial_delete(keys):
        del keys
        return 0

    bundle.persons.hard_delete_persons = partial_delete

    try:
        await service.apply_person_changeset(
            {
                "created": [],
                "updated": [
                    {
                        "old_key": "P001",
                        "expected_updated_at": existing["updated_at"],
                        "person_id": "P002",
                        "summary": "new",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "deleted": [],
            }
        )
    except BlacklistConflictError as exc:
        assert "delete mismatch" in str(exc)
    else:
        raise AssertionError("delete count mismatch should fail")
    finally:
        bundle.persons.hard_delete_persons = original_delete

    assert bundle.persons.get_management_item("P001") is not None
    assert bundle.persons.get_management_item("P002") is None


async def test_event_update_recomputes_embedding_only_when_summary_changes():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)

    created = await service.create_event(
        {
            "sample_id": "E001",
            "summary": "短摘要",
            "description": "note",
            "enabled": True,
        }
    )
    original = bundle.event_samples.get_management_item("E001")

    description_only = await service.update_event(
        "E001",
        {
            "sample_id": "E002",
            "summary": "短摘要",
            "description": "changed note",
            "enabled": False,
            "expected_updated_at": original["updated_at"],
        },
    )
    renamed = bundle.event_samples.get_management_item("E002")

    assert created["embedding_status"] == "computed"
    assert description_only["embedding_status"] == "reused"
    assert renamed["embedding"] == original["embedding"]
    assert renamed["enabled"] is False

    summary_changed = await service.update_event(
        "E002",
        {
            "sample_id": "E002",
            "summary": "更长的摘要文本",
            "description": "changed note",
            "enabled": False,
            "expected_updated_at": renamed["updated_at"],
        },
    )

    assert summary_changed["embedding_status"] == "computed"
    assert (
        bundle.event_samples.get_management_item("E002")["embedding"]
        != original["embedding"]
    )


async def test_event_enable_toggle_reuses_embedding():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )
    original = bundle.event_samples.get_management_item("E001")

    result = await service.set_event_enabled(
        "E001",
        enabled=False,
        expected_updated_at=original["updated_at"],
    )

    updated = bundle.event_samples.get_management_item("E001")
    assert result["embedding_status"] == "reused"
    assert updated["enabled"] is False
    assert updated["embedding"] == original["embedding"]


async def test_event_create_rejects_empty_summary_and_duplicate_id():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)

    try:
        await service.create_event(
            {"sample_id": "E001", "summary": "", "description": "", "enabled": True}
        )
    except BlacklistValidationError:
        pass
    else:
        raise AssertionError("empty summary should fail")

    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )

    try:
        await service.create_event(
            {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
        )
    except BlacklistDuplicateError:
        pass
    else:
        raise AssertionError("duplicate event id should fail")


async def test_event_create_reports_fallback_embedding_status():
    bundle = Bundle(embedding_fn=failing_embed)
    service = BlacklistManagementService(bundle)

    result = await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )

    assert result["embedding_status"] == "fallback"
    assert bundle.event_samples.get_management_item("E001")["embedding"]


async def test_event_update_reports_fallback_embedding_status_when_summary_changes():
    embedder = SwitchableEmbedder()
    bundle = Bundle(embedding_fn=embedder)
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )
    original = bundle.event_samples.get_management_item("E001")
    embedder.fail = True

    result = await service.update_event(
        "E001",
        {
            "sample_id": "E001",
            "summary": "新摘要",
            "description": "",
            "enabled": True,
            "expected_updated_at": original["updated_at"],
        },
    )

    assert result["embedding_status"] == "fallback"


async def test_event_update_rechecks_timestamp_after_embedding_wait():
    embedder = DelayedEmbedder()
    bundle = Bundle(embedding_fn=embedder)
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )
    original = bundle.event_samples.get_management_item("E001")

    async def mutate_event_during_embedding():
        row = bundle.event_samples.get_management_item("E001")
        row["summary"] = "别人已经修改"
        await bundle.event_samples.upsert_management_event(row)

    embedder.on_second_call = mutate_event_during_embedding

    try:
        await service.update_event(
            "E001",
            {
                "sample_id": "E001",
                "summary": "新摘要",
                "description": "",
                "enabled": True,
                "expected_updated_at": original["updated_at"],
            },
        )
    except BlacklistConflictError as exc:
        assert "E001" in str(exc)
    else:
        raise AssertionError("stale event update after embedding should fail")

    assert bundle.event_samples.get_management_item("E001")["summary"] == "别人已经修改"


async def test_event_create_rechecks_duplicate_after_embedding_wait():
    embedder = DelayedEmbedder()
    bundle = Bundle(embedding_fn=embedder)
    service = BlacklistManagementService(bundle)

    async def create_duplicate_during_embedding():
        await bundle.event_samples.upsert_management_event(
            {
                "sample_id": "E001",
                "summary": "其他请求",
                "description": "",
                "embedding": [1.0, 0.2, 0.3],
                "enabled": True,
            }
        )

    embedder.on_second_call = create_duplicate_during_embedding
    await service.create_event(
        {"sample_id": "E000", "summary": "预热", "description": "", "enabled": True}
    )

    try:
        await service.create_event(
            {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
        )
    except BlacklistDuplicateError as exc:
        assert "E001" in str(exc)
    else:
        raise AssertionError("duplicate event after embedding should fail")

    assert bundle.event_samples.get_management_item("E001")["summary"] == "其他请求"


async def test_event_rename_delete_count_mismatch_restores_old_event():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {
            "sample_id": "E001",
            "summary": "原摘要",
            "description": "原备注",
            "enabled": True,
        }
    )
    existing = bundle.event_samples.get_management_item("E001")
    original_delete = bundle.event_samples.hard_delete_events

    def deleting_zero(keys):
        original_delete(keys)
        return 0

    bundle.event_samples.hard_delete_events = deleting_zero

    try:
        await service.update_event(
            "E001",
            {
                "sample_id": "E002",
                "summary": "原摘要",
                "description": "新备注",
                "enabled": True,
                "expected_updated_at": existing["updated_at"],
            },
        )
    except BlacklistConflictError as exc:
        assert "E001" in str(exc)
    else:
        raise AssertionError("event delete count mismatch should fail")
    finally:
        bundle.event_samples.hard_delete_events = original_delete

    restored = bundle.event_samples.get_management_item("E001")
    assert restored is not None
    assert restored["summary"] == "原摘要"
    assert bundle.event_samples.get_management_item("E002") is None


async def test_event_delete_requires_existing_row():
    service = BlacklistManagementService(Bundle())

    try:
        await service.delete_event("MISSING", expected_updated_at="missing")
    except BlacklistNotFoundError as exc:
        assert "MISSING" in str(exc)
    else:
        raise AssertionError("missing delete should fail")


async def test_event_delete_rejects_stale_timestamp():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )

    try:
        await service.delete_event("E001", expected_updated_at="stale")
    except BlacklistConflictError as exc:
        assert "E001" in str(exc)
    else:
        raise AssertionError("stale event delete should fail")


async def test_event_delete_rejects_delete_count_mismatch():
    bundle = Bundle()
    service = BlacklistManagementService(bundle)
    await service.create_event(
        {"sample_id": "E001", "summary": "摘要", "description": "", "enabled": True}
    )
    existing = bundle.event_samples.get_management_item("E001")
    original_delete = bundle.event_samples.hard_delete_events

    def deleting_zero(keys):
        original_delete(keys)
        return 0

    bundle.event_samples.hard_delete_events = deleting_zero

    try:
        await service.delete_event(
            "E001",
            expected_updated_at=existing["updated_at"],
        )
    except BlacklistConflictError as exc:
        assert "E001" in str(exc)
    else:
        raise AssertionError("event delete count mismatch should fail")
    finally:
        bundle.event_samples.hard_delete_events = original_delete

    assert bundle.event_samples.get_management_item("E001") is not None
