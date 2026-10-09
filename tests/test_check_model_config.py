import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import check_model_config as checker
from sentinel.config import SentinelSettings


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_provider": "openai",
        "llm_model": "chat-model",
        "llm_base_url": "https://llm.example/v1",
        "embedder_model": "embedder-model",
        "embedder_api_key": None,
        "embedder_api_base": None,
        "reranker_model": "reranker-model",
        "reranker_api_key": None,
        "reranker_base_url": None,
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def test_static_only_prints_masked_model_configs_once(capsys):
    settings = make_settings(
        embedder_api_key="embed-secret",
        reranker_api_key="rerank-secret",
        reranker_base_url="https://rerank.example/v1",
        reranker_model="reranker-model",
    )

    exit_code = checker.main(
        ["--static-only"],
        settings_loader=lambda: settings,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "STATIC PASS llm" in output
    assert output.count("STATIC PASS reranker") == 1
    assert "graph_reranker" not in output
    assert "classifier_reranker" not in output
    assert "chat-model" in output
    assert "llm-secret" not in output
    assert "embed-secret" not in output
    assert "rerank-secret" not in output
    assert "ll***et" in output
    assert "em***et" in output
    assert "re***et" in output
    assert "openai/chat-model" in output
    assert "openai/embedder-model" in output
    assert "jina_ai/reranker-model" in output


def test_static_only_script_uses_local_litellm_cost_map():
    env = os.environ.copy()
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    env.pop("SENTINEL_CONFIG_FILE", None)
    env.update(
        {
            "NEO4J_PASSWORD": "dummy",
            "LLM_API_KEY": "dummy",
        }
    )

    result = subprocess.run(
        [sys.executable, "scripts/check_model_config.py", "--static-only"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=15,
    )

    combined_output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "STATIC PASS reranker" in result.stdout
    assert "Provider List" not in combined_output
    assert "Failed to fetch remote model cost map" not in combined_output


def test_default_run_requires_confirmation_before_live_checks(capsys):
    settings = make_settings()

    exit_code = checker.main(
        [],
        settings_loader=lambda: settings,
        confirm_input=lambda prompt: "no",
    )

    output = capsys.readouterr().out
    assert exit_code == checker.EXIT_CANCELLED
    assert "may consume user account quota" in output
    assert "cancelled" in output


def test_non_interactive_confirmation_is_cancelled(capsys):
    settings = make_settings()

    exit_code = checker.main(
        [],
        settings_loader=lambda: settings,
        confirm_input=lambda prompt: (_ for _ in ()).throw(EOFError),
    )

    output = capsys.readouterr().out
    assert exit_code == checker.EXIT_CANCELLED
    assert "may consume user account quota" in output
    assert "cancelled" in output


def test_yes_flag_still_prints_live_warning(capsys, monkeypatch):
    settings = make_settings()

    async def fake_run_live_checks(settings_arg, checks):
        return 0

    monkeypatch.setattr(checker, "_run_live_checks", fake_run_live_checks)

    exit_code = checker.main(["--yes"], settings_loader=lambda: settings)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "may consume user account quota" in output


def test_live_check_failures_redact_configured_secrets(capsys, monkeypatch):
    settings = make_settings(reranker_api_key="rerank-secret")

    async def fake_generate_text(*args, **kwargs):
        raise RuntimeError("bad key llm-secret rerank-secret")

    monkeypatch.setattr(checker, "generate_text", fake_generate_text)

    exit_code = checker.main(["--yes"], settings_loader=lambda: settings)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "llm-secret" not in output
    assert "rerank-secret" not in output
    assert "ll***et" in output
    assert "re***et" in output


@pytest.mark.asyncio
async def test_run_live_checks_calls_each_distinct_model_once(monkeypatch):
    settings = make_settings(
        embedder_api_key=None,
        reranker_api_key="rerank-secret",
        reranker_base_url="https://rerank.example/v1",
        reranker_model="shared-reranker",
    )
    calls: list[tuple[str, dict]] = []

    async def fake_generate_text(settings_arg, **kwargs):
        calls.append(("llm", kwargs))
        return "pong"

    async def fake_embed_text(settings_arg, text, **kwargs):
        calls.append(("embedding", {"text": text, **kwargs}))
        return [0.1]

    async def fake_rerank_scores(**kwargs):
        calls.append(("rerank", kwargs))
        return [1.0]

    monkeypatch.setattr(checker, "generate_text", fake_generate_text)
    monkeypatch.setattr(checker, "embed_text", fake_embed_text)
    monkeypatch.setattr(checker, "rerank_scores", fake_rerank_scores)

    results = await checker.run_live_checks(settings)

    assert [result.status for result in results] == ["PASS", "PASS", "PASS"]
    assert [kind for kind, _ in calls] == ["llm", "embedding", "rerank"]
    assert calls[0][1]["prompt"] == "ping"
    assert calls[0][1]["temperature"] == 0
    assert calls[0][1]["max_completion_tokens"] <= 8
    assert calls[0][1]["extra_body"] == checker.THINKING_DISABLED_EXTRA_BODY
    assert calls[1][1]["text"] == "x"
    assert calls[2][1]["query"] == "x"
    assert calls[2][1]["documents"] == ["x"]
    assert "provider" not in calls[2][1]


@pytest.mark.asyncio
async def test_generate_text_passes_extra_body_to_litellm(monkeypatch):
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
        prompt="ping",
        extra_body={"enable_thinking": False},
    )

    assert text == "pong"
    assert captured["extra_body"] == {"enable_thinking": False}
