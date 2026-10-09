from pathlib import Path

import pytest
from crewai import Agent

from sentinel.trend_prediction.classifier import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_KEYWORDS,
    CATEGORY_NAMES,
    SEVERITY_DESCRIPTIONS,
    EventClassifier,
)
from sentinel.trend_prediction.task_templates import (
    get_intent_analysis_task,
    get_trend_prediction_task,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

KNOWN_FAILURE_TEXT = (
    "2026年5月22日 23:15 PM，【P08# 刘波】与【P09# 马会】在【L31# 武汉市汉阳区】"
    "一处临时仓库内被发现大量危险化学品和疑似自制爆炸装置材料，现场情况紧急，"
    "警方和消防部门已到场处置。"
)


def test_public_safety_category_metadata_exists() -> None:
    assert "public_safety" in CATEGORY_DESCRIPTIONS
    assert CATEGORY_NAMES["public_safety"] == "公共安全"
    assert "危险化学品" in CATEGORY_KEYWORDS["public_safety"]
    assert "自制爆炸装置" in CATEGORY_KEYWORDS["public_safety"]


@pytest.mark.asyncio
async def test_keyword_fallback_routes_known_failure_to_public_safety() -> None:
    classifier = EventClassifier(use_rerank=False)

    (
        category,
        confidence,
        severity,
        severity_confidence,
    ) = await classifier.classify_with_severity(KNOWN_FAILURE_TEXT)

    assert category == "public_safety"
    assert confidence > 0
    assert severity in {"moderate", "severe", "critical"}
    assert severity_confidence >= 0


def make_agent() -> Agent:
    return Agent(
        role="测试分析员",
        goal="验证提示词选择",
        backstory="用于单元测试的分析员。",
        allow_delegation=False,
        verbose=False,
    )


def test_adaptive_prompt_assets_have_one_runtime_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "src/sentinel/trend_prediction/prompts").mkdir(parents=True)
    (tmp_path / "src/sentinel/trend_prediction/adapters").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert not (REPO_ROOT / "src/sentinel/trend_prediction/prompts").exists()
    assert not (REPO_ROOT / "src/sentinel/trend_prediction/adapters").exists()


def test_intent_task_general_prompt_preserves_public_safety_metadata() -> None:
    classifier = EventClassifier(use_rerank=False)

    task = get_intent_analysis_task(
        event_text=KNOWN_FAILURE_TEXT,
        classifier=classifier,
        category="public_safety",
        confidence=0.61,
        agent=make_agent(),
        prompt_category="general",
    )

    assert "当前事件分类：公共安全" in task.description
    assert "分类置信度：61%" in task.description


def test_trend_task_general_prompt_preserves_public_safety_metadata() -> None:
    classifier = EventClassifier(use_rerank=False)
    intent_task = get_intent_analysis_task(
        event_text=KNOWN_FAILURE_TEXT,
        classifier=classifier,
        category="public_safety",
        confidence=0.61,
        agent=make_agent(),
    )

    task = get_trend_prediction_task(
        event_text=KNOWN_FAILURE_TEXT,
        intent_task=intent_task,
        classifier=classifier,
        category="public_safety",
        confidence=0.61,
        agent=make_agent(),
        severity="severe",
        severity_confidence=0.74,
        prompt_category="general",
    )

    assert "当前事件分类：公共安全" in task.description
    assert "分类置信度：61%" in task.description
    assert "事件影响严重度：严重" in task.description
    assert "严重度置信度：74%" in task.description


