"""Serialization helpers for converting pipeline results to web payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sentinel.web.models import (
    GraphSummaryPayload,
    SentinelEventPayload,
    TrendReportPayload,
)

if TYPE_CHECKING:
    from sentinel.main import PipelineRunResult


def pipeline_result_to_event_payload(
    result: "PipelineRunResult",
) -> SentinelEventPayload:
    event = result.normalized_event
    trend = _trend_report_payload(result)
    key_entities = _normalize_key_entities(event.structured_data)
    event_type = event.event_type or ("未触发" if not result.entered_flow else "")
    summary = event.summary or result.message or event.raw_content[:200]
    reasoning = event.reasoning or result.message
    if result.status == "stashed" or not result.entered_flow:
        risk_level = "unassessed"
        risk_score = 0.0
        dimension_scores: dict[str, float] = {}
    else:
        risk_level = (
            event.risk_level.value
            if hasattr(event.risk_level, "value")
            else str(event.risk_level)
        )
        risk_score = float(event.risk_score)
        dimension_scores = dict(getattr(event, "dimension_scores", {}) or {})
        if not dimension_scores:
            dimension_scores = {"risk": risk_score}
    return SentinelEventPayload(
        event_id=event.event_id,
        analysis_status=result.status,
        source=event.source.value
        if hasattr(event.source, "value")
        else str(event.source),
        event_type=event_type,
        risk_level=risk_level,
        risk_score=risk_score,
        summary=summary,
        raw_content=event.raw_content,
        timestamp=event.timestamp.isoformat(),
        key_entities=key_entities,
        reasoning=reasoning,
        dimension_scores=dimension_scores,
        trend_report=trend,
        graph_summary=_graph_summary_payload(result.graph_result),
    )


def row_to_event_payload(row: dict[str, Any]) -> SentinelEventPayload:
    analysis_status = str(row.get("analysis_status") or "")
    risk_level = str(row.get("risk_level") or "")
    risk_score = float(row.get("risk_score") or 0.0)
    dimension_scores = _json_dict(row.get("dimension_scores_json"), {})
    if analysis_status == "stashed":
        risk_level = "unassessed"
        risk_score = 0.0
        dimension_scores = {}
    elif not risk_level:
        risk_level = "unassessed"
    return SentinelEventPayload(
        event_id=str(row.get("event_id") or ""),
        analysis_status=analysis_status,
        source=str(row.get("source") or ""),
        event_type=str(row.get("event_type") or ""),
        risk_level=risk_level,
        risk_score=risk_score,
        summary=str(row.get("summary") or ""),
        raw_content=str(row.get("raw_content") or ""),
        timestamp=str(row.get("event_timestamp") or row.get("created_at") or ""),
        key_entities=_json_list(row.get("key_entities_json"), []),
        reasoning=str(row.get("reasoning") or row.get("pipeline_message") or ""),
        dimension_scores=dimension_scores,
        trend_report=TrendReportPayload(**_json_dict(row.get("trend_report_json"), {})),
        graph_summary=_graph_summary_from_stored_json(row.get("graph_summary_json")),
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _graph_summary_payload(value: Any) -> GraphSummaryPayload:
    if not isinstance(value, dict):
        return GraphSummaryPayload()

    raw_success = value.get("success")
    return GraphSummaryPayload(
        success=raw_success if isinstance(raw_success, bool) else None,
        entities_extracted=_safe_int(value.get("entities_extracted")),
        relations_created=_safe_int(value.get("relations_created")),
        group_id=str(value.get("group_id") or ""),
        fetched_count=_safe_int(value.get("fetched_count")),
        eligible_count=_safe_int(value.get("eligible_count")),
        batched_count=_safe_int(value.get("batched_count")),
        skipped_irrelevant_count=_safe_int(value.get("skipped_irrelevant_count")),
        skipped_existing_count=_safe_int(value.get("skipped_existing_count")),
        raw=_filtered_graph_summary_raw(value),
    )


def _graph_summary_from_stored_json(value: Any) -> GraphSummaryPayload:
    payload = GraphSummaryPayload(**_json_dict(value, {}))
    payload.raw = _filtered_graph_summary_raw(payload.raw)
    return payload


def _filtered_graph_summary_raw(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if key != "batch_results"}


def _trend_report_payload(result: "PipelineRunResult") -> TrendReportPayload:
    report = result.trend_report
    if report is None:
        return TrendReportPayload(
            category_name="未触发",
            category_confidence=0.0,
            severity_name="未触发",
            severity_confidence=0.0,
            intent_analysis="未触发趋势预测",
            trend_prediction="未触发趋势预测",
        )
    return TrendReportPayload(
        category_name=report.category_name,
        category_confidence=float(report.category_confidence),
        severity_name=report.severity_name,
        severity_confidence=float(report.severity_confidence),
        intent_analysis=report.raw_report,
        trend_prediction=report.raw_report,
    )


def dumps_json(value: Any, max_chars: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    if isinstance(value, dict):
        trimmed: dict[str, Any] = {}
        for key, item in value.items():
            candidate = {**trimmed, key: item}
            candidate_text = json.dumps(candidate, ensure_ascii=False, default=str)
            if len(candidate_text) > max_chars:
                break
            trimmed[key] = item
        return json.dumps(trimmed, ensure_ascii=False, default=str)
    if isinstance(value, list):
        trimmed_list: list[Any] = []
        for item in value:
            candidate = [*trimmed_list, item]
            candidate_text = json.dumps(candidate, ensure_ascii=False, default=str)
            if len(candidate_text) > max_chars:
                break
            trimmed_list.append(item)
        return json.dumps(trimmed_list, ensure_ascii=False, default=str)
    return json.dumps(str(value)[:max_chars], ensure_ascii=False, default=str)


def _json_dict(value: Any, default: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return default
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, dict) else default


def _json_list(value: Any, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if not value:
        return default
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, list) else default


def _normalize_key_entities(structured_data: dict[str, Any]) -> list[dict[str, Any]]:
    if "key_entities" in structured_data:
        key_entities = structured_data.get("key_entities", [])
        if isinstance(key_entities, list):
            return [item for item in key_entities if isinstance(item, dict)]

    normalized: list[dict[str, Any]] = []
    for key, value in structured_data.items():
        entity_type = str(key).upper()
        if isinstance(value, str) and value.strip():
            normalized.append({"name": value, "type": entity_type})
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    normalized.append({"name": item, "type": entity_type})
    return normalized
