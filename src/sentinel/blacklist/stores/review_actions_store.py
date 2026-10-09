"""黑名单审核动作的 Milvus 存取。"""

import uuid
from typing import Any

from pymilvus import DataType

from sentinel.blacklist.stores.base import FieldSpec, MilvusBaseStore
from sentinel.utils.logging import get_logger

REVIEW_ACTIONS_QUERY_LIMIT = 10000

logger = get_logger(__name__)


class ReviewActionsStore(MilvusBaseStore):
    collection_name = "review_actions"
    primary_field = "action_id"

    def fields(self) -> list[FieldSpec]:
        return [
            FieldSpec("action_id", DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSpec("event_id", DataType.VARCHAR, max_length=128),
            FieldSpec("action_type", DataType.VARCHAR, max_length=128),
            FieldSpec("comment", DataType.VARCHAR, max_length=4096),
            FieldSpec("created_at", DataType.VARCHAR, max_length=64),
        ]

    def create(self, event_id: str, action_type: str, comment: str) -> dict[str, Any]:
        row = {
            "action_id": uuid.uuid4().hex,
            "event_id": event_id,
            "action_type": action_type,
            "comment": comment,
            "created_at": self.now_iso(),
        }
        self.upsert_rows([row])
        return row

    def list_for_event(self, event_id: str) -> list[dict[str, Any]]:
        rows = self.query_rows(
            f"event_id == {self.quote(event_id)}",
            ["action_id", "event_id", "action_type", "comment", "created_at"],
            limit=10000,
        )
        return sorted(
            rows,
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

    def list_recent(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.query_rows(
            'action_id != ""',
            ["action_id", "event_id", "action_type", "comment", "created_at"],
            limit=REVIEW_ACTIONS_QUERY_LIMIT,
        )
        if len(rows) >= REVIEW_ACTIONS_QUERY_LIMIT:
            logger.warning(
                "Milvus review actions list reached query cap=%d; totals may be truncated",
                REVIEW_ACTIONS_QUERY_LIMIT,
            )
        return sorted(
            rows,
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )[:limit]
