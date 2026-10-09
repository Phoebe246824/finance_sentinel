from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from sentinel.config import SentinelSettings, load_yaml_settings


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def write_env(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_yaml(path: Path, text: str) -> None:
    path.write_text(dedent(text).strip() + "\n", encoding="utf-8")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key] = value
    return values


def load_settings_from_files(config_file: Path, env_file: Path) -> SentinelSettings:
    env_values = read_env(env_file)
    return SentinelSettings(
        _env_file=None,
        **load_yaml_settings(config_file),
        neo4j_password=env_values["NEO4J_PASSWORD"],
        llm_api_key=env_values["LLM_API_KEY"],
        milvus_token=env_values.get("MILVUS_TOKEN"),
    )


def test_serialize_settings_masks_secrets(tmp_path: Path):
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        models:
          llm:
            provider: custom-openai
            model: gpt-runtime-test
            base_url: https://llm.internal.example/v1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-runtime-secret",
            "MILVUS_TOKEN=milvus-runtime-token",
        ],
    )

    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: load_settings_from_files(yaml_path, env_path),
    )

    payload = service.read_runtime_settings()

    assert payload.models.llm.provider == "custom-openai"
    assert payload.models.llm.model == "gpt-runtime-test"
    assert payload.models.llm.base_url == "https://llm.internal.example/v1"
    assert payload.secrets.milvus_token.configured is True
    assert payload.secrets.milvus_token.masked_hint == "****"
    assert payload.secrets.llm_api_key.configured is True
    assert payload.secrets.llm_api_key.masked_hint == "****"
    assert "llm-runtime-secret" not in payload.model_dump_json()
    assert "milvus-runtime-token" not in payload.model_dump_json()


def test_save_runtime_settings_keeps_secret_when_input_blank(tmp_path: Path):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
          embedder:
            model: BAAI/bge-m3
            api_base: https://api.siliconflow.cn/v1
            dim: 1024
          reranker:
            model: BAAI/bge-reranker-v2-m3
            base_url: https://api.siliconflow.cn/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )

    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(),
    )

    updated = service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": True},
                },
                "runtime": {
                    "search": {
                        "num_results": 12,
                        "risk_num_results": 24,
                        "min_score": 0.1,
                    },
                    "risk": {"threshold": 0.8},
                    "stash": {
                        "kv_ttl_days": 95,
                        "semantic_top_k": 11,
                        "rerank_min_score": 0.75,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 22},
                    "blacklist": {
                        "event_similarity_threshold": 0.55,
                        "person_min_hits": 2,
                    },
                },
            }
        )
    )

    env_text = env_path.read_text(encoding="utf-8")
    yaml_doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    assert "LLM_API_KEY=llm-secret" in env_text
    assert yaml_doc["models"]["llm"]["model"] == "gpt-4.1"
    assert updated.models.llm.model == "gpt-4.1"
    assert updated.services.graphiti.dry_run is True


def test_save_runtime_settings_preserves_required_secret_from_loader_when_env_file_omits_it(
    tmp_path: Path,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )

    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(),
    )

    updated = service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    assert updated.models.llm.model == "gpt-4.1"


def test_save_runtime_settings_replaces_secret_when_new_value_provided(
    tmp_path: Path,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
          embedder:
            model: BAAI/bge-m3
            api_base: https://api.siliconflow.cn/v1
            dim: 1024
          reranker:
            model: BAAI/bge-reranker-v2-m3
            base_url: https://api.siliconflow.cn/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )

    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(),
    )

    service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "new-llm-secret",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    env_text = env_path.read_text(encoding="utf-8")
    assert "LLM_API_KEY=new-llm-secret" in env_text
    assert "LLM_API_KEY=llm-secret" not in env_text


def test_write_failure_does_not_overwrite_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    original_yaml = """
    neo4j:
      uri: bolt://localhost:7687
      user: neo4j
      database: neo4j
    graphiti:
      dry_run: false
    models:
      llm:
        provider: openai
        model: gpt-4o
        base_url: https://api.openai.com/v1
      embedder:
        model: BAAI/bge-m3
        api_base: https://api.siliconflow.cn/v1
        dim: 1024
      reranker:
        model: BAAI/bge-reranker-v2-m3
        base_url: https://api.siliconflow.cn/v1
    search:
      num_results: 10
      risk_num_results: 20
      min_score: 0.0
    risk:
      threshold: 0.7
    milvus:
      uri: http://localhost:19530
      kv_ttl_days: 90
      stash_semantic_top_k: 10
      stash_rerank_min_score: 0.7
      stash_rerank_enabled: true
      batch_max_per_person: 20
    blacklist:
      event_similarity_threshold: 0.5
      person_min_hits: 1
    """
    write_yaml(yaml_path, original_yaml)
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )

    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(),
    )

    payload = RuntimeSettingsUpdatePayload.model_validate(
        {
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://localhost:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19530",
                    "token": "",
                    "input_events_collection": "input_events",
                },
                "graphiti": {"dry_run": False},
            },
            "runtime": {
                "search": {
                    "num_results": 10,
                    "risk_num_results": 20,
                    "min_score": 0.0,
                },
                "risk": {"threshold": 0.7},
                "stash": {
                    "kv_ttl_days": 90,
                    "semantic_top_k": 10,
                    "rerank_min_score": 0.7,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 20},
                "blacklist": {
                    "event_similarity_threshold": 0.5,
                    "person_min_hits": 1,
                },
            },
        }
    )

    original_stage_file = service._stage_file

    def fail_stage_file(target: Path, content: str) -> Path:
        if target == env_path:
            raise OSError("simulated env write failure")
        return original_stage_file(target, content)

    monkeypatch.setattr(service, "_stage_file", fail_stage_file)

    with pytest.raises(OSError, match="simulated env write failure"):
        service.save_runtime_settings(payload)

    assert yaml_path.read_text(encoding="utf-8") == dedent(original_yaml).strip() + "\n"
    env_text = env_path.read_text(encoding="utf-8")
    assert "LLM_API_KEY=llm-secret" in env_text


