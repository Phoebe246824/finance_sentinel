"""人员黑名单的 Milvus 存取。"""

from typing import Any

from pymilvus import DataType

from sentinel.blacklist.stores.base import FieldSpec, MilvusBaseStore


class PersonsStore(MilvusBaseStore):
    collection_name = "blacklist_persons"
    primary_field = "person_id"
    MANAGEMENT_FIELDS = [
        "person_id",
        "summary",
        "description",
        "hit_count",
        "enabled",
        "created_at",
        "updated_at",
    ]

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec("person_id", DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSpec("summary", DataType.VARCHAR, max_length=1024),
            FieldSpec("description", DataType.VARCHAR, max_length=4096),
            FieldSpec("hit_count", DataType.INT64),
            FieldSpec("enabled", DataType.BOOL),
            FieldSpec("created_at", DataType.VARCHAR, max_length=64),
            FieldSpec("updated_at", DataType.VARCHAR, max_length=64),
        ]

    async def query_person(self, id_number: str) -> float | None:
        """Check if person is on the blacklist.

        Returns ``1.0`` if the person exists and is enabled, ``None`` otherwise.
        The return value does **not** represent hit count — it is a presence
        indicator matching the ``PersonsLookup`` protocol used by
        ``BlacklistFilter``.
        """
        rows = self.query_rows(
            f"person_id == {self.quote(id_number.upper())} and enabled == true",
            ["person_id", "hit_count"],
            limit=1,
        )
        return 1.0 if rows else None

    async def append_person(
        self,
        id_number: str,
        summary: str = "",
        description: str = "",
    ) -> int:
        return await self.append_persons(
            [id_number],
            summary=summary,
            description=description,
        )

    async def append_persons(
        self,
        id_numbers: list[str],
        summary: str = "",
        description: str = "",
    ) -> int:
        person_ids = list(dict.fromkeys(id_number.upper() for id_number in id_numbers))
        if not person_ids:
            return 0

        now = self.now_iso()
        existing_rows = self._find_person_rows(person_ids)
        rows = []
        for person_id in person_ids:
            existing = existing_rows.get(person_id, {})
            rows.append(
                {
                    "person_id": person_id,
                    "summary": summary,
                    "description": description,
                    "hit_count": (
                        int(existing.get("hit_count") or 0) + 1 if existing else 1
                    ),
                    "enabled": True,
                    "created_at": (
                        str(existing.get("created_at") or now) if existing else now
                    ),
                    "updated_at": now,
                }
            )
        return self.upsert_rows(rows)

    async def remove_person(self, id_number: str) -> bool:
        row = self._find_person_row(id_number.upper())
        if not row:
            return False
        row.update({"enabled": False, "updated_at": self.now_iso()})
        return self.upsert_rows([row]) > 0

    async def get_person_stats(self) -> dict[str, float]:
        rows = self.query_rows(
            'person_id != "" and enabled == true',
            ["person_id", "hit_count"],
            limit=10000,
        )
        return {
            str(row["person_id"]): float(row.get("hit_count") or 1.0) for row in rows
        }

    def list_items(self) -> list[dict[str, Any]]:
        rows = self.query_rows(
            'person_id != "" and enabled == true',
            [
                "person_id",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
                "updated_at",
            ],
            limit=10000,
        )
        return [
            {**row, "value": row["person_id"]}
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
        clauses = ['person_id != ""']
        if enabled is not None:
            clauses.append(f"enabled == {str(enabled).lower()}")
        if keyword:
            clauses.append(
                self.like_filter(["person_id", "summary", "description"], keyword)
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

    def get_management_item(self, person_id: str) -> dict[str, Any] | None:
        rows = self.query_rows(
            f"person_id == {self.quote(person_id.upper())}",
            self.MANAGEMENT_FIELDS,
            limit=1,
        )
        return dict(rows[0]) if rows else None

    async def upsert_management_person(self, row: dict[str, Any]) -> int:
        now = self.now_iso()
        person_id = str(row["person_id"]).upper()
        existing = self.get_management_item(person_id)
        payload = {
            "person_id": person_id,
            "summary": str(row.get("summary") or ""),
            "description": str(row.get("description") or ""),
            "hit_count": int(
                row.get("hit_count") if row.get("hit_count") is not None else 0
            ),
            "enabled": bool(row.get("enabled", True)),
            "created_at": str(
                row.get("created_at") or (existing or {}).get("created_at") or now
            ),
            "updated_at": now,
        }
        return self.upsert_rows([payload])

    def hard_delete_persons(self, person_ids: list[str]) -> int:
        normalized = sorted(
            {person_id.upper() for person_id in person_ids if person_id}
        )
        if not normalized:
            return 0
        return self.delete_rows(self.id_filter("person_id", normalized))

    def _find_person_row(self, person_id: str) -> dict[str, Any]:
        return self._find_person_rows([person_id]).get(person_id, {})

    def _find_person_rows(self, person_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not person_ids:
            return {}
        rows = self.query_rows(
            self.id_filter("person_id", person_ids),
            [
                "person_id",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
            ],
            limit=len(person_ids),
        )
        return {str(row["person_id"]): dict(row) for row in rows}
