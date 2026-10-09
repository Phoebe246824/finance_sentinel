"""
Sentinel 舆情分析系统 — 自适应任务模板

根据事件类别和影响严重度动态选择提示词，实现：
- 类别自适应：不同领域使用不同的分析维度和输出模板
- 严重度自适应：根据影响程度动态调整时间范围
"""

from crewai import Agent, Task

from sentinel.config import PromptTemplate, get_profile_config, render_prompt
from sentinel.config.profile import LoadedDashboardPromptPair
from sentinel.trend_prediction.classification_taxonomy import (
    SEVERITY_TO_TIME_RANGES,
)
from sentinel.trend_prediction.classifier import EventClassifier


def _category_name(classifier: EventClassifier, category: str) -> str:
    if category == "general":
        return "通用"
    return classifier.get_category_name(category)


def _resolve_task_prompt(
    category: str,
    confidence: float,
    prompt_category: str | None,
) -> tuple[LoadedDashboardPromptPair, str, float]:
    profile = get_profile_config()
    resolved_category, prompt_pair = profile.prompts.dashboard.resolve(
        prompt_category or category
    )
    if prompt_category is not None or resolved_category == category:
        return prompt_pair, category, confidence
    return prompt_pair, "general", 1.0


def build_intent_analysis_prompt(
    *,
    event_text: str,
    classifier: EventClassifier,
    category: str,
    confidence: float,
    template: PromptTemplate,
) -> str:
    return render_prompt(
        template,
        category_name=_category_name(classifier, category),
        category_confidence=f"{confidence:.0%}",
        event_text=event_text,
    )


def build_trend_prediction_prompt(
    *,
    event_text: str,
    intent_analysis: str,
    classifier: EventClassifier,
    category: str,
    confidence: float,
    severity: str | None = None,
    severity_confidence: float = 0.0,
    template: PromptTemplate,
) -> str:
    severity_name = classifier.get_severity_name(severity) if severity else "未知"
    time_ranges = SEVERITY_TO_TIME_RANGES.get(
        severity or "moderate",
        SEVERITY_TO_TIME_RANGES["moderate"],
    )
    return render_prompt(
        template,
        category_name=_category_name(classifier, category),
        category_confidence=f"{confidence:.0%}",
        severity_name=severity_name,
        severity_confidence=f"{severity_confidence:.0%}",
        short_term=time_ranges["short_term"],
        medium_term=time_ranges["medium_term"],
        long_term=time_ranges["long_term"],
        event_text=event_text,
        intent_analysis=intent_analysis,
    )


def get_intent_analysis_task(
    event_text: str,
    classifier: EventClassifier,
    category: str,
    confidence: float,
    agent: Agent,
    prompt_category: str | None = None,
) -> Task:
    """
    创建意图分析任务，使用类别自适应提示词。

    Args:
        event_text: 事件文本
        classifier: 事件分类器实例
        category: 事件类别
        confidence: 分类置信度
        agent: CrewAI Agent（由调用方创建）
        prompt_category: 提示词类别；不传时与事件类别一致

    Returns:
        Task: CrewAI 意图分析任务
    """
    prompt_pair, render_category, render_confidence = _resolve_task_prompt(
        category,
        confidence,
        prompt_category,
    )
    description = build_intent_analysis_prompt(
        event_text=event_text,
        classifier=classifier,
        category=render_category,
        confidence=render_confidence,
        template=prompt_pair.intent_analysis,
    )

    return Task(
        name="意图分析",
        description=description,
        agent=agent,
        expected_output="一个完整的意图分析报告，包含上述所有维度的分析结果。",
    )


def get_trend_prediction_task(
    event_text: str,
    intent_task: Task,
    classifier: EventClassifier,
    category: str,
    confidence: float,
    agent: Agent,
    severity: str | None = None,
    severity_confidence: float = 0.0,
    prompt_category: str | None = None,
) -> Task:
    """
    创建趋势预测任务，使用类别自适应和严重度自适应提示词。

    Args:
        event_text: 事件文本
        intent_task: 意图分析任务（作为上下文）
        classifier: 事件分类器实例
        category: 事件类别
        confidence: 分类置信度
        agent: CrewAI Agent（由调用方创建）
        severity: 事件严重度
        severity_confidence: 严重度置信度
        prompt_category: 提示词类别；不传时与事件类别一致

    Returns:
        Task: CrewAI 趋势预测任务
    """
    prompt_pair, render_category, render_confidence = _resolve_task_prompt(
        category,
        confidence,
        prompt_category,
    )
    description = build_trend_prediction_prompt(
        event_text=event_text,
        intent_analysis="请参考上一任务的意图分析结果。",
        classifier=classifier,
        category=render_category,
        confidence=render_confidence,
        severity=severity,
        severity_confidence=severity_confidence,
        template=prompt_pair.trend_prediction,
    )

    return Task(
        name="趋势预测",
        description=description,
        agent=agent,
        expected_output="一个完整的趋势预测报告，包含上述所有维度的分析结果。",
        context=[intent_task],
    )
