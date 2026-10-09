"""Risk evaluation stage helpers."""

from json import JSONDecodeError
from typing import Any

import httpx

from sentinel.config import SentinelSettings, get_profile_config, render_prompt
from sentinel.config.profile import PromptTemplate, RiskProfileConfig
from sentinel.models import NormalizedEvent, RiskLevel
from sentinel.pipeline.llm_json import generate_pipeline_json
from sentinel.ragflow.client import RagflowApiError, ragflow_error_summary
from sentinel.ragflow.context import (
    append_knowledge_context,
    format_knowledge_for_prompt,
    retrieve_event_knowledge,
)
from sentinel.utils.logging import get_logger, print_error


def risk_dimension_text(risk_profile: RiskProfileConfig) -> str:
    return "；".join(
        f"{name}: {description}"
        for name, description in risk_profile.dimensions.items()
    )


def risk_output_schema(risk_profile: RiskProfileConfig) -> str:
    score_fields = ",".join(f"{name}:number" for name in risk_profile.dimensions)
    reasoning_fields = ",".join(f"{name}:string" for name in risk_profile.dimensions)
    return (
        "Return strict JSON with this shape: {"
        f"dimension_scores:{{{score_fields}}}, "
        f"dimension_reasoning:{{{reasoning_fields}}}, "
        "history_context_analysis:{used_context:boolean, "
        "matched_evidence:list[string], relevance:string, score_reason:string}, "
        "risk_score:number, risk_level:string, reasoning:string, "
        "recommended_actions:list[string]}. "
        "risk_level must be high, medium, or low; all dimension scores and "
        "risk_score must be numbers from 0.0 to 1.0."
    )


def build_risk_prompt(
    *,
    template: PromptTemplate,
    risk_profile: RiskProfileConfig,
    event: NormalizedEvent,
    related_events: str,
) -> str:
    return render_prompt(
        template,
        risk_dimensions=risk_dimension_text(risk_profile),
        event_type=event.event_type,
        event_summary=event.summary,
        key_entities=event.structured_data,
        event_time=event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        source=event.source,
        related_events=related_events,
        output_schema=risk_output_schema(risk_profile),
    )


def normalize_context_text(text: str) -> str:
    return " ".join(text.split())


def is_current_event_text(candidate: str, current_event_text: str | None) -> bool:
    if not current_event_text:
        return False
    candidate_norm = normalize_context_text(candidate)
    current_norm = normalize_context_text(current_event_text)
    if not candidate_norm or not current_norm:
        return False
    return candidate_norm == current_norm or current_norm in candidate_norm


def build_related_events_context(
    results: dict | None,
    *,
    current_event_text: str | None = None,
) -> str:
    reranked_edges = results.get("reranked_edges", []) if results else []
    reranked_episodes = results.get("reranked_episodes", []) if results else []
    related_parts: list[str] = []
    for item in reranked_edges:
        text = (
            item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        )
        if text and not is_current_event_text(text, current_event_text):
            related_parts.append(f"[edge] {text}")
    for item in reranked_episodes:
        text = (
            item.get("text")
            if isinstance(item, dict)
            else getattr(item, "content", None)
        )
        if text and not is_current_event_text(text, current_event_text):
            related_parts.append(f"[episode] {text}")
    return "\n".join(related_parts)


def normalize_dimension_scores(
    value: Any,
    risk_profile: RiskProfileConfig,
) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    scores: dict[str, float] = {}
    for key in risk_profile.dimensions:
        raw_score = value.get(key, 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        scores[key] = max(0.0, min(1.0, score))
    return scores


def normalize_string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if raw is None else str(raw) for key, raw in value.items()}


def normalize_history_context_analysis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "used_context": False,
            "matched_evidence": [],
            "relevance": "",
            "score_reason": "",
        }
    matched_evidence = value.get("matched_evidence", [])
    if not isinstance(matched_evidence, list):
        matched_evidence = [str(matched_evidence)]
    return {
        "used_context": bool(value.get("used_context", False)),
        "matched_evidence": [str(item) for item in matched_evidence],
        "relevance": ""
        if value.get("relevance") is None
        else str(value.get("relevance")),
        "score_reason": ""
        if value.get("score_reason") is None
        else str(value.get("score_reason")),
    }


