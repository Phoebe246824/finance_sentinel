"""关键词黑名单的 Milvus 存取。"""

import hashlib
from typing import Any

from pymilvus import DataType

from sentinel.blacklist.stores.base import FieldSpec, MilvusBaseStore


class KeywordsStore(MilvusBaseStore):
    collection_name = "blacklist_keywords"
    primary_field = "keyword_id"
    MANAGEMENT_FIELDS = [
        "keyword_id",
        "keyword",
        "summary",
        "description",
        "hit_count",
        "enabled",
        "created_at",
        "updated_at",
    ]

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec("keyword_id", DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSpec("keyword", DataType.VARCHAR, max_length=512),
            FieldSpec("summary", DataType.VARCHAR, max_length=1024),
            FieldSpec("description", DataType.VARCHAR, max_length=4096),
            FieldSpec("hit_count", DataType.INT64),
            FieldSpec("enabled", DataType.BOOL),
            FieldSpec("created_at", DataType.VARCHAR, max_length=64),
            FieldSpec("updated_at", DataType.VARCHAR, max_length=64),
        ]

    async def query_keywords(self) -> list[str]:
        rows = self.query_rows(
            'keyword_id != "" and enabled == true',
            ["keyword", "updated_at"],
            limit=10000,
        )
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [str(row["keyword"]) for row in rows]

    async def append_keyword(
        self,
        keyword: str,
        summary: str = "",
        description: str = "",
    ) -> int:
        return await self.append_keywords(
            [keyword],
            summary=summary,
            description=description,
        )

    async def append_keywords(
        self,
        keywords: list[str],
        summary: str = "",
        description: str = "",
    ) -> int:
        unique_keywords = list(dict.fromkeys(keywords))
        if not unique_keywords:
            return 0

        now = self.now_iso()
        keyword_ids = {keyword: self.keyword_id(keyword) for keyword in unique_keywords}
        existing_rows = self._find_keyword_rows(list(keyword_ids.values()))
        rows = []
        for keyword, keyword_id in keyword_ids.items():
            existing = existing_rows.get(keyword_id, {})
            rows.append(
                {
                    "keyword_id": keyword_id,
                    "keyword": keyword,
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

    async def remove_keyword(self, keyword: str) -> bool:
        row = self._find_keyword_row(self.keyword_id(keyword))
        if not row:
            return False
        row.update({"enabled": False, "updated_at": self.now_iso()})
        return self.upsert_rows([row]) > 0

    async def get_keyword_stats(self) -> dict[str, float]:
        rows = self.query_rows(
            'keyword_id != "" and enabled == true',
            ["keyword", "hit_count"],
            limit=10000,
        )
        return {str(row["keyword"]): float(row.get("hit_count") or 1.0) for row in rows}

    def list_items(self) -> list[dict[str, Any]]:
        rows = self.query_rows(
            'keyword_id != "" and enabled == true',
            [
                "keyword_id",
                "keyword",
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
            {**row, "value": row["keyword"]}
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
        clauses = ['keyword_id != ""']
        if enabled is not None:
            clauses.append(f"enabled == {str(enabled).lower()}")
        if keyword:
            clauses.append(
                self.like_filter(["keyword", "summary", "description"], keyword)
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

    def get_management_item(self, keyword_id: str) -> dict[str, Any] | None:
        rows = self.query_rows(
            f"keyword_id == {self.quote(keyword_id)}",
            self.MANAGEMENT_FIELDS,
            limit=1,
        )
        return dict(rows[0]) if rows else None

    async def upsert_management_keyword(self, row: dict[str, Any]) -> int:
        now = self.now_iso()
        keyword = str(row["keyword"])
        keyword_id = self.keyword_id(keyword)
        existing = self.get_management_item(keyword_id)
        payload = {
            "keyword_id": keyword_id,
            "keyword": keyword,
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

    def hard_delete_keywords(self, keyword_ids: list[str]) -> int:
        normalized = sorted({keyword_id for keyword_id in keyword_ids if keyword_id})
        if not normalized:
            return 0
        return self.delete_rows(self.id_filter("keyword_id", normalized))

    def _find_keyword_row(self, keyword_id: str) -> dict[str, Any]:
        return self._find_keyword_rows([keyword_id]).get(keyword_id, {})

    def _find_keyword_rows(self, keyword_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not keyword_ids:
            return {}
        rows = self.query_rows(
            self.id_filter("keyword_id", keyword_ids),
            [
                "keyword_id",
                "keyword",
                "summary",
                "description",
                "hit_count",
                "enabled",
                "created_at",
            ],
            limit=len(keyword_ids),
        )
        return {str(row["keyword_id"]): dict(row) for row in rows}

    @staticmethod
    def keyword_id(keyword: str) -> str:
        return hashlib.sha256(keyword.encode("utf-8")).hexdigest()