@pytest.mark.asyncio
async def test_reranker_energy_result_is_preserved_without_external_api(
    monkeypatch,
) -> None:
    async def fake_rerank_classify_combined(
        event_text: str,
        category_descriptions: dict[str, str],
        severity_descriptions: dict[str, str],
        base_url: str,
        api_key: str,
        model: str,
        app_settings=None,
    ):
        del app_settings
        return (
            (
                "energy",
                0.609,
                {
                    "energy": 0.61,
                    "public_safety": 0.24,
                    "society": 0.06,
                    "economy": 0.03,
                    "intl_politics": 0.02,
                    "public_health": 0.02,
                    "finance": 0.01,
                    "tech": 0.01,
                },
            ),
            ("severe", 0.7445, {"severe": 0.7445, "moderate": 0.1}),
        )

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier._rerank_classify_combined",
        fake_rerank_classify_combined,
    )
    classifier = EventClassifier(
        use_rerank=True,
        rerank_api_key="test-key",
        rerank_base_url="https://example.invalid",
        rerank_model="test-reranker",
    )

    (
        category,
        confidence,
        severity,
        severity_confidence,
    ) = await classifier.classify_with_severity(KNOWN_FAILURE_TEXT)

    assert category == "energy"
    assert confidence == pytest.approx(0.609)
    assert severity == "severe"
    assert severity_confidence == pytest.approx(0.7445)


@pytest.mark.asyncio
async def test_reranker_public_safety_result_is_selected_as_peer_category(
    monkeypatch,
) -> None:
    async def fake_rerank_classify_combined(
        event_text: str,
        category_descriptions: dict[str, str],
        severity_descriptions: dict[str, str],
        base_url: str,
        api_key: str,
        model: str,
        app_settings=None,
    ) -> tuple[
        tuple[str, float, dict[str, float]], tuple[str, float, dict[str, float]]
    ]:
        del app_settings
        return (
            (
                "public_safety",
                0.62,
                {
                    "public_safety": 0.62,
                    "energy": 0.24,
                    "society": 0.06,
                    "economy": 0.03,
                    "intl_politics": 0.02,
                    "public_health": 0.02,
                    "finance": 0.01,
                    "tech": 0.01,
                },
            ),
            ("severe", 0.7445, {"severe": 0.7445, "moderate": 0.1}),
        )

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier._rerank_classify_combined",
        fake_rerank_classify_combined,
    )
    classifier = EventClassifier(
        use_rerank=True,
        rerank_api_key="test-key",
        rerank_base_url="https://example.invalid",
        rerank_model="test-reranker",
    )

    (
        category,
        confidence,
        severity,
        severity_confidence,
    ) = await classifier.classify_with_severity(KNOWN_FAILURE_TEXT)

    assert category == "public_safety"
    assert confidence == pytest.approx(0.62)
    assert severity == "severe"
    assert severity_confidence == pytest.approx(0.7445)


@pytest.mark.asyncio
async def test_reranker_classifier_uses_litellm_rerank_util(monkeypatch) -> None:
    from sentinel.config import SentinelSettings

    calls = []

    async def fake_rerank_scores(
        *,
        query: str,
        documents: list[str],
        model: str,
        api_key: str,
        base_url: str,
    ) -> list[float]:
        calls.append(
            {
                "query": query,
                "documents": documents,
                "model": model,
                "api_key": api_key,
                "base_url": base_url,
            }
        )
        categories = list(CATEGORY_DESCRIPTIONS.keys())
        severities = list(SEVERITY_DESCRIPTIONS.keys())
        scores = [0.01] * (len(categories) + len(severities))
        scores[categories.index("public_safety")] = 0.9
        scores[len(categories) + severities.index("severe")] = 0.8
        return scores

    monkeypatch.setattr(
        "sentinel.trend_prediction.classifier.rerank_scores",
        fake_rerank_scores,
    )
    settings = SentinelSettings(
        _env_file=None,
        neo4j_password="neo4j",
        llm_api_key="llm",
        reranker_api_key="rerank-key",
        reranker_base_url="https://rerank.example/v1",
        reranker_model="reranker-model",
    )
    classifier = EventClassifier(use_rerank=True, app_settings=settings)

    (
        category,
        confidence,
        severity,
        severity_confidence,
    ) = await classifier.classify_with_severity(KNOWN_FAILURE_TEXT)

    assert category == "public_safety"
    assert confidence > 0.8
    assert severity == "severe"
    assert severity_confidence > 0.8
    assert calls[0]["model"] == "reranker-model"
    assert calls[0]["api_key"] == "rerank-key"
    assert calls[0]["base_url"] == "https://rerank.example/v1"
