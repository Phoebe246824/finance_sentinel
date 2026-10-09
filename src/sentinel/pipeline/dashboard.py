"""Dashboard/trend-prediction stage helpers."""

from sentinel.config import SentinelSettings, get_profile_config
from sentinel.config.profile import ProfileConfig
from sentinel.models import NormalizedEvent
from sentinel.trend_prediction.service import (
    TrendPredictionConfig,
    TrendReport,
    run_trend_prediction,
)
from sentinel.utils.logging import get_logger, print_info


def build_dashboard_context_text(results: dict | None) -> str:
    reranked_edges = results.get("reranked_edges", []) if results else []
    reranked_episodes = results.get("reranked_episodes", []) if results else []
    context_parts = []
    for item in reranked_edges:
        text = (
            item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        )
        if text:
            context_parts.append(f"[edge] {text}")
    for item in reranked_episodes:
        text = (
            item.get("text")
            if isinstance(item, dict)
            else getattr(item, "content", None)
        )
        if text:
            context_parts.append(f"[episode] {text}")
    return "\n".join(context_parts)


def build_event_metadata_text(
    event: NormalizedEvent,
    profile_config: ProfileConfig | None = None,
) -> str:
    analysis_target = (
        profile_config.dashboard.analysis_target
        if profile_config is not None
        else "General event impact and response."
    )
    return (
        f"事件类型: {event.event_type or '未知'}\n"
        f"风险等级: {event.risk_level.value}\n"
        f"风险分数: {event.risk_score:.2f}\n"
        f"风险理由: {event.reasoning or '无'}\n"
        f"分析目标: {analysis_target}"
    )


async def execute_dashboard(
    app_settings: SentinelSettings | None,
    normalized_event: NormalizedEvent,
    results: dict,
) -> TrendReport:
    logger = get_logger("main.dashboard")

    event = normalized_event
    profile = get_profile_config()
    context_text = build_dashboard_context_text(results)
    event_metadata = build_event_metadata_text(event, profile)
    report = await run_trend_prediction(
        TrendPredictionConfig(
            temperature=0.3,
            include_context=True,
            event_metadata_text=event_metadata,
            force_category=profile.dashboard.force_category,
            force_category_confidence=profile.dashboard.force_category_confidence,
        ),
        event.raw_content,
        context_text=context_text,
        app_settings=app_settings,
        source_event=event,
    )

    print_info(
        f"\n[dashboard] 事件分类: {report.category_name} "
        f"(置信度: {report.category_confidence:.0%})"
    )
    print_info(
        f"[dashboard] 影响严重度: {report.severity_name} "
        f"(置信度: {report.severity_confidence:.0%})"
    )
    print_info(
        f"[dashboard] 已选择 {report.category_name} 自适应提示词进行意图分析和趋势预测"
    )
    logger.info("analysis result:\n%s", report.raw_report)
    print_info("Dashboard 分析完成")
    return report
