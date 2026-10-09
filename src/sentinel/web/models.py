"""Web API 的共享请求/响应数据模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, StrictBool, field_validator


class TrendReportPayload(BaseModel):
    category_name: str = ""
    category_confidence: float = 0.0
    severity_name: str = ""
    severity_confidence: float = 0.0
    intent_analysis: str = ""
    trend_prediction: str = ""


class GraphSummaryPayload(BaseModel):
    success: bool | None = None
    entities_extracted: int = 0
    relations_created: int = 0
    group_id: str = ""
    fetched_count: int = 0
    eligible_count: int = 0
    batched_count: int = 0
    skipped_irrelevant_count: int = 0
    skipped_existing_count: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class SentinelEventPayload(BaseModel):
    event_id: str
    analysis_status: str = ""
    source: str = ""
    event_type: str = ""
    risk_level: str = "unassessed"
    risk_score: float = 0.0
    summary: str = ""
    raw_content: str = ""
    timestamp: str = ""
    key_entities: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str = ""
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    trend_report: TrendReportPayload = Field(default_factory=TrendReportPayload)
    graph_summary: GraphSummaryPayload = Field(default_factory=GraphSummaryPayload)


class PaginatedEventsPayload(BaseModel):
    items: list[SentinelEventPayload]
    total: int
    page: int
    page_size: int
    current: int
    size: int
    truncated: bool = False


class DashboardStatsPayload(BaseModel):
    total_events: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    unassessed_count: int = 0
    avg_processing_latency_ms: int | None = None
    events_per_minute: float | None = None
    graph_node_count: int | None = None
    graph_edge_count: int | None = None
    uptime_hours: float | None = None
    runtime_metrics_available: bool = True
    graph_metrics_available: bool = True
    data_truncated: bool = False


class DashboardOverviewPayload(BaseModel):
    stats: DashboardStatsPayload = Field(default_factory=DashboardStatsPayload)
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    source_distribution: dict[str, int] = Field(default_factory=dict)
    recent_events: list[SentinelEventPayload] = Field(default_factory=list)
    updated_at: str = ""
    truncated: bool = False


def _strip_required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


class BlacklistBatchDeleteItem(BaseModel):
    key: str = Field(
        min_length=1,
        max_length=512,
        description="Persisted blacklist key to hard delete.",
    )
    expected_updated_at: str = Field(
        min_length=1,
        max_length=64,
        description="Last known update timestamp used for optimistic locking.",
    )

    @field_validator("key", "expected_updated_at")
    @classmethod
    def strip_required_fields(cls, value: Any, info) -> str:
        return _strip_required_text(value, str(info.field_name))


class BlacklistPersonCreateItem(BaseModel):
    person_id: str = Field(
        min_length=1,
        max_length=128,
        description="Person ID used by blacklist matching.",
    )
    summary: str = Field(default="", max_length=1024, description="Operator summary.")
    description: str = Field(
        default="",
        max_length=4096,
        description="Operator-facing management note.",
    )
    enabled: StrictBool = Field(
        default=True,
        description="Whether this person ID participates in matching.",
    )

    @field_validator("person_id")
    @classmethod
    def strip_person_id(cls, value: Any) -> str:
        return _strip_required_text(value, "person_id")


class BlacklistPersonUpdateItem(BlacklistPersonCreateItem):
    old_key: str = Field(
        min_length=1,
        max_length=128,
        description="Persisted person ID before editing.",
    )
    expected_updated_at: str = Field(
        min_length=1,
        max_length=64,
        description="Last known update timestamp used for optimistic locking.",
    )

    @field_validator("old_key", "expected_updated_at")
    @classmethod
    def strip_update_keys(cls, value: Any, info) -> str:
        return _strip_required_text(value, str(info.field_name))


class BlacklistKeywordCreateItem(BaseModel):
    keyword: str = Field(
        min_length=1,
        max_length=512,
        description="Keyword text used by blacklist matching.",
    )
    summary: str = Field(default="", max_length=1024, description="Operator summary.")
    description: str = Field(
        default="",
        max_length=4096,
        description="Operator-facing management note.",
    )
    enabled: StrictBool = Field(
        default=True,
        description="Whether this keyword participates in matching.",
    )

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, value: Any) -> str:
        return _strip_required_text(value, "keyword")


class BlacklistKeywordUpdateItem(BlacklistKeywordCreateItem):
    old_key: str = Field(
        min_length=1,
        max_length=512,
        description="Persisted keyword before editing.",
    )
    expected_updated_at: str = Field(
        min_length=1,
        max_length=64,
        description="Last known update timestamp used for optimistic locking.",
    )

    @field_validator("old_key", "expected_updated_at")
    @classmethod
    def strip_update_keys(cls, value: Any, info) -> str:
        return _strip_required_text(value, str(info.field_name))


class BlacklistPersonBatchPayload(BaseModel):
    created: list[BlacklistPersonCreateItem] = Field(
        default_factory=list,
        description="New person rows to create.",
    )
    updated: list[BlacklistPersonUpdateItem] = Field(
        default_factory=list,
        description="Existing person rows to update.",
    )
    deleted: list[BlacklistBatchDeleteItem] = Field(
        default_factory=list,
        description="Existing person rows to hard delete.",
    )


class BlacklistKeywordBatchPayload(BaseModel):
    created: list[BlacklistKeywordCreateItem] = Field(
        default_factory=list,
        description="New keyword rows to create.",
    )
    updated: list[BlacklistKeywordUpdateItem] = Field(
        default_factory=list,
        description="Existing keyword rows to update.",
    )
    deleted: list[BlacklistBatchDeleteItem] = Field(
        default_factory=list,
        description="Existing keyword rows to hard delete.",
    )


class BlacklistEventCreatePayload(BaseModel):
    sample_id: str = Field(
        min_length=1,
        max_length=128,
        description="Typical event ID used by management and matching records.",
    )
    summary: str = Field(
        min_length=1,
        max_length=2048,
        description="Text embedded for typical event similarity matching.",
    )
    description: str = Field(
        default="",
        max_length=8192,
        description="Operator-facing management note.",
    )
    enabled: StrictBool = Field(
        default=True,
        description="Whether this typical event participates in matching.",
    )


class BlacklistEventUpdatePayload(BlacklistEventCreatePayload):
    expected_updated_at: str = Field(
        min_length=1,
        max_length=64,
        description="Last known update timestamp used for optimistic locking.",
    )


class BlacklistEnabledPayload(BaseModel):
    enabled: StrictBool = Field(description="Desired enabled state.")
    expected_updated_at: str = Field(
        min_length=1,
        max_length=64,
        description="Last known update timestamp used for optimistic locking.",
    )
