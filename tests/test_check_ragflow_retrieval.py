"""Tests for the RAGFlow retrieval self-check script."""

from scripts import check_ragflow_retrieval as checker
from sentinel.config import SentinelSettings


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "ragflow_enabled": True,
        "ragflow_base_url": "http://ragflow.example",
        "ragflow_api_key": "rag-secret",
        "ragflow_dataset_id": "dataset",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def test_main_rejects_incomplete_ragflow_config(capsys) -> None:
    exit_code = checker.main(
        ["query"],
        settings_loader=lambda: make_settings(ragflow_api_key=None),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "RAGFlow is not ready" in output
    assert "config/config.yaml" in output
    assert "RAGFLOW_API_KEY" in output
    assert "rag-secret" not in output


def test_main_prints_ready_and_formatted_chunks(monkeypatch, capsys) -> None:
    async def fake_retrieve(self, query):
        assert query == "money laundering"
        return {
            "ready": True,
            "chunks": [
                {
                    "content": "AML red flag.",
                    "document_name": "aml.pdf",
                    "score": 0.9,
                }
            ],
        }

    monkeypatch.setattr(
        "sentinel.ragflow.client.RagflowClient.retrieve",
        fake_retrieve,
    )

    exit_code = checker.main(
        ["money laundering"],
        settings_loader=lambda: make_settings(),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "ready=True chunks=1" in output
    assert "AML red flag" in output
    assert "aml.pdf" in output
    assert "rag-secret" not in output


def test_main_returns_nonzero_when_retrieval_is_not_ready(
    monkeypatch,
    capsys,
) -> None:
    async def fake_retrieve(self, query):
        assert query == "money laundering"
        return {
            "ready": False,
            "chunks": [],
            "error": "ConnectError",
        }

    monkeypatch.setattr(
        "sentinel.ragflow.client.RagflowClient.retrieve",
        fake_retrieve,
    )

    exit_code = checker.main(
        ["money laundering"],
        settings_loader=lambda: make_settings(),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "ready=False chunks=0" in output
    assert "rag-secret" not in output


def test_main_treats_ready_without_chunks_as_success(monkeypatch, capsys) -> None:
    async def fake_retrieve(self, query):
        assert query == "money laundering"
        return {
            "ready": True,
            "chunks": [],
        }

    monkeypatch.setattr(
        "sentinel.ragflow.client.RagflowClient.retrieve",
        fake_retrieve,
    )

    exit_code = checker.main(
        ["money laundering"],
        settings_loader=lambda: make_settings(),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "ready=True chunks=0" in output
    assert "<retrieved_chunk" not in output
    assert "rag-secret" not in output