async def build_ragflow_enriched_context(
    app_settings: SentinelSettings,
    event: NormalizedEvent,
    results: dict | None,
    *,
    stage: str,
) -> str:
    logger = get_logger("main.risk_evaluation")
    related_events = build_related_events_context(
        results,
        current_event_text=event.raw_content,
    )
    try:
        ragflow_result = await retrieve_event_knowledge(
            app_settings, event, stage=stage
        )
    except (httpx.HTTPError, JSONDecodeError, RagflowApiError) as exc:
        if not app_settings.ragflow_fail_open:
            raise
        logger.warning(
            "RAGFlow enrichment failed for %s; continuing with graph context: %s",
            stage,
            ragflow_error_summary(exc),
        )
        return related_events
    knowledge_text = format_knowledge_for_prompt(
        ragflow_result,
        max_chars=app_settings.ragflow_max_context_chars,
    )
    return append_knowledge_context(related_events, knowledge_text)


def parse_risk_level(raw_level: str | RiskLevel | None) -> RiskLevel:
    if isinstance(raw_level, RiskLevel):
        return raw_level
    if raw_level is None:
        return RiskLevel.MEDIUM
    try:
        return RiskLevel(raw_level.strip().lower())
    except ValueError:
        return RiskLevel.MEDIUM


async def evaluate_risk(
    app_settings: SentinelSettings,
    event: NormalizedEvent,
    results: dict | None = None,
) -> dict:
    logger = get_logger("main.risk_evaluation")

    related_events = await build_ragflow_enriched_context(
        app_settings,
        event,
        results,
        stage="risk_first",
    )
    profile = get_profile_config()
    prompt = build_risk_prompt(
        template=profile.prompts.pipeline.risk_first,
        risk_profile=profile.risk,
        event=event,
        related_events=related_events,
    )
    try:
        result_dict = await generate_pipeline_json(
            app_settings,
            prompt=prompt,
            temperature=0.1,
        )

        risk_score = result_dict.get("risk_score", 0.5)
        if isinstance(risk_score, str):
            risk_score = float(risk_score)
        dimension_scores = normalize_dimension_scores(
            result_dict.get("dimension_scores", {}),
            profile.risk,
        )
        dimension_reasoning = normalize_string_dict(
            result_dict.get("dimension_reasoning", {})
        )
        history_context_analysis = normalize_history_context_analysis(
            result_dict.get("history_context_analysis", {})
        )

        final_result = {
            "risk_level": parse_risk_level(result_dict.get("risk_level")),
            "risk_score": risk_score,
            "reasoning": result_dict.get("reasoning", ""),
            "dimension_scores": dimension_scores,
            "dimension_reasoning": dimension_reasoning,
            "history_context_analysis": history_context_analysis,
            "recommended_actions": result_dict.get("recommended_actions", []),
        }
        return final_result

    except Exception as e:
        print_error("风险评估结果解析失败")
        logger.error("parse risk evaluation result failed: %s", e, exc_info=True)
        return {
            "risk_level": RiskLevel.MEDIUM,
            "risk_score": 0.5,
            "reasoning": "自动评估",
        }


async def second_evaluate_risk(
    app_settings: SentinelSettings,
    event: NormalizedEvent,
    results: dict,
) -> dict:
    logger = get_logger("main.risk_evaluation")

    related_events = await build_ragflow_enriched_context(
        app_settings,
        event,
        results,
        stage="risk_second",
    )
    profile = get_profile_config()
    prompt = build_risk_prompt(
        template=profile.prompts.pipeline.risk_second,
        risk_profile=profile.risk,
        event=event,
        related_events=related_events,
    )
    try:
        result_dict = await generate_pipeline_json(
            app_settings,
            prompt=prompt,
            temperature=0.1,
        )

        risk_score = result_dict.get("risk_score", 0.5)
        if isinstance(risk_score, str):
            risk_score = float(risk_score)
        dimension_scores = normalize_dimension_scores(
            result_dict.get("dimension_scores", {}),
            profile.risk,
        )
        dimension_reasoning = normalize_string_dict(
            result_dict.get("dimension_reasoning", {})
        )
        history_context_analysis = normalize_history_context_analysis(
            result_dict.get("history_context_analysis", {})
        )

        final_result = {
            "risk_level": parse_risk_level(result_dict.get("risk_level")),
            "risk_score": risk_score,
            "reasoning": result_dict.get("reasoning", ""),
            "dimension_scores": dimension_scores,
            "dimension_reasoning": dimension_reasoning,
            "history_context_analysis": history_context_analysis,
            "recommended_actions": result_dict.get("recommended_actions", []),
        }
        return final_result
    except Exception as e:
        print_error("风险评估结果解析失败")
        logger.error("parse second risk evaluation result failed: %s", e, exc_info=True)
        return {
            "risk_level": RiskLevel.MEDIUM,
            "risk_score": 0.5,
            "reasoning": "自动评估",
        }
