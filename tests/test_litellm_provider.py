import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sentinel.config import SentinelSettings


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_provider": "openai",
        "llm_model": "gpt-test",
        "llm_base_url": "https://llm.example/v1",
        "embedder_model": "BAAI/bge-m3",
        "embedder_api_base": None,
        "embedder_api_key": None,
        "reranker_model": None,
        "reranker_base_url": None,
        "reranker_api_key": None,
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def test_litellm_model_name_prefixes_bare_and_namespaced_models():
    from sentinel.utils.litellm_models import litellm_model_name

    assert litellm_model_name("openai", "gpt-test") == "openai/gpt-test"
    assert litellm_model_name("openai", "BAAI/bge-m3") == "openai/BAAI/bge-m3"
    assert (
        litellm_model_name("openai", "Qwen/Qwen2.5-72B-Instruct")
        == "openai/Qwen/Qwen2.5-72B-Instruct"
    )


def test_litellm_model_name_preserves_known_provider_prefixes():
    from sentinel.utils.litellm_models import litellm_model_name

    assert litellm_model_name("openai", "openai/gpt-4o") == "openai/gpt-4o"
    assert litellm_model_name("openai", "deepseek/chat") == "deepseek/chat"
    assert (
        litellm_model_name("openai", "jina_ai/jina-reranker-v2-base-multilingual")
        == "jina_ai/jina-reranker-v2-base-multilingual"
    )


def test_litellm_model_name_does_not_import_litellm_for_provider_detection():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys;"
                "os.environ.pop('LITELLM_LOCAL_MODEL_COST_MAP', None);"
                "from sentinel.utils.litellm_models import litellm_model_name;"
                "print(litellm_model_name('openai', 'gpt-test'));"
                "print('litellm' in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["openai/gpt-test", "False"]
    assert "Failed to fetch remote model cost map" not in result.stderr


def test_litellm_rerank_model_name_defaults_to_jina_provider():
    from sentinel.utils.litellm_models import litellm_rerank_model_name

    assert litellm_rerank_model_name("Qwen3-Reranker-8B") == "jina_ai/Qwen3-Reranker-8B"
    assert (
        litellm_rerank_model_name("BAAI/bge-reranker-v2-m3")
        == "jina_ai/BAAI/bge-reranker-v2-m3"
    )
    assert litellm_rerank_model_name("cohere/rerank-v3.5") == "cohere/rerank-v3.5"


@pytest.mark.asyncio
async def test_generate_text_calls_litellm_acompletion(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    monkeypatch.setattr(
        "sentinel.utils.litellm_text.litellm.acompletion", fake_acompletion
    )

    from sentinel.utils.litellm_text import generate_text

    text = await generate_text(
        make_settings(),
        prompt="hello",
        temperature=0.2,
    )

    assert text == '{"ok": true}'
    assert calls[0]["model"] == "openai/gpt-test"
    assert calls[0]["api_key"] == "llm-secret"
    assert calls[0]["api_base"] == "https://llm.example/v1"
    assert calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert calls[0]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_generate_text_passes_timeout_to_litellm(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )

    monkeypatch.setattr(
        "sentinel.utils.litellm_text.litellm.acompletion", fake_acompletion
    )

    from sentinel.utils.litellm_text import generate_text

    text = await generate_text(
        make_settings(),
        prompt="hello",
        timeout=12,
    )

    assert text == "pong"
    assert captured["timeout"] == 12


@pytest.mark.asyncio
async def test_generate_text_enforces_asyncio_timeout(monkeypatch):
    async def fake_acompletion(**kwargs):
        await asyncio.sleep(0.05)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )

    monkeypatch.setattr(
        "sentinel.utils.litellm_text.litellm.acompletion", fake_acompletion
    )

    from sentinel.utils.litellm_text import generate_text

    with pytest.raises(TimeoutError):
        await generate_text(
            make_settings(),
            prompt="hello",
            timeout=0.01,
        )


@pytest.mark.asyncio
async def test_embed_text_returns_first_embedding(monkeypatch):
    async def fake_aembedding(**kwargs):
        assert kwargs["model"] == "openai/BAAI/bge-m3"
        assert kwargs["input"] == ["alpha"]
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr(
        "sentinel.utils.litellm_embedding.litellm.aembedding",
        fake_aembedding,
    )

    from sentinel.utils.litellm_embedding import embed_text

    assert await embed_text(make_settings(), "alpha") == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_rerank_scores_preserves_document_order(monkeypatch):
    async def fake_arerank(**kwargs):
        assert kwargs["model"] == "jina_ai/reranker-test"
        assert kwargs["query"] == "q"
        assert kwargs["documents"] == ["a", "b", "c"]
        assert kwargs["top_n"] == 3
        assert kwargs["return_documents"] is True
        assert kwargs["api_key"] == "rerank-secret"
        assert kwargs["api_base"] == "https://rerank.example/v1"
        return {
            "results": [
                {"index": 2, "document": None, "relevance_score": 0.9},
                {"index": 0, "document": None, "relevance_score": 0.4},
            ]
        }

    monkeypatch.setattr("sentinel.utils.litellm_rerank.litellm.arerank", fake_arerank)

    from sentinel.utils.litellm_rerank import rerank_scores

    settings = make_settings(
        reranker_api_key="rerank-secret",
        reranker_base_url="https://rerank.example/v1",
        reranker_model="reranker-test",
    )

    assert await rerank_scores(
        query="q",
        documents=["a", "b", "c"],
        model=settings.effective_reranker_model,
        api_key=settings.effective_reranker_api_key_value(),
        base_url=settings.effective_reranker_base_url,
    ) == [0.4, 0.0, 0.9]


@pytest.mark.asyncio
async def test_rerank_scores_preserves_prefixed_rerank_model(monkeypatch):
    async def fake_arerank(**kwargs):
        assert kwargs["model"] == "cohere/rerank-v3.5"
        assert kwargs["query"] == "q"
        assert kwargs["documents"] == ["a", "b"]
        return {
            "results": [
                {"index": 1, "relevance_score": 0.8},
                {"index": 0, "relevance_score": 0.3},
            ]
        }

    monkeypatch.setattr("sentinel.utils.litellm_rerank.litellm.arerank", fake_arerank)

    from sentinel.utils.litellm_rerank import rerank_scores

    assert await rerank_scores(
        query="q",
        documents=["a", "b"],
        model="cohere/rerank-v3.5",
        api_key="rerank-secret",
        base_url="https://rerank.example/v1",
    ) == [0.3, 0.8]
