"""Tests for Sentinel settings loading and validation."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from sentinel import config as sentinel_config
from sentinel.config import (
    SentinelSettings,
    get_settings,
    load_yaml_settings,
    migrate_yaml_settings_file,
    reset_settings_cache,
)

SETTINGS_ENV_VARS = {
    "SENTINEL_CONFIG_FILE",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "GRAPHITI_DRY_RUN",
    "GRAPHITI_EPISODE_SOURCE",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "EMBEDDER_MODEL",
    "EMBEDDER_API_KEY",
    "EMBEDDER_API_BASE",
    "EMBEDDING_DIM",
    "RERANKER_MODEL",
    "RERANKER_API_KEY",
    "RERANKER_BASE_URL",
    "SEARCH_NUM_RESULTS",
    "RISK_SEARCH_NUM_RESULTS",
    "SEARCH_MIN_SCORE",
    "RISK_THRESHOLD",
    "MILVUS_URI",
    "MILVUS_TOKEN",
    "MILVUS_INPUT_EVENTS_COLLECTION",
    "KV_TTL_DAYS",
    "STASH_SEMANTIC_TOP_K",
    "STASH_RERANK_MIN_SCORE",
    "STASH_RERANK_ENABLED",
    "BATCH_MAX_PER_PERSON",
    "BLACKLIST_EVENT_SIMILARITY_THRESHOLD",
    "BLACKLIST_PERSON_MIN_HITS",
    "DASHBOARD_ADMIN_USER",
    "DASHBOARD_ADMIN_PASSWORD",
    "DASHBOARD_ACCESS_TOKEN",
    "DASHBOARD_REFRESH_TOKEN",
    "RAGFLOW_ENABLED",
    "RAGFLOW_BASE_URL",
    "RAGFLOW_API_KEY",
    "RAGFLOW_DATASET_ID",
    "RAGFLOW_DATASET_IDS",
    "RAGFLOW_TOP_K",
    "RAGFLOW_SIMILARITY_THRESHOLD",
    "RAGFLOW_VECTOR_SIMILARITY_WEIGHT",
    "RAGFLOW_TIMEOUT_SECONDS",
    "RAGFLOW_MAX_CONTEXT_CHARS",
    "RAGFLOW_FAIL_OPEN",
    "WEB_ADMIN_PASSWORD",
}


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch):
    reset_settings_cache()
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    reset_settings_cache()


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def test_config_package_reexports_existing_public_api():
    from sentinel import config as sentinel_config
    from sentinel.config import (
        SentinelSettings,
        get_settings,
        load_yaml_settings,
        migrate_yaml_settings_file,
        reset_settings_cache,
    )

    assert sentinel_config.SentinelSettings is SentinelSettings
    assert callable(get_settings)
    assert callable(reset_settings_cache)
    assert callable(load_yaml_settings)
    assert callable(migrate_yaml_settings_file)


def test_required_secrets_are_rejected_when_missing():
    with pytest.raises(ValidationError):
        SentinelSettings(_env_file=None)


def test_empty_required_secret_is_rejected():
    with pytest.raises(ValidationError, match="llm_api_key"):
        make_settings(llm_api_key="")


def test_defaults_match_confirmed_refactor_decisions():
    settings = make_settings()

    assert settings.risk_threshold == 0.7
    assert settings.search_num_results == 10
    assert settings.risk_search_num_results == 20
    assert settings.reranker_model is None
    assert settings.effective_reranker_model == "BAAI/bge-reranker-v2-m3"
    assert not hasattr(settings, "profile_config_dir")
    assert not hasattr(settings, "effective_graph_reranker_model")
    assert not hasattr(settings, "effective_classifier_reranker_model")


def test_ragflow_defaults_match_reference_integration():
    settings = make_settings()

    assert settings.ragflow_enabled is False
    assert settings.ragflow_base_url == "http://127.0.0.1:9380"
    assert settings.optional_ragflow_api_key() is None
    assert settings.ragflow_dataset_id is None
    assert settings.ragflow_dataset_ids is None
    assert settings.ragflow_dataset_id_list() == []
    assert settings.ragflow_top_k == 5
    assert settings.ragflow_similarity_threshold == 0.2
    assert settings.ragflow_vector_similarity_weight == 0.7
    assert settings.ragflow_timeout_seconds == 15.0
    assert settings.ragflow_max_context_chars == 4000
    assert settings.ragflow_fail_open is True


def test_effective_fallbacks_preserve_raw_env_semantics():
    settings = make_settings(
        llm_base_url="https://llm.example/v1",
        reranker_model=None,
        reranker_base_url=None,
        embedder_api_key=None,
        embedder_api_base=None,
    )

    assert settings.effective_embedder_api_key_value() == "llm-secret"
    assert settings.effective_embedder_api_base == "https://llm.example/v1"
    assert settings.effective_reranker_api_key_value() == "llm-secret"
    assert settings.effective_reranker_base_url == "https://llm.example/v1"


def test_explicit_reranker_env_overrides_both_contexts():
    settings = make_settings(
        reranker_model="custom-reranker",
        reranker_base_url="https://rerank.example/v1",
        reranker_api_key="rerank-secret",
    )

    assert settings.effective_reranker_model == "custom-reranker"
    assert settings.effective_reranker_base_url == "https://rerank.example/v1"
    assert settings.effective_reranker_api_key_value() == "rerank-secret"


def test_optional_secret_helpers_return_none_for_blank_values():
    settings = make_settings(
        dashboard_admin_password="",
        dashboard_access_token="",
        dashboard_refresh_token="",
        milvus_token="",
    )

    assert settings.optional_dashboard_admin_password() is None
    assert settings.optional_dashboard_access_token() is None
    assert settings.optional_dashboard_refresh_token() is None
    assert settings.optional_milvus_token() is None


def test_dashboard_auth_settings_can_be_loaded_from_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_USER", "analyst")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "dashboard-password")
    monkeypatch.setenv("DASHBOARD_ACCESS_TOKEN", "dashboard-access")
    monkeypatch.setenv("DASHBOARD_REFRESH_TOKEN", "dashboard-refresh")

    settings = make_settings()

    assert settings.dashboard_admin_user == "analyst"
    assert settings.optional_dashboard_admin_password() == "dashboard-password"
    assert settings.optional_dashboard_access_token() == "dashboard-access"
    assert settings.optional_dashboard_refresh_token() == "dashboard-refresh"


def test_ragflow_dataset_ids_prefer_plural_and_trim_values():
    settings = make_settings(
        ragflow_dataset_id="single",
        ragflow_dataset_ids=" first, second ,, ",
        ragflow_api_key="rag-secret",
    )

    assert settings.optional_ragflow_api_key() == "rag-secret"
    assert settings.ragflow_dataset_id_list() == ["first", "second"]


def test_yaml_settings_are_loaded_from_structured_file(tmp_path):
    config_file = tmp_path / "sentinel.yaml"
    config_file.write_text(
        """
