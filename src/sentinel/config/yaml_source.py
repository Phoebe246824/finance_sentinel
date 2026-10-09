"""Structured YAML Settings source helpers."""

import os
from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, InitSettingsSource

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_CONFIG_TEMPLATE = PROJECT_ROOT / "config" / "config.example.yaml"
INPUT_EVENTS_COLLECTION_KEY = "input_events_collection"
LEGACY_STASH_COLLECTION_KEY = "stash_collection"
_LOAD_DEFAULT_CONFIG_FILE: ContextVar[bool] = ContextVar(
    "sentinel_load_default_config_file_fallback",
    default=True,
)

YAML_SETTINGS_MAP = {
    ("neo4j", "uri"): "neo4j_uri",
    ("neo4j", "user"): "neo4j_user",
    ("neo4j", "database"): "neo4j_database",
    ("graphiti", "dry_run"): "graphiti_dry_run",
    ("graphiti", "episode_source"): "graphiti_episode_source",
    ("models", "llm", "provider"): "llm_provider",
    ("models", "llm", "model"): "llm_model",
    ("models", "llm", "base_url"): "llm_base_url",
    ("models", "embedder", "model"): "embedder_model",
    ("models", "embedder", "api_base"): "embedder_api_base",
    ("models", "embedder", "dim"): "embedding_dim",
    ("models", "reranker", "model"): "reranker_model",
    ("models", "reranker", "base_url"): "reranker_base_url",
    ("search", "num_results"): "search_num_results",
    ("search", "risk_num_results"): "risk_search_num_results",
    ("search", "min_score"): "search_min_score",
    ("risk", "threshold"): "risk_threshold",
    ("milvus", "uri"): "milvus_uri",
    ("milvus", "input_events_collection"): "milvus_input_events_collection",
    ("milvus", "kv_ttl_days"): "kv_ttl_days",
    ("milvus", "stash_semantic_top_k"): "stash_semantic_top_k",
    ("milvus", "stash_rerank_min_score"): "stash_rerank_min_score",
    ("milvus", "stash_rerank_enabled"): "stash_rerank_enabled",
    ("milvus", "batch_max_per_person"): "batch_max_per_person",
    ("blacklist", "event_similarity_threshold"): (
        "blacklist_event_similarity_threshold"
    ),
    ("blacklist", "person_min_hits"): "blacklist_person_min_hits",
    ("dashboard", "admin_user"): "dashboard_admin_user",
    ("ragflow", "enabled"): "ragflow_enabled",
    ("ragflow", "base_url"): "ragflow_base_url",
    ("ragflow", "dataset_id"): "ragflow_dataset_id",
    ("ragflow", "dataset_ids"): "ragflow_dataset_ids",
    ("ragflow", "top_k"): "ragflow_top_k",
    ("ragflow", "similarity_threshold"): "ragflow_similarity_threshold",
    ("ragflow", "vector_similarity_weight"): "ragflow_vector_similarity_weight",
    ("ragflow", "timeout_seconds"): "ragflow_timeout_seconds",
    ("ragflow", "max_context_chars"): "ragflow_max_context_chars",
    ("ragflow", "fail_open"): "ragflow_fail_open",
}


def _nested_get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"YAML settings file must contain a mapping: {path}")
    return raw


def _merge_missing_defaults(
    current: dict[str, Any],
    template: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    migrated = deepcopy(current)
    changed = False
    for key, template_value in template.items():
        if key not in migrated:
            migrated[key] = deepcopy(template_value)
            changed = True
            continue
        current_value = migrated[key]
        if isinstance(current_value, dict) and isinstance(template_value, dict):
            merged_value, nested_changed = _merge_missing_defaults(
                current_value,
                template_value,
            )
            migrated[key] = merged_value
            changed = changed or nested_changed
    return migrated, changed


def _migrate_input_events_collection(
    current: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    migrated = deepcopy(current)
    milvus_config = migrated.get("milvus")
    if not isinstance(milvus_config, dict):
        return migrated, False

    legacy_value = milvus_config.get(LEGACY_STASH_COLLECTION_KEY)
    if legacy_value is None:
        return migrated, False

    if INPUT_EVENTS_COLLECTION_KEY not in milvus_config:
        milvus_config[INPUT_EVENTS_COLLECTION_KEY] = legacy_value
    milvus_config.pop(LEGACY_STASH_COLLECTION_KEY, None)
    return migrated, True


def migrate_yaml_settings_file(
    path: str | os.PathLike[str],
    *,
    template_path: str | os.PathLike[str],
) -> bool:
    config_path = Path(path)
    template_file = Path(template_path)
    template = _load_yaml_mapping(template_file)
    current = _load_yaml_mapping(config_path) if config_path.exists() else {}

    migrated, changed = _migrate_input_events_collection(current)
    migrated, defaults_changed = _merge_missing_defaults(migrated, template)
    changed = changed or defaults_changed
    if not changed and config_path.exists():
        return False

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            migrated,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return True


def load_yaml_settings(
    path: str | os.PathLike[str] | None,
    *,
    required: bool = False,
) -> dict[str, Any]:
    if path is None:
        return {}

    config_path = Path(path)
    if not config_path.exists():
        if required:
            raise FileNotFoundError(f"YAML settings file not found: {config_path}")
        return {}

    raw = _load_yaml_mapping(config_path)
    raw, _ = _migrate_input_events_collection(raw)

    values: dict[str, Any] = {}
    for yaml_path, field_name in YAML_SETTINGS_MAP.items():
        value = _nested_get(raw, yaml_path)
        if value is not None:
            values[field_name] = value
    return values


class StructuredYamlSettingsSource(InitSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        *,
        load_default_config_file: ContextVar[bool] = _LOAD_DEFAULT_CONFIG_FILE,
        default_config_file: Callable[[], Path] | None = None,
        migrate_settings_file: Callable[[str | os.PathLike[str]], bool] | None = None,
    ) -> None:
        super().__init__(settings_cls, {})
        self._load_default_config_file = load_default_config_file
        self._default_config_file = default_config_file or (lambda: DEFAULT_CONFIG_FILE)
        self._migrate_settings_file = migrate_settings_file or (
            lambda path: migrate_yaml_settings_file(
                path,
                template_path=DEFAULT_CONFIG_TEMPLATE,
            )
        )

    def __call__(self) -> dict[str, Any]:
        if not self._load_default_config_file.get():
            return {}
        default_config_file = self._default_config_file()
        self._migrate_settings_file(default_config_file)
        return load_yaml_settings(default_config_file, required=False)