def test_save_runtime_settings_normalizes_quoted_env_values(tmp_path: Path):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            'NEO4J_PASSWORD="neo4j secret #123"',
            'LLM_API_KEY="llm secret #123"',
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: load_settings_from_files(yaml_path, env_path),
    )

    service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    current = service.current_settings()
    assert current.require_llm_api_key() == "llm secret #123"
    env_text = env_path.read_text(encoding="utf-8")
    assert 'LLM_API_KEY="llm secret #123"' in env_text
    assert 'NEO4J_PASSWORD="neo4j secret #123"' in env_text


def test_save_runtime_settings_rejects_dotenv_interpolation_in_new_secret(
    tmp_path: Path,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(),
    )

    payload = RuntimeSettingsUpdatePayload.model_validate(
        {
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "abc${MISSING}def",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://localhost:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19530",
                    "token": "",
                    "input_events_collection": "input_events",
                },
                "graphiti": {"dry_run": False},
            },
            "runtime": {
                "search": {
                    "num_results": 10,
                    "risk_num_results": 20,
                    "min_score": 0.0,
                },
                "risk": {"threshold": 0.7},
                "stash": {
                    "kv_ttl_days": 90,
                    "semantic_top_k": 10,
                    "rerank_min_score": 0.7,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 20},
                "blacklist": {
                    "event_similarity_threshold": 0.5,
                    "person_min_hits": 1,
                },
            },
        }
    )

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        service.save_runtime_settings(payload)

    assert "abc${MISSING}def" not in env_path.read_text(encoding="utf-8")


def test_save_runtime_settings_removes_editable_non_secret_env_overrides(
    tmp_path: Path,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: yaml-old
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            f"SENTINEL_CONFIG_FILE={yaml_path}",
            "LLM_MODEL=env-old",
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: SentinelSettings(_env_file=env_path),
    )

    updated = service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "yaml-new",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.openai.com/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    assert updated.models.llm.model == "yaml-new"
    env_text = env_path.read_text(encoding="utf-8")
    assert "SENTINEL_CONFIG_FILE=" not in env_text
    assert "LLM_MODEL=" not in env_text
    assert load_yaml_settings(yaml_path)["llm_model"] == "yaml-new"


def test_save_runtime_settings_uses_dotenv_parser_for_comments_and_export(
    tmp_path: Path,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            f"SENTINEL_CONFIG_FILE={yaml_path}",
            "export NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret # trailing comment",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: SentinelSettings(_env_file=env_path),
    )

    service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.openai.com/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    current = service.current_settings()
    assert current.require_neo4j_password() == "neo4j-secret"
    assert current.require_llm_api_key() == "llm-secret"
    env_text = env_path.read_text(encoding="utf-8")
    assert "export NEO4J_PASSWORD" not in env_text
    assert "LLM_API_KEY=llm-secret" in env_text


def test_save_runtime_settings_rejects_process_env_non_secret_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    monkeypatch.setenv("LLM_MODEL", "env-old")
    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://localhost:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: yaml-old
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(llm_model="env-old"),
    )

    payload = RuntimeSettingsUpdatePayload.model_validate(
        {
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "yaml-new",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.openai.com/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://localhost:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19530",
                    "token": "",
                    "input_events_collection": "input_events",
                },
                "graphiti": {"dry_run": False},
            },
            "runtime": {
                "search": {
                    "num_results": 10,
                    "risk_num_results": 20,
                    "min_score": 0.0,
                },
                "risk": {"threshold": 0.7},
                "stash": {
                    "kv_ttl_days": 90,
                    "semantic_top_k": 10,
                    "rerank_min_score": 0.7,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 20},
                "blacklist": {
                    "event_similarity_threshold": 0.5,
                    "person_min_hits": 1,
                },
            },
        }
    )

    with pytest.raises(ValueError, match="LLM_MODEL"):
        service.save_runtime_settings(payload)