neo4j:
  uri: bolt://neo4j.local:7687
  user: neo4j-user
  database: sentinel-db
graphiti:
  dry_run: true
  episode_source: yaml-source
models:
  llm:
    provider: openai
    model: yaml-chat
    base_url: https://llm.example/v1
  embedder:
    model: yaml-embedder
    api_base: https://embed.example/v1
    dim: 2048
  reranker:
    model: yaml-reranker
    base_url: https://rerank.example/v1
search:
  num_results: 11
  risk_num_results: 22
  min_score: 0.25
risk:
  threshold: 0.8
milvus:
  uri: http://milvus.local:19530
  input_events_collection: yaml_stash
  kv_ttl_days: 30
  stash_semantic_top_k: 7
  stash_rerank_min_score: 0.6
  stash_rerank_enabled: false
  batch_max_per_person: 9
blacklist:
  event_similarity_threshold: 0.4
  person_min_hits: 3
dashboard:
  admin_user: yaml-admin
""",
        encoding="utf-8",
    )

    values = load_yaml_settings(config_file)

    assert values == {
        "neo4j_uri": "bolt://neo4j.local:7687",
        "neo4j_user": "neo4j-user",
        "neo4j_database": "sentinel-db",
        "graphiti_dry_run": True,
        "graphiti_episode_source": "yaml-source",
        "llm_provider": "openai",
        "llm_model": "yaml-chat",
        "llm_base_url": "https://llm.example/v1",
        "embedder_model": "yaml-embedder",
        "embedder_api_base": "https://embed.example/v1",
        "embedding_dim": 2048,
        "reranker_model": "yaml-reranker",
        "reranker_base_url": "https://rerank.example/v1",
        "search_num_results": 11,
        "risk_search_num_results": 22,
        "search_min_score": 0.25,
        "risk_threshold": 0.8,
        "milvus_uri": "http://milvus.local:19530",
        "milvus_input_events_collection": "yaml_stash",
        "kv_ttl_days": 30,
        "stash_semantic_top_k": 7,
        "stash_rerank_min_score": 0.6,
        "stash_rerank_enabled": False,
        "batch_max_per_person": 9,
        "blacklist_event_similarity_threshold": 0.4,
        "blacklist_person_min_hits": 3,
        "dashboard_admin_user": "yaml-admin",
    }


def test_yaml_settings_migrates_legacy_stash_collection_key(tmp_path):
    """Verify backward-compatible reading: old stash_collection key is mapped to
    milvus_input_events_collection at load time (not a file-write migration)."""
    config_file = tmp_path / "sentinel.yaml"
    config_file.write_text(
        """
