"""Trend prediction orchestration and prompt assembly service."""

from dataclasses import dataclass
from json import JSONDecodeError

import httpx

from sentinel.config import SentinelSettings, get_profile_config, get_settings
from sentinel.models import NormalizedEvent
from sentinel.ragflow.client import RagflowApiError, ragflow_error_summary
from sentinel.ragflow.context import (
    format_knowledge_for_prompt,
    knowledge_section_for_prompt,
    retrieve_event_knowledge,
)
from sentinel.trend_prediction.classification_taxonomy import SEVERITY_NAMES
from sentinel.trend_prediction.classifier import EventClassifier
from sentinel.trend_prediction.task_templates import (
    build_intent_analysis_prompt,
    build_trend_prediction_prompt,
)
from sentinel.utils.litellm_text import generate_text
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TrendPredictionConfig:
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.3
    verbose: bool = False
    use_rerank: bool = True
    zero_shot: bool = False
    force_category: str | None = None
    force_category_confidence: float = 1.0
    force_severity: str | None = None
    force_severity_confidence: float = 1.0
    use_adaptive_prompts: bool = True
    include_context: bool = False
    fixed_horizon_severity: str | None = None
    event_metadata_text: str = ""


@dataclass(frozen=True, slots=True)
class TrendReport:
    raw_report: str
    category: str
    category_name: str
    category_confidence: float
    severity: str
    severity_name: str
    severity_confidence: float
    event_text: str
    context_text: str
    model: str | None
    temperature: float


def _build_event_description(event_text: str, context_text: str) -> str:
    if not context_text:
        return f"事件描述: {event_text}"
    return f"上下文信息: {context_text}\n事件描述: {event_text}"


def _prepend_metadata(event_text: str, metadata_text: str) -> str:
    if not metadata_text.strip():
        return event_text
    return f"{metadata_text.strip()}\n{event_text}"


async def _dashboard_knowledge_section(
    settings: SentinelSettings,
    event: NormalizedEvent | None,
) -> str:
    if event is None:
        return ""
    try:
        ragflow_result = await retrieve_event_knowledge(
            settings,
            event,
            stage="dashboard",
        )
    except (httpx.HTTPError, JSONDecodeError, RagflowApiError) as exc:
        if not settings.ragflow_fail_open:
            raise
        logger.warning(
            "RAGFlow dashboard enrichment failed; continuing without it: %s",
            ragflow_error_summary(exc),
        )
        return ""
    knowledge_text = format_knowledge_for_prompt(
        ragflow_result,
        max_chars=settings.ragflow_max_context_chars,
    )
    return knowledge_section_for_prompt(
        knowledge_text,
        header="RAGFlow external knowledge reference:",
    )


def _category_name(classifier: EventClassifier, category: str) -> str:
    if category == "general":
        return "通用"
    return classifier.get_category_name(category)


async def run_trend_prediction(
    config: TrendPredictionConfig,
    event_text: str,
    context_text: str = "",
    app_settings: SentinelSettings | None = None,
    source_event: NormalizedEvent | None = None,
) -> TrendReport:
    settings = app_settings or get_settings()
    if config.zero_shot:
        category = "general"
        confidence = 1.0
        severity = "moderate"
        severity_confidence = 1.0
        category_name = "通用"
        severity_name = SEVERITY_NAMES[severity]
    else:
        classifier = EventClassifier(
            use_rerank=config.use_rerank,
            app_settings=settings,
        )
        if config.force_category is not None:
            category = config.force_category
            confidence = config.force_category_confidence
            severity = config.force_severity or "moderate"
            severity_confidence = (
                config.force_severity_confidence
                if config.force_severity is not None
                else 1.0
            )
        else:
            (
                category,
                confidence,
                severity,
                severity_confidence,
            ) = await classifier.classify_with_severity(event_text)
            if config.force_severity is not None:
                severity = config.force_severity
                severity_confidence = config.force_severity_confidence

        profile = get_profile_config()
        prompt_category = category if config.use_adaptive_prompts else "general"
        resolved_category, prompt_pair = profile.prompts.dashboard.resolve(
            prompt_category
        )
        if config.use_adaptive_prompts and resolved_category != category:
            category = "general"
            confidence = 1.0
        category_name = _category_name(classifier, category)
        severity_name = classifier.get_severity_name(severity)

    prompt_severity = config.fixed_horizon_severity or severity
    selected_context = context_text if config.include_context else ""
    knowledge_section = (
        ""
        if config.zero_shot
        else await _dashboard_knowledge_section(settings, source_event)
    )
    if knowledge_section:
        selected_context = (
            f"{selected_context}\n\n{knowledge_section}".strip()
            if selected_context
            else knowledge_section.strip()
        )
    event_with_metadata = _prepend_metadata(event_text, config.event_metadata_text)
    event_description = _build_event_description(event_with_metadata, selected_context)

    model = config.model or settings.llm_model
    api_key = config.api_key or settings.require_llm_api_key()
    base_url = config.base_url or settings.llm_base_url

    if config.zero_shot:
        trend_prompt = (
            "你是一位事件趋势预测专家。只依据下列事发当时信息，预测该事件"
            "在短期到中期内最可能的发展走向；不要假设已知后续结局。\n\n"
            f"{event_description}"
        )
        raw_report = await generate_text(
            settings,
            prompt=trend_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=config.temperature,
        )
    else:
        intent_prompt = build_intent_analysis_prompt(
            event_text=event_description,
            classifier=classifier,
            category=category,
            confidence=confidence,
            template=prompt_pair.intent_analysis,
        )
        intent_analysis = await generate_text(
            settings,
            prompt=intent_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=config.temperature,
        )
        trend_prompt = build_trend_prediction_prompt(
            event_text=event_description,
            intent_analysis=intent_analysis,
            classifier=classifier,
            category=category,
            confidence=confidence,
            severity=prompt_severity,
            severity_confidence=severity_confidence,
            template=prompt_pair.trend_prediction,
        )
        raw_report = await generate_text(
            settings,
            prompt=trend_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=config.temperature,
        )

    return TrendReport(
        raw_report=raw_report,
        category=category,
        category_name=category_name,
        category_confidence=confidence,
        severity=severity,
        severity_name=severity_name,
        severity_confidence=severity_confidence,
        event_text=event_text,
        context_text=selected_context,
        model=model,
        temperature=config.temperature,
    )
