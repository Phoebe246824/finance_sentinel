"""分析结果的 Milvus 持久化仓库。"""

from __future__ import annotations

from datetime import datetime

from sentinel.blacklist.stores.events_store import EventsStore
from sentinel.web.models import (
    DashboardOverviewPayload,
    DashboardStatsPayload,
    PaginatedEventsPayload,
    SentinelEventPayload,
)
from sentinel.web.serialization import dumps_json, row_to_event_payload

DEFAULT_ANALYSIS_ROW_LIMIT = 5000


class EventResultRepository:
    def __init__(
        self,
        events_store: EventsStore,
        *,
        row_limit: int = DEFAULT_ANALYSIS_ROW_LIMIT,
    ) -> None:
        self._events_store = events_store
        self._row_limit = row_limit

    async def save_result(
        self,
        event: SentinelEventPayload,
        status: str,
        settings=None,
    ) -> None:
        del settings
        await self._events_store.update_analysis_result(
            event.event_id,
            self.payload_to_store_fields(event, status=status),
        )

    def get_result(self, event_id: str) -> SentinelEventPayload | None:
        row = self._events_store.get_analysis_row(event_id)
        if row is None:
            return None
        if str(row.get("analysis_status") or "") not in {"stashed", "analyzed"}:
            return None
        return row_to_event_payload(row)

    def list_results(
        self,
        *,
        page: int,
        page_size: int,
        source: str | None = None,
        risk_level: str | None = None,
        event_type: str | None = None,
        keyword: str | None = None,
    ) -> PaginatedEventsPayload:
        output_fields = self._events_store.WEB_OUTPUT_FIELDS if keyword else None
        rows, truncated = self._list_analysis_rows(
            source=source,
            risk_level=risk_level,
            event_type=event_type,
            output_fields=output_fields,
        )
        events = [row_to_event_payload(row) for row in rows]
        if keyword:
            lowered = keyword.lower()
            events = [
                event
                for event in events
                if lowered in event.event_id.lower()
                or lowered in event.raw_content.lower()
                or lowered in event.summary.lower()
            ]
        start = (page - 1) * page_size
        end = start + page_size
        return PaginatedEventsPayload(
            items=events[start:end],
            total=len(events),
            page=page,
            page_size=page_size,
            current=page,
            size=page_size,
            truncated=truncated,
        )

    def overview(self) -> DashboardOverviewPayload:
        rows, truncated = self._list_analysis_rows()
        all_events = [row_to_event_payload(row) for row in rows]
        recent_events = all_events[:20]
        risk_distribution = {"high": 0, "medium": 0, "low": 0}
        source_distribution: dict[str, int] = {}
        unassessed_count = 0
        for event in all_events:
            if event.risk_level in risk_distribution:
                risk_distribution[event.risk_level] += 1
            else:
                unassessed_count += 1
            source_distribution[event.source] = (
                source_distribution.get(event.source, 0) + 1
            )
        return DashboardOverviewPayload(
            stats=DashboardStatsPayload(
                total_events=len(all_events),
                high_risk_count=risk_distribution["high"],
                medium_risk_count=risk_distribution["medium"],
                low_risk_count=risk_distribution["low"],
                unassessed_count=unassessed_count,
                data_truncated=truncated,
            ),
            risk_distribution=risk_distribution,
            source_distribution=source_distribution,
            recent_events=recent_events,
            updated_at=datetime.now().isoformat(timespec="seconds"),
            truncated=truncated,
        )

    def _list_analysis_rows(
        self,
        *,
        source: str | None = None,
        risk_level: str | None = None,
        event_type: str | None = None,
        output_fields: list[str] | None = None,
    ) -> tuple[list[dict], bool]:
        probe_limit = self._row_limit + 1
        rows = self._events_store.list_analysis_rows(
            limit=probe_limit,
            source=source,
            risk_level=risk_level,
            event_type=event_type,
            output_fields=output_fields,
        )
        truncated = len(rows) > self._row_limit
        if truncated:
            rows = rows[: self._row_limit]
        return rows, truncated

    @staticmethod
    def payload_to_store_fields(
        event: SentinelEventPayload,
        *,
        status: str = "analyzed",
    ) -> dict[str, object]:
        return {
            "analysis_status": status,
            "analyzed_at": datetime.now().isoformat(timespec="seconds"),
            "source": _truncate_utf8(event.source, 32),
            "event_type": _truncate_utf8(event.event_type, 128),
            "risk_level": _truncate_utf8(event.risk_level, 16),
            "risk_score": float(event.risk_score),
            "summary": _truncate_utf8(event.summary, 4096),
            "reasoning": _truncate_utf8(event.reasoning, 8192),
            "title": "",
            "event_timestamp": _truncate_utf8(event.timestamp, 64),
            "key_entities_json": dumps_json(event.key_entities, 8192),
            "dimension_scores_json": dumps_json(event.dimension_scores, 4096),
            "trend_report_json": dumps_json(
                {
                    "category_name": _truncate_utf8(
                        event.trend_report.category_name, 256
                    ),
                    "category_confidence": float(
                        event.trend_report.category_confidence
                    ),
                    "severity_name": _truncate_utf8(
                        event.trend_report.severity_name, 256
                    ),
                    "severity_confidence": float(
                        event.trend_report.severity_confidence
                    ),
                    "intent_analysis": _truncate_utf8(
                        event.trend_report.intent_analysis, 7000
                    ),
                    "trend_prediction": _truncate_utf8(
                        event.trend_report.trend_prediction, 7000
                    ),
                },
                16384,
            ),
            "graph_summary_json": dumps_json(
                event.graph_summary.model_dump(),
                8192,
            ),
            "pipeline_message": _truncate_utf8(event.reasoning, 512),
        }


def _truncate_utf8(value: object, max_bytes: int) -> str:
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""