milvus:
  uri: http://milvus.local:19530
  stash_collection: old_events
""",
        encoding="utf-8",
    )

    values = load_yaml_settings(config_file)

    assert values["milvus_input_events_collection"] == "old_events"


def test_migrate_yaml_settings_file_removes_legacy_stash_collection_key(tmp_path):
    config_file = tmp_path / "config.yaml"
    template_file = tmp_path / "config.example.yaml"
    config_file.write_text(
        """
milvus:
  uri: http://milvus.local:19530
  stash_collection: old_events
""",
        encoding="utf-8",
    )
    template_file.write_text(
        """
milvus:
  uri: http://localhost:19530
  input_events_collection: input_events
""",
        encoding="utf-8",
    )

    changed = migrate_yaml_settings_file(config_file, template_path=template_file)

    assert changed is True
    migrated = load_yaml_settings(config_file)
    assert migrated["milvus_input_events_collection"] == "old_events"


def test_yaml_settings_load_ragflow_values(tmp_path):
    config_file = tmp_path / "sentinel.yaml"
    config_file.write_text(
        """
ragflow:
  enabled: true
  base_url: http://ragflow.local:9380
  dataset_id: single-dataset
  dataset_ids: alpha, beta
  top_k: 8
  similarity_threshold: 0.15
  vector_similarity_weight: 0.9
  timeout_seconds: 9.5
  max_context_chars: 1234
  fail_open: false
""",
        encoding="utf-8",
    )

    values = load_yaml_settings(config_file)

    assert values == {
        "ragflow_enabled": True,
        "ragflow_base_url": "http://ragflow.local:9380",
        "ragflow_dataset_id": "single-dataset",
        "ragflow_dataset_ids": "alpha, beta",
        "ragflow_top_k": 8,
        "ragflow_similarity_threshold": 0.15,
        "ragflow_vector_similarity_weight": 0.9,
        "ragflow_timeout_seconds": 9.5,
        "ragflow_max_context_chars": 1234,
        "ragflow_fail_open": False,
    }


def test_settings_loads_yaml_values_from_fixed_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
neo4j:
  uri: bolt://neo4j.local:7687
models:
  llm:
    model: yaml-chat
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", config_file)

    settings = SentinelSettings(
        _env_file=(),
        neo4j_password="neo4j-secret",
        llm_api_key="llm-secret",
    )

    assert settings.neo4j_uri == "bolt://neo4j.local:7687"
    assert settings.llm_model == "yaml-chat"


def test_get_settings_ignores_config_file_env(tmp_path, monkeypatch):
    fixed_config = tmp_path / "config.yaml"
    fixed_config.write_text(
        """
neo4j:
  database: fixed-db
""",
        encoding="utf-8",
    )
    ignored_config = tmp_path / "sentinel.yaml"
    ignored_config.write_text(
        """
neo4j:
  database: ignored-db
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", fixed_config)
    monkeypatch.setenv("SENTINEL_CONFIG_FILE", str(ignored_config))
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-secret")
    monkeypatch.setenv("LLM_API_KEY", "llm-secret")
    reset_settings_cache()

    try:
        settings = get_settings()
    finally:
        reset_settings_cache()

    assert settings.neo4j_database == "fixed-db"


