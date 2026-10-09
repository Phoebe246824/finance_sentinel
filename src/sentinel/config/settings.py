"""Application settings and structured YAML configuration loading."""

import os
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from sys import modules
from typing import Any

from pydantic import SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from sentinel.config.yaml_source import StructuredYamlSettingsSource
from sentinel.config.yaml_source import load_yaml_settings as _load_yaml_settings
from sentinel.config.yaml_source import (
    migrate_yaml_settings_file as _migrate_yaml_settings_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_CONFIG_TEMPLATE = PROJECT_ROOT / "config" / "config.example.yaml"
_LOAD_DEFAULT_CONFIG_FILE: ContextVar[bool] = ContextVar(
    "sentinel_load_default_config_file",
    default=True,
)


def _public_default_config_file() -> Path:
    package = modules.get("sentinel.config")
    if package is None:
        return DEFAULT_CONFIG_FILE
    value = getattr(package, "DEFAULT_CONFIG_FILE", DEFAULT_CONFIG_FILE)
    return Path(value)


def _public_default_config_template() -> Path:
    package = modules.get("sentinel.config")
    if package is None:
        return DEFAULT_CONFIG_TEMPLATE
    value = getattr(package, "DEFAULT_CONFIG_TEMPLATE", DEFAULT_CONFIG_TEMPLATE)
    return Path(value)


def migrate_yaml_settings_file(
    path: str | os.PathLike[str],
    *,
    template_path: str | os.PathLike[str] | None = None,
) -> bool:
    return _migrate_yaml_settings_file(
        path,
        template_path=(
            _public_default_config_template()
            if template_path is None
            else template_path
        ),
    )


def load_yaml_settings(
    path: str | os.PathLike[str] | None,
    *,
    required: bool = False,
) -> dict[str, Any]:
    return _load_yaml_settings(path, required=required)


class SentinelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr
    neo4j_database: str = "neo4j"
    graphiti_dry_run: bool = False
    graphiti_episode_source: str = "sentinel"

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: SecretStr
    llm_base_url: str = "https://api.openai.com/v1"

    embedder_model: str = "BAAI/bge-m3"
    embedder_api_key: SecretStr | None = None
    embedder_api_base: str | None = None
    embedding_dim: int = 1024

    reranker_model: str | None = None
    reranker_api_key: SecretStr | None = None
    reranker_base_url: str | None = None

    search_num_results: int = 10
    risk_search_num_results: int = 20
    search_min_score: float = 0.0

    risk_threshold: float = 0.7

    milvus_uri: str = "http://localhost:19530"
    milvus_token: SecretStr | None = None
    milvus_input_events_collection: str = "input_events"
    kv_ttl_days: int = 90
    stash_semantic_top_k: int = 10
    stash_rerank_min_score: float = 0.7
    stash_rerank_enabled: bool = True
    batch_max_per_person: int = 20

    blacklist_event_similarity_threshold: float = 0.5
    blacklist_person_min_hits: int = 1

    dashboard_admin_user: str = "admin"
    dashboard_admin_password: SecretStr | None = None
    dashboard_access_token: SecretStr | None = None
    dashboard_refresh_token: SecretStr | None = None

    ragflow_enabled: bool = False
    ragflow_base_url: str = "http://127.0.0.1:9380"
    ragflow_api_key: SecretStr | None = None
    ragflow_dataset_id: str | None = None
    ragflow_dataset_ids: str | None = None
    ragflow_top_k: int = 5
    ragflow_similarity_threshold: float = 0.2
    ragflow_vector_similarity_weight: float = 0.7
    ragflow_timeout_seconds: float = 15.0
    ragflow_max_context_chars: int = 4000
    ragflow_fail_open: bool = True

    def __init__(self, **values: Any) -> None:
        load_default_config = values.get("_env_file", ...) is not None
        token = _LOAD_DEFAULT_CONFIG_FILE.set(load_default_config)
        try:
            super().__init__(**values)
        finally:
            _LOAD_DEFAULT_CONFIG_FILE.reset(token)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            StructuredYamlSettingsSource(
                settings_cls,
                load_default_config_file=_LOAD_DEFAULT_CONFIG_FILE,
                default_config_file=_public_default_config_file,
                migrate_settings_file=migrate_yaml_settings_file,
            ),
            file_secret_settings,
        )

    @field_validator(
        "neo4j_password",
        "llm_api_key",
    )
    @classmethod
    def _required_secret_must_not_be_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("required secret cannot be empty")
        return value

    @staticmethod
    def _optional_secret_value(value: SecretStr | None) -> str | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        return raw or None

    def require_llm_api_key(self) -> str:
        return self.llm_api_key.get_secret_value()

    def require_neo4j_password(self) -> str:
        return self.neo4j_password.get_secret_value()

    def effective_embedder_api_key_value(self) -> str:
        return (
            self._optional_secret_value(self.embedder_api_key)
            or self.require_llm_api_key()
        )

    def effective_reranker_api_key_value(self) -> str:
        return (
            self._optional_secret_value(self.reranker_api_key)
            or self.require_llm_api_key()
        )

    def optional_milvus_token(self) -> str | None:
        return self._optional_secret_value(self.milvus_token)

    def optional_dashboard_admin_password(self) -> str | None:
        return self._optional_secret_value(self.dashboard_admin_password)

    def optional_dashboard_access_token(self) -> str | None:
        return self._optional_secret_value(self.dashboard_access_token)

    def optional_dashboard_refresh_token(self) -> str | None:
        return self._optional_secret_value(self.dashboard_refresh_token)

    def optional_ragflow_api_key(self) -> str | None:
        return self._optional_secret_value(self.ragflow_api_key)

    def ragflow_dataset_id_list(self) -> list[str]:
        raw = self.ragflow_dataset_ids or self.ragflow_dataset_id or ""
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def effective_embedder_api_base(self) -> str:
        return self.embedder_api_base or self.llm_base_url

    @property
    def effective_reranker_base_url(self) -> str:
        return self.reranker_base_url or self.llm_base_url

    @property
    def effective_reranker_model(self) -> str:
        return self.reranker_model or "BAAI/bge-reranker-v2-m3"

    def resolved_env_file_path(self) -> Path | None:
        env_file = self.model_config.get("env_file")
        if env_file is None:
            return None
        return Path(env_file)

    def resolved_config_file_path(self) -> Path:
        return _public_default_config_file()


@lru_cache(maxsize=1)
def get_settings() -> SentinelSettings:
    return SentinelSettings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
