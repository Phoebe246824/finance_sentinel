"""
Sentinel 舆情分析系统 — 事件分类与严重度评估模块

基于 LiteLLM Rerank 的事件分类器，支持：
- 8 种事件类别分类（国际政治、科技、经济、社会/文化、公共卫生、能源、金融、公共安全）
- 4 级影响严重度评估（轻微、一般、严重、重大）
- 严重度到时间范围的动态映射
- 关键词匹配回退方案
"""

import logging

from sentinel.config import SentinelSettings, get_settings
from sentinel.trend_prediction.classification_taxonomy import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_KEYWORDS,
    CATEGORY_NAMES,
    SEVERITY_DESCRIPTIONS,
    SEVERITY_KEYWORDS,
    SEVERITY_NAMES,
    SEVERITY_TO_TIME_RANGES,
)
from sentinel.utils.litellm_rerank import rerank_scores

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# 合并分类的documents前缀
# ══════════════════════════════════════════════════════════════════

CATEGORY_DOC_PREFIX = "CATEGORY:"
SEVERITY_DOC_PREFIX = "SEVERITY:"


# ══════════════════════════════════════════════════════════════════
# Rerank 分类函数
# ══════════════════════════════════════════════════════════════════


async def _rerank_classify_combined(
    event_text: str,
    category_descriptions: dict[str, str],
    severity_descriptions: dict[str, str],
    base_url: str,
    api_key: str,
    model: str,
    app_settings: SentinelSettings | None = None,
) -> tuple[
    tuple[str, float, dict[str, float]],
    tuple[str, float, dict[str, float]],
]:
    """
    使用 rerank 模型同时分类事件类别和严重度。

    将类别和严重度描述合并到一个documents列表，通过前缀区分，
    实现单次API调用完成两种分类。

    Returns:
        tuple: ((类别结果, 类别置信度, 类别得分字典), (严重度结果, 严重度置信度, 严重度得分字典))
    """
    categories = list(category_descriptions.keys())
    severities = list(severity_descriptions.keys())

    documents: list[str] = [
        f"{CATEGORY_DOC_PREFIX}{category_descriptions[cat]}" for cat in categories
    ] + [f"{SEVERITY_DOC_PREFIX}{severity_descriptions[sev]}" for sev in severities]

    query = f"这条新闻「{event_text}」属于什么类别的事件？同时评估该事件的严重度（轻微/一般/严重/重大）。"

    MAX_QUERY_LENGTH = 24000  # noqa: N806
    if len(query) > MAX_QUERY_LENGTH:
        logger.warning(
            f"Combined query length {len(query)} exceeds {MAX_QUERY_LENGTH}, falling back to keyword classification"
        )
        raise ValueError("Query length exceeds API limit")

    logger.debug(
        "Calling LiteLLM rerank provider (combined): base_url=%s, model=%s",
        base_url,
        model,
    )

    scores = await rerank_scores(
        query=query,
        documents=documents,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    if not scores:
        logger.warning(
            "Rerank API returned empty results, falling back to keyword classification"
        )
        raise ValueError("Empty rerank results")

    category_scores: dict[str, float] = {}
    severity_scores: dict[str, float] = {}

    for idx, score in enumerate(scores):
        if idx < len(categories):
            category_scores[categories[idx]] = score
        elif idx >= len(categories) and (idx - len(categories)) < len(severities):
            severity_scores[severities[idx - len(categories)]] = score
        else:
            logger.warning(
                f"Rerank returned unexpected index {idx}, "
                f"expected range [0, {len(categories) + len(severities) - 1}]"
            )

    if not category_scores:
        logger.warning(
            "No category scores returned from rerank, falling back to keyword classification"
        )
        raise ValueError("No valid category scores from rerank")

    max_category = max(category_scores, key=category_scores.__getitem__)
    max_category_score = category_scores[max_category]
    category_total = sum(category_scores.values())
    category_confidence = (
        max_category_score / category_total if category_total > 0 else 0.0
    )

    if not severity_scores:
        logger.warning(
            "No severity scores returned from rerank, falling back to keyword classification"
        )
        raise ValueError("No valid severity scores from rerank")

    max_severity = max(severity_scores, key=severity_scores.__getitem__)
    max_severity_score = severity_scores[max_severity]
    severity_total = sum(severity_scores.values())
    severity_confidence = (
        max_severity_score / severity_total if severity_total > 0 else 0.0
    )

    logger.info(
        f"Rerank classification (combined): category={max_category}, "
        f"cat_conf={category_confidence:.4f}, severity={max_severity}, "
        f"sev_conf={severity_confidence:.4f}"
    )

    return (
        (max_category, category_confidence, category_scores),
        (max_severity, severity_confidence, severity_scores),
    )


def _keyword_classify(
    event_text: str,
    keywords: dict[str, list[str]],
) -> tuple[str, float, dict[str, float]]:
    """
    使用关键词匹配进行分类（回退方案）。

    Returns:
        tuple: (分类结果, 置信度, 各类别得分字典)
    """
    event_lower = event_text.lower()
    scores: dict[str, float] = {}

    for category, kws in keywords.items():
        score = sum(1 for kw in kws if kw in event_lower)
        scores[category] = float(score)

    if not any(scores.values()):
        return "general", 0.0, scores

    max_score = max(scores.values())
    max_category = max(scores, key=scores.__getitem__)

    total_score = sum(scores.values())
    confidence = max_score / total_score if total_score > 0 else 0.0

    return max_category, confidence, scores


# ══════════════════════════════════════════════════════════════════
# 分类器类
# ══════════════════════════════════════════════════════════════════


class EventClassifier:
    """事件分类器：根据事件描述判断事件性质"""

    def __init__(
        self,
        use_rerank: bool = True,
        rerank_base_url: str | None = None,
        rerank_api_key: str | None = None,
        rerank_model: str | None = None,
        app_settings: SentinelSettings | None = None,
    ) -> None:
        """
        初始化事件分类器。

        Args:
            use_rerank: 是否使用rerank模型进行分类
            rerank_base_url: Rerank API 地址
            rerank_api_key: Rerank API Key
            rerank_model: Rerank 模型名称
        """
        self.use_rerank = use_rerank
        if (
            app_settings is None
            and use_rerank
            and (
                rerank_base_url is None
                or rerank_api_key is None
                or rerank_model is None
            )
        ):
            app_settings = get_settings()

        self._settings = app_settings
        self.rerank_base_url = rerank_base_url or (
            app_settings.effective_reranker_base_url if app_settings is not None else ""
        )
        self.rerank_api_key = rerank_api_key or (
            app_settings.effective_reranker_api_key_value()
            if app_settings is not None
            else ""
        )
        self.rerank_model = rerank_model or (
            app_settings.effective_reranker_model
            if app_settings is not None
            else "BAAI/bge-reranker-v2-m3"
        )

        if self.use_rerank and not self.rerank_api_key:
            logger.warning(
                "Rerank is enabled (use_rerank=True) but no API key is "
                "configured. Falling back to keyword classification."
            )

    async def classify_with_severity(
        self, event_text: str
    ) -> tuple[str, float, str, float]:
        """
        同时分类事件类别和严重度，在 rerank 模式下仅调用一次 API。

        Args:
            event_text: 事件描述文本

        Returns:
            tuple: (类别结果, 类别置信度, 严重度结果, 严重度置信度)
        """
        try:
            if self.use_rerank and self.rerank_api_key:
                (
                    (category, cat_conf, _),
                    (severity, sev_conf, _),
                ) = await _rerank_classify_combined(
                    event_text,
                    CATEGORY_DESCRIPTIONS,
                    SEVERITY_DESCRIPTIONS,
                    self.rerank_base_url,
                    self.rerank_api_key,
                    self.rerank_model,
                    self._settings,
                )
                return category, cat_conf, severity, sev_conf
        except Exception as e:
            logger.warning(
                "Rerank classification failed (%s), falling back to keyword classification",
                e,
            )

        cat_result = _keyword_classify(event_text, CATEGORY_KEYWORDS)
        sev_result = _keyword_classify(event_text, SEVERITY_KEYWORDS)
        return (
            cat_result[0],
            cat_result[1],
            sev_result[0],
            sev_result[1],
        )

    def get_category_name(self, category: str) -> str:
        """获取类别的中文名称"""
        return CATEGORY_NAMES.get(category, category)

    def get_severity_name(self, severity: str) -> str:
        """获取严重度的中文名称"""
        return SEVERITY_NAMES.get(severity, severity)

    def get_time_ranges(self, severity: str) -> dict[str, str]:
        """
        根据严重度获取对应的时间范围。

        Args:
            severity: 严重度标签

        Returns:
            dict: 时间范围字典，包含short_term, medium_term, long_term
        """
        return SEVERITY_TO_TIME_RANGES.get(
            severity, SEVERITY_TO_TIME_RANGES["moderate"]
        )