def test_resolved_config_file_path_is_fixed(tmp_path, monkeypatch):
    fixed_config = tmp_path / "config.yaml"
    ignored_config = tmp_path / "ignored.yaml"
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "\n".join(
            [
                f"SENTINEL_CONFIG_FILE={ignored_config}",
                "NEO4J_PASSWORD=neo4j-secret",
                "LLM_API_KEY=llm-secret",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", fixed_config)
    monkeypatch.setenv("SENTINEL_CONFIG_FILE", str(ignored_config))

    settings = SentinelSettings(_env_file=dotenv_file)

    assert settings.resolved_config_file_path() == fixed_config


def test_config_paths_are_independent_from_process_cwd(tmp_path):
    code = """
from sentinel.config import DEFAULT_CONFIG_FILE, PROJECT_ROOT
from sentinel.config.profile import PROFILE_CONFIG_DIR
print(PROJECT_ROOT)
print(DEFAULT_CONFIG_FILE)
print(PROFILE_CONFIG_DIR)
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        cwd=tmp_path,
        text=True,
    )

    project_root, config_file, profile_dir = result.stdout.strip().splitlines()
    assert project_root != str(tmp_path)
    assert config_file == str(sentinel_config.DEFAULT_CONFIG_FILE)
    assert profile_dir == str(sentinel_config.PROFILE_CONFIG_DIR)


def test_config_file_env_does_not_select_yaml_file(tmp_path, monkeypatch):
    fixed_config = tmp_path / "config.yaml"
    fixed_config.write_text(
        """
neo4j:
  database: fixed-file-db
""",
        encoding="utf-8",
    )
    ignored_config = tmp_path / "sentinel.yaml"
    ignored_config.write_text(
        """
neo4j:
  database: ignored-db
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", fixed_config)
    monkeypatch.setenv("SENTINEL_CONFIG_FILE", str(ignored_config))

    settings = SentinelSettings(
        _env_file=(),
        neo4j_password="neo4j-secret",
        llm_api_key="llm-secret",
    )

    assert settings.neo4j_database == "fixed-file-db"


def test_dotenv_config_file_env_does_not_select_yaml_file(tmp_path, monkeypatch):
    fixed_config = tmp_path / "config.yaml"
    fixed_config.write_text(
        """
neo4j:
  database: fixed-dotenv-db
""",
        encoding="utf-8",
    )
    ignored_config = tmp_path / "sentinel.yaml"
    ignored_config.write_text(
        """
neo4j:
  database: ignored-db
""",
        encoding="utf-8",
    )
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "\n".join(
            [
                f"SENTINEL_CONFIG_FILE={ignored_config}",
                "NEO4J_PASSWORD=neo4j-secret",
                "LLM_API_KEY=llm-secret",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", fixed_config)

    settings = SentinelSettings(_env_file=dotenv_file)

    assert settings.neo4j_database == "fixed-dotenv-db"


def test_missing_fixed_config_file_is_created_from_template(tmp_path, monkeypatch):
    missing_config = tmp_path / "config.yaml"
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", missing_config)

    settings = SentinelSettings(
        _env_file=(),
        neo4j_password="neo4j-secret",
        llm_api_key="llm-secret",
    )

    assert settings.ragflow_enabled is False
    assert missing_config.exists()
    created = missing_config.read_text(encoding="utf-8")
    assert "ragflow:" in created
    assert "enabled: false" in created


def test_existing_fixed_config_file_is_migrated_without_overwriting_values(
    tmp_path, monkeypatch
):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
neo4j:
  uri: bolt://custom.local:7687
milvus:
  uri: http://custom-milvus.local:19530
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", config_file)

    settings = SentinelSettings(
        _env_file=(),
        neo4j_password="neo4j-secret",
        llm_api_key="llm-secret",
    )

    migrated = config_file.read_text(encoding="utf-8")
    assert settings.neo4j_uri == "bolt://custom.local:7687"
    assert settings.milvus_uri == "http://custom-milvus.local:19530"
    assert settings.ragflow_base_url == "http://127.0.0.1:9380"
    assert "bolt://custom.local:7687" in migrated
    assert "http://custom-milvus.local:19530" in migrated
    assert "ragflow:" in migrated
    assert "fail_open: true" in migrated


def test_default_config_file_is_loaded_when_not_explicitly_isolated(
    tmp_path, monkeypatch
):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
neo4j:
  database: default-file-db
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", config_file)
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-secret")
    monkeypatch.setenv("LLM_API_KEY", "llm-secret")

    settings = SentinelSettings(_env_file=())

    assert settings.neo4j_database == "default-file-db"


def test_env_file_none_isolates_default_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
neo4j:
  database: should-not-load
models:
  llm:
    model: should-not-load-model
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sentinel_config, "DEFAULT_CONFIG_FILE", config_file)

    settings = make_settings()

    assert settings.neo4j_database == "neo4j"
    assert settings.llm_model == "gpt-4o"


def test_migrate_yaml_settings_file_adds_future_defaults(tmp_path):
    config_file = tmp_path / "nested" / "sentinel.yaml"
    template_file = tmp_path / "template.yaml"
    template_file.write_text(
        """
section:
  existing: template-value
  added: default-value
new_section:
  enabled: true
""",
        encoding="utf-8",
    )
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        """
section:
  existing: user-value
""",
        encoding="utf-8",
    )

    changed = migrate_yaml_settings_file(config_file, template_path=template_file)
    changed_again = migrate_yaml_settings_file(config_file, template_path=template_file)
    values = load_yaml_settings(config_file)
    migrated = config_file.read_text(encoding="utf-8")

    assert changed is True
    assert changed_again is False
    assert values == {}
    assert "existing: user-value" in migrated
    assert "added: default-value" in migrated
    assert "new_section:" in migrated
