"""Operator-facing blacklist management service."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from sentinel.blacklist.stores.keywords_store import KeywordsStore


class BlacklistManagementError(Exception):
    status_code = 500


class BlacklistValidationError(BlacklistManagementError):
    status_code = 422


class BlacklistDuplicateError(BlacklistManagementError):
    status_code = 422


class BlacklistConflictError(BlacklistManagementError):
    status_code = 409


class BlacklistNotFoundError(BlacklistManagementError):
    status_code = 404


@dataclass(frozen=True, slots=True)
class PageResult:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    current: int
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "current": self.current,
            "size": self.size,
        }


NormalizeKey = Callable[[Any], str]
GetRow = Callable[[str], dict[str, Any] | None]
UpsertRow = Callable[[dict[str, Any]], Awaitable[int]]
HardDelete = Callable[[list[str]], int]


class BlacklistManagementService:
    def __init__(self, store_bundle: Any) -> None:
        self._bundle = store_bundle

    def list_persons(
        self,
        *,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        rows = self._bundle.persons.list_management_items(
            keyword=keyword,
            enabled=enabled,
            limit=10000,
        )
        return self._page(rows, page=page, page_size=page_size).as_dict()

    def list_keywords(
        self,
        *,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        rows = self._bundle.keywords.list_management_items(
            keyword=keyword,
            enabled=enabled,
            limit=10000,
        )
        return self._page(rows, page=page, page_size=page_size).as_dict()

    def list_events(
        self,
        *,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        rows = self._bundle.event_samples.list_management_items(
            keyword=keyword,
            enabled=enabled,
            limit=10000,
        )
        return self._page(
            self._strip_embedding(rows),
            page=page,
            page_size=page_size,
        ).as_dict()

    async def apply_person_changeset(
        self,
        changeset: dict[str, Any],
    ) -> dict[str, int]:
        return await self._apply_changeset(
            changeset,
            key_field="person_id",
            normalize_key=lambda value: self._required_key(value, "person_id").upper(),
            get_row=self._bundle.persons.get_management_item,
            upsert_row=self._bundle.persons.upsert_management_person,
            hard_delete=self._bundle.persons.hard_delete_persons,
        )

    async def apply_keyword_changeset(
        self,
        changeset: dict[str, Any],
    ) -> dict[str, int]:
        return await self._apply_changeset(
            changeset,
            key_field="keyword",
            normalize_key=lambda value: self._required_key(value, "keyword"),
            get_row=lambda keyword: self._bundle.keywords.get_management_item(
                KeywordsStore.keyword_id(str(keyword))
            ),
            upsert_row=self._bundle.keywords.upsert_management_keyword,
            hard_delete=self._bundle.keywords.hard_delete_keywords,
            delete_key_to_primary=KeywordsStore.keyword_id,
        )

    async def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        sample_id = self._required_text(payload, "sample_id")
        summary = self._required_text(payload, "summary")
        if self._bundle.event_samples.get_management_item(sample_id) is not None:
            raise BlacklistDuplicateError(f"duplicate event sample: {sample_id}")

        embedding = await self._bundle.event_samples.embed_management_summary(summary)
        if self._bundle.event_samples.get_management_item(sample_id) is not None:
            raise BlacklistDuplicateError(f"duplicate event sample: {sample_id}")
        await self._bundle.event_samples.upsert_management_event(
            {
                "sample_id": sample_id,
                "summary": summary,
                "description": str(payload.get("description") or ""),
                "embedding": embedding.vector,
                "enabled": bool(payload.get("enabled", True)),
            }
        )
        return {
            "item": self._event_without_embedding(
                self._bundle.event_samples.get_management_item(sample_id)
            ),
            "embedding_status": embedding.status,
        }

    async def update_event(
        self,
        old_sample_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        old_row = self._require_event(old_sample_id)
        self._check_expected_updated_at(
            old_sample_id,
            old_row,
            payload.get("expected_updated_at"),
        )
        new_sample_id = self._required_text(payload, "sample_id")
        new_summary = self._required_text(payload, "summary")
        existing_new = self._bundle.event_samples.get_management_item(new_sample_id)
        if new_sample_id != old_sample_id and existing_new is not None:
            raise BlacklistDuplicateError(f"duplicate event sample: {new_sample_id}")

        summary_changed = new_summary != str(old_row.get("summary") or "")
        embedding_result = (
            await self._bundle.event_samples.embed_management_summary(new_summary)
            if summary_changed
            else None
        )
        embedding = (
            embedding_result.vector
            if embedding_result is not None
            else list(old_row.get("embedding") or [])
        )
        current_old_row = self._require_event(old_sample_id)
        self._check_expected_updated_at(
            old_sample_id,
            current_old_row,
            payload.get("expected_updated_at"),
        )
        existing_new = self._bundle.event_samples.get_management_item(new_sample_id)
        if new_sample_id != old_sample_id and existing_new is not None:
            raise BlacklistDuplicateError(f"duplicate event sample: {new_sample_id}")
        next_row = {
            "sample_id": new_sample_id,
            "summary": new_summary,
            "description": str(payload.get("description") or ""),
            "embedding": embedding,
            "enabled": bool(payload.get("enabled", old_row.get("enabled", True))),
            "created_at": old_row.get("created_at"),
        }
        if new_sample_id != old_sample_id:
            new_upsert_attempted = False
            try:
                deleted_count = self._bundle.event_samples.hard_delete_events(
                    [old_sample_id]
                )
                if deleted_count != 1:
                    raise BlacklistConflictError(
                        f"delete mismatch for event sample: {old_sample_id}"
                    )
                new_upsert_attempted = True
                await self._bundle.event_samples.upsert_management_event(next_row)
            except Exception:
                if new_upsert_attempted:
                    with suppress(Exception):
                        self._bundle.event_samples.hard_delete_events([new_sample_id])
                with suppress(Exception):
                    if (
                        self._bundle.event_samples.get_management_item(old_sample_id)
                        is None
                    ):
                        await self._bundle.event_samples.upsert_management_event(
                            old_row
                        )
                raise
        else:
            await self._bundle.event_samples.upsert_management_event(next_row)

        return {
            "item": self._event_without_embedding(
                self._bundle.event_samples.get_management_item(new_sample_id)
            ),
            "embedding_status": (
                embedding_result.status if embedding_result is not None else "reused"
            ),
        }

    async def set_event_enabled(
        self,
        sample_id: str,
        *,
        enabled: bool,
        expected_updated_at: str,
    ) -> dict[str, Any]:
        row = self._require_event(sample_id)
        self._check_expected_updated_at(sample_id, row, expected_updated_at)
        row["enabled"] = enabled
        await self._bundle.event_samples.upsert_management_event(row)
        return {
            "item": self._event_without_embedding(
                self._bundle.event_samples.get_management_item(sample_id)
            ),
            "embedding_status": "reused",
        }

    async def delete_event(
        self,
        sample_id: str,
        *,
        expected_updated_at: str,
    ) -> dict[str, int]:
        row = self._require_event(sample_id)
        self._check_expected_updated_at(sample_id, row, expected_updated_at)
        deleted_count = self._bundle.event_samples.hard_delete_events([sample_id])
        if deleted_count != 1:
            with suppress(Exception):
                if self._bundle.event_samples.get_management_item(sample_id) is None:
                    await self._bundle.event_samples.upsert_management_event(row)
            raise BlacklistConflictError(
                f"delete mismatch for event sample: {sample_id}"
            )
        return {"deleted": deleted_count}

    async def _apply_changeset(
        self,
        changeset: dict[str, Any],
        *,
        key_field: str,
        normalize_key: NormalizeKey,
        get_row: GetRow,
        upsert_row: UpsertRow,
        hard_delete: HardDelete,
        delete_key_to_primary: Callable[[str], str] | None = None,
    ) -> dict[str, int]:
        created = list(changeset.get("created") or [])
        updated = list(changeset.get("updated") or [])
        deleted = list(changeset.get("deleted") or [])

        new_keys = [normalize_key(item[key_field]) for item in [*created, *updated]]
        self._reject_duplicate_values(new_keys)
        updated_old_keys = [normalize_key(item["old_key"]) for item in updated]
        deleted_keys = [normalize_key(item["key"]) for item in deleted]
        self._reject_duplicate_values(updated_old_keys)
        self._reject_duplicate_values(deleted_keys)
        self._reject_overlapping_values(updated_old_keys, deleted_keys)

        rows_to_upsert: list[dict[str, Any]] = []
        raw_delete_keys: list[str] = []
        original_rows: list[dict[str, Any]] = []
        existing_keys_to_release = set(updated_old_keys) | set(deleted_keys)

        for item in created:
            new_key = normalize_key(item[key_field])
            if get_row(new_key) is not None and new_key not in existing_keys_to_release:
                raise BlacklistDuplicateError(f"duplicate key: {new_key}")
            rows_to_upsert.append(
                {
                    **item,
                    key_field: new_key,
                    "hit_count": 0,
                }
            )

        for item in updated:
            old_key = normalize_key(item["old_key"])
            old_row = get_row(old_key)
            if old_row is None:
                raise BlacklistNotFoundError(f"row not found: {old_key}")
            original_rows.append(dict(old_row))
            self._check_expected_updated_at(
                old_key,
                old_row,
                item.get("expected_updated_at"),
            )
            new_key = normalize_key(item[key_field])
            existing_new = get_row(new_key)
            if (
                new_key != old_key
                and existing_new is not None
                and new_key not in existing_keys_to_release
            ):
                raise BlacklistDuplicateError(f"duplicate key: {new_key}")
            rows_to_upsert.append(
                {
                    **old_row,
                    **item,
                    key_field: new_key,
                    "created_at": old_row.get("created_at"),
                    "hit_count": old_row.get("hit_count", 0),
                }
            )
            if new_key != old_key:
                raw_delete_keys.append(old_key)

        for item in deleted:
            old_key = normalize_key(item["key"])
            old_row = get_row(old_key)
            if old_row is None:
                raise BlacklistNotFoundError(f"row not found: {old_key}")
            original_rows.append(dict(old_row))
            self._check_expected_updated_at(
                old_key,
                old_row,
                item.get("expected_updated_at"),
            )
            raw_delete_keys.append(old_key)

        final_upsert_keys = [
            normalize_key(row[key_field]) for row in rows_to_upsert if key_field in row
        ]
        delete_keys = list(dict.fromkeys(raw_delete_keys))
        primary_delete_keys = [
            delete_key_to_primary(key) if delete_key_to_primary else key
            for key in delete_keys
        ]
        rollback_keys = [
            delete_key_to_primary(key) if delete_key_to_primary else key
            for key in final_upsert_keys
        ]

        async def restore_missing_original_rows() -> None:
            for original_row in original_rows:
                with suppress(Exception):
                    original_key = normalize_key(original_row[key_field])
                    if get_row(original_key) is None:
                        await upsert_row(original_row)

        async def restore_all_original_rows() -> None:
            for original_row in original_rows:
                with suppress(Exception):
                    await upsert_row(original_row)

        attempted_upsert = False
        try:
            deleted_count = hard_delete(primary_delete_keys)
            if deleted_count != len(primary_delete_keys):
                raise BlacklistConflictError(
                    f"delete mismatch: expected {len(primary_delete_keys)}, got {deleted_count}"
                )
            for row in rows_to_upsert:
                attempted_upsert = True
                await upsert_row(row)
        except Exception:
            if attempted_upsert:
                with suppress(Exception):
                    hard_delete(rollback_keys)
                await restore_all_original_rows()
            else:
                await restore_missing_original_rows()
            raise
        return {
            "created": len(created),
            "updated": len(updated),
            "deleted": len(raw_delete_keys),
        }

    @staticmethod
    def _page(rows: list[dict[str, Any]], *, page: int, page_size: int) -> PageResult:
        start = (page - 1) * page_size
        end = start + page_size
        return PageResult(
            items=rows[start:end],
            total=len(rows),
            page=page,
            page_size=page_size,
            current=page,
            size=page_size,
        )

    @staticmethod
    def _strip_embedding(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            BlacklistManagementService._event_without_embedding(row) for row in rows
        ]

    @staticmethod
    def _event_without_embedding(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        return {key: value for key, value in row.items() if key != "embedding"}

    @staticmethod
    def _required_text(payload: dict[str, Any], field_name: str) -> str:
        value = str(payload.get(field_name) or "").strip()
        if not value:
            raise BlacklistValidationError(f"{field_name} is required")
        return value

    @staticmethod
    def _required_key(value: Any, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise BlacklistValidationError(f"{field_name} is required")
        return normalized

    @staticmethod
    def _reject_duplicate_values(values: list[str]) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                raise BlacklistDuplicateError(f"duplicate key: {value}")
            seen.add(value)

    @staticmethod
    def _reject_overlapping_values(left: list[str], right: list[str]) -> None:
        overlap = set(left) & set(right)
        if overlap:
            value = sorted(overlap)[0]
            raise BlacklistDuplicateError(f"duplicate key: {value}")

    @staticmethod
    def _check_expected_updated_at(
        key: str,
        row: dict[str, Any],
        expected: Any,
    ) -> None:
        if not expected or str(row.get("updated_at") or "") != str(expected):
            raise BlacklistConflictError(f"row changed: {key}")

    def _require_event(self, sample_id: str) -> dict[str, Any]:
        row = self._bundle.event_samples.get_management_item(sample_id)
        if row is None:
            raise BlacklistNotFoundError(f"event sample not found: {sample_id}")
        return row