def test_save_runtime_settings_allows_unchanged_process_env_service_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    monkeypatch.setenv("MILVUS_URI", "http://milvus:19530")
    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://neo4j:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://milvus:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(
            neo4j_uri="bolt://neo4j:7687",
            milvus_uri="http://milvus:19530",
        ),
    )

    updated = service.save_runtime_settings(
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.openai.com/v1",
                        "api_key": "",
                        "embedding_dim": 1024,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://neo4j:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://milvus:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": 10,
                        "risk_num_results": 20,
                        "min_score": 0.0,
                    },
                    "risk": {"threshold": 0.7},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
    )

    assert updated.models.llm.model == "gpt-4.1"
    assert updated.services.neo4j.uri == "bolt://neo4j:7687"
    assert updated.services.milvus.uri == "http://milvus:19530"


def test_save_runtime_settings_rejects_changed_process_env_service_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload
    from sentinel.web.settings_service import RuntimeSettingsService

    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    yaml_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    write_yaml(
        yaml_path,
        """
        neo4j:
          uri: bolt://neo4j:7687
          user: neo4j
          database: neo4j
        graphiti:
          dry_run: false
        models:
          llm:
            provider: openai
            model: gpt-4o
            base_url: https://api.openai.com/v1
        search:
          num_results: 10
          risk_num_results: 20
          min_score: 0.0
        risk:
          threshold: 0.7
        milvus:
          uri: http://localhost:19530
          kv_ttl_days: 90
          stash_semantic_top_k: 10
          stash_rerank_min_score: 0.7
          stash_rerank_enabled: true
          batch_max_per_person: 20
        blacklist:
          event_similarity_threshold: 0.5
          person_min_hits: 1
        """,
    )
    write_env(
        env_path,
        [
            "NEO4J_PASSWORD=neo4j-secret",
            "LLM_API_KEY=llm-secret",
        ],
    )
    service = RuntimeSettingsService(
        config_file=yaml_path,
        env_file=env_path,
        settings_loader=lambda: make_settings(neo4j_uri="bolt://neo4j:7687"),
    )

    payload = RuntimeSettingsUpdatePayload.model_validate(
        {
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.openai.com/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://external-neo4j:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19530",
                    "token": "",
                    "input_events_collection": "input_events",
                },
                "graphiti": {"dry_run": False},
            },
            "runtime": {
                "search": {
                    "num_results": 10,
                    "risk_num_results": 20,
                    "min_score": 0.0,
                },
                "risk": {"threshold": 0.7},
                "stash": {
                    "kv_ttl_days": 90,
                    "semantic_top_k": 10,
                    "rerank_min_score": 0.7,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 20},
                "blacklist": {
                    "event_similarity_threshold": 0.5,
                    "person_min_hits": 1,
                },
            },
        }
    )

    with pytest.raises(ValueError, match="NEO4J_URI"):
        service.save_runtime_settings(payload)


def test_from_active_settings_uses_fixed_config_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from sentinel import config as sentinel_config
    from sentinel.web.settings_service import RuntimeSettingsService

    env_file = tmp_path / ".env"
    fixed_config = tmp_path / "config.yaml"
    ignored_config = tmp_path / "alt-config.yaml"
    write_env(env_file, [f'SENTINEL_CONFIG_FILE="{ignored_config}"'])
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", fixed_config)

    class DummySettings:
        def resolved_env_file_path(self) -> Path:
            return env_file

        def resolved_config_file_path(self) -> Path:
            return fixed_config

    active_settings = DummySettings()

    service = RuntimeSettingsService.from_active_settings(
        lambda: active_settings,
        active_settings=active_settings,
    )

    assert service._config_file == fixed_config
    assert service._env_file == env_file


def test_runtime_settings_update_rejects_invalid_ranges():
    from pydantic import ValidationError

    from sentinel.web.settings_models import RuntimeSettingsUpdatePayload

    with pytest.raises(ValidationError):
        RuntimeSettingsUpdatePayload.model_validate(
            {
                "models": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "",
                    },
                    "embedder": {
                        "model": "BAAI/bge-m3",
                        "api_base": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                        "embedding_dim": -1,
                    },
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "",
                    },
                },
                "services": {
                    "neo4j": {
                        "uri": "bolt://localhost:7687",
                        "user": "neo4j",
                        "password": "",
                        "database": "neo4j",
                    },
                    "milvus": {
                        "uri": "http://localhost:19530",
                        "token": "",
                        "input_events_collection": "input_events",
                    },
                    "graphiti": {"dry_run": False},
                },
                "runtime": {
                    "search": {
                        "num_results": -1,
                        "risk_num_results": 20,
                        "min_score": 9.9,
                    },
                    "risk": {"threshold": -0.5},
                    "stash": {
                        "kv_ttl_days": 90,
                        "semantic_top_k": 10,
                        "rerank_min_score": 0.7,
                        "rerank_enabled": True,
                    },
                    "batch": {"max_per_person": 20},
                    "blacklist": {
                        "event_similarity_threshold": 0.5,
                        "person_min_hits": 1,
                    },
                },
            }
        )
