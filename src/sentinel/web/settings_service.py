"""设置页的运行时配置服务：读写、更新与响应组装。"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

import yaml
from dotenv import dotenv_values
from pydantic import ValidationError

from sentinel.config import (
    SentinelSettings,
    load_yaml_settings,
)
from sentinel.web.settings_models import (
    BatchRuntimePayload,
    BlacklistRuntimePayload,
    EmbedderSettingsPayload,
    GraphitiSettingsPayload,
    LlmSettingsPayload,
    MilvusSettingsPayload,
    ModelsSettingsPayload,
    Neo4jSettingsPayload,
    RerankerSettingsPayload,
    RiskRuntimePayload,
    RuntimeSettingsMetaPayload,
    RuntimeSettingsPayload,
    RuntimeSettingsResponsePayload,
    RuntimeSettingsSecretsPayload,
    RuntimeSettingsUpdatePayload,
    SearchRuntimePayload,
    SecretFieldState,
    ServicesSettingsPayload,
    StashRuntimePayload,
)

EDITABLE_NON_SECRET_ENV_KEYS = {
    "SENTINEL_CONFIG_FILE",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_DATABASE",
    "GRAPHITI_DRY_RUN",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "EMBEDDER_MODEL",
    "EMBEDDER_API_BASE",
    "EMBEDDING_DIM",
    "RERANKER_MODEL",
    "RERANKER_BASE_URL",
    "SEARCH_NUM_RESULTS",
    "RISK_SEARCH_NUM_RESULTS",
    "SEARCH_MIN_SCORE",
    "RISK_THRESHOLD",
    "MILVUS_URI",
    "MILVUS_INPUT_EVENTS_COLLECTION",
    "KV_TTL_DAYS",
    "STASH_SEMANTIC_TOP_K",
    "STASH_RERANK_MIN_SCORE",
    "STASH_RERANK_ENABLED",
    "BATCH_MAX_PER_PERSON",
    "BLACKLIST_EVENT_SIMILARITY_THRESHOLD",
    "BLACKLIST_PERSON_MIN_HITS",
}


class RuntimeSettingsService:
    def __init__(
        self,
        *,
        config_file: Path,
        env_file: Path,
        settings_loader: Callable[[], SentinelSettings],
    ) -> None:
        self._config_file = config_file
        self._env_file = env_file
        self._settings_loader = settings_loader

    def read_runtime_settings(self) -> RuntimeSettingsResponsePayload:
        settings = self._settings_loader()
        return RuntimeSettingsResponsePayload(
            models=ModelsSettingsPayload(
                llm=LlmSettingsPayload(
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    base_url=settings.llm_base_url,
                ),
                embedder=EmbedderSettingsPayload(
                    model=settings.embedder_model,
                    api_base=settings.effective_embedder_api_base,
                    embedding_dim=settings.embedding_dim,
                ),
                reranker=RerankerSettingsPayload(
                    model=settings.effective_reranker_model,
                    base_url=settings.effective_reranker_base_url,
                ),
            ),
            services=ServicesSettingsPayload(
                neo4j=Neo4jSettingsPayload(
                    uri=settings.neo4j_uri,
                    user=settings.neo4j_user,
                    database=settings.neo4j_database,
                ),
                milvus=MilvusSettingsPayload(
                    uri=settings.milvus_uri,
                    input_events_collection=settings.milvus_input_events_collection,
                ),
                graphiti=GraphitiSettingsPayload(dry_run=settings.graphiti_dry_run),
            ),
            runtime=RuntimeSettingsPayload(
                search=SearchRuntimePayload(
                    num_results=settings.search_num_results,
                    risk_num_results=settings.risk_search_num_results,
                    min_score=settings.search_min_score,
                ),
                risk=RiskRuntimePayload(threshold=settings.risk_threshold),
                stash=StashRuntimePayload(
                    kv_ttl_days=settings.kv_ttl_days,
                    semantic_top_k=settings.stash_semantic_top_k,
                    rerank_min_score=settings.stash_rerank_min_score,
                    rerank_enabled=settings.stash_rerank_enabled,
                ),
                batch=BatchRuntimePayload(max_per_person=settings.batch_max_per_person),
                blacklist=BlacklistRuntimePayload(
                    event_similarity_threshold=settings.blacklist_event_similarity_threshold,
                    person_min_hits=settings.blacklist_person_min_hits,
                ),
            ),
            secrets=RuntimeSettingsSecretsPayload(
                neo4j_password=self._secret_state(settings.require_neo4j_password()),
                llm_api_key=self._secret_state(settings.require_llm_api_key()),
                embedder_api_key=self._secret_state(
                    settings.effective_embedder_api_key_value()
                ),
                reranker_api_key=self._secret_state(
                    settings.effective_reranker_api_key_value()
                ),
                milvus_token=self._secret_state(settings.optional_milvus_token()),
            ),
            meta=RuntimeSettingsMetaPayload(updated_at=self._current_updated_at()),
        )

    def current_settings(self) -> SentinelSettings:
        return self._settings_loader()

    def save_runtime_settings(
        self,
        payload: RuntimeSettingsUpdatePayload,
    ) -> RuntimeSettingsResponsePayload:
        yaml_doc = self._read_yaml_document()
        current_settings = self._settings_loader()
        self._reject_process_env_overrides(payload, current_settings)
        env_values = self._read_env_values()
        current_env_lines = (
            self._env_file.read_text(encoding="utf-8").splitlines()
            if self._env_file.exists()
            else []
        )

        yaml_doc["neo4j"] = {
            "uri": payload.services.neo4j.uri,
            "user": payload.services.neo4j.user,
            "database": payload.services.neo4j.database,
        }
        yaml_doc["graphiti"] = {
            "dry_run": payload.services.graphiti.dry_run,
            "episode_source": yaml_doc.get("graphiti", {}).get(
                "episode_source", "sentinel"
            ),
        }
        yaml_doc["models"] = {
            "llm": {
                "provider": payload.models.llm.provider,
                "model": payload.models.llm.model,
                "base_url": payload.models.llm.base_url,
            },
            "embedder": {
                "model": payload.models.embedder.model,
                "dim": payload.models.embedder.embedding_dim,
            },
            "reranker": {},
        }
        embedder_api_base = self._preserve_fallback_value(
            payload.models.embedder.api_base,
            raw_value=current_settings.embedder_api_base,
            effective_value=current_settings.effective_embedder_api_base,
        )
        if embedder_api_base is not None:
            yaml_doc["models"]["embedder"]["api_base"] = embedder_api_base

        reranker_model = self._preserve_fallback_value(
            payload.models.reranker.model,
            raw_value=current_settings.reranker_model,
            effective_value=current_settings.effective_reranker_model,
        )
        if reranker_model is not None:
            yaml_doc["models"]["reranker"]["model"] = reranker_model

        reranker_base_url = self._preserve_fallback_value(
            payload.models.reranker.base_url,
            raw_value=current_settings.reranker_base_url,
            effective_value=current_settings.effective_reranker_base_url,
        )
        if reranker_base_url is not None:
            yaml_doc["models"]["reranker"]["base_url"] = reranker_base_url
        yaml_doc["search"] = {
            "num_results": payload.runtime.search.num_results,
            "risk_num_results": payload.runtime.search.risk_num_results,
            "min_score": payload.runtime.search.min_score,
        }
        yaml_doc["risk"] = {"threshold": payload.runtime.risk.threshold}
        yaml_doc["milvus"] = {
            "uri": payload.services.milvus.uri,
            "input_events_collection": payload.services.milvus.input_events_collection,
            "kv_ttl_days": payload.runtime.stash.kv_ttl_days,
            "stash_semantic_top_k": payload.runtime.stash.semantic_top_k,
            "stash_rerank_min_score": payload.runtime.stash.rerank_min_score,
            "stash_rerank_enabled": payload.runtime.stash.rerank_enabled,
            "batch_max_per_person": payload.runtime.batch.max_per_person,
        }
        yaml_doc["blacklist"] = {
            "event_similarity_threshold": payload.runtime.blacklist.event_similarity_threshold,
            "person_min_hits": payload.runtime.blacklist.person_min_hits,
        }

        persisted_env_values = {
            key: value
            for key, value in env_values.items()
            if key not in EDITABLE_NON_SECRET_ENV_KEYS
        }
        self._set_secret(
            persisted_env_values,
            "NEO4J_PASSWORD",
            payload.services.neo4j.password,
        )
        self._set_secret(
            persisted_env_values,
            "LLM_API_KEY",
            payload.models.llm.api_key,
        )
        self._set_secret(
            persisted_env_values,
            "EMBEDDER_API_KEY",
            payload.models.embedder.api_key,
        )
        self._set_secret(
            persisted_env_values,
            "RERANKER_API_KEY",
            payload.models.reranker.api_key,
        )
        self._set_secret(
            persisted_env_values,
            "MILVUS_TOKEN",
            payload.services.milvus.token,
        )
        self._validate_env_values(persisted_env_values)

        candidate = self._build_candidate_settings(
            yaml_doc,
            persisted_env_values,
            current_settings=current_settings,
        )
        yaml_text = self._render_yaml_document(yaml_doc)
        env_text = self._render_env_values(current_env_lines, persisted_env_values)
        original_yaml_text = (
            self._config_file.read_text(encoding="utf-8")
            if self._config_file.exists()
            else None
        )
        original_env_text = (
            self._env_file.read_text(encoding="utf-8")
            if self._env_file.exists()
            else None
        )

        yaml_temp = self._stage_file(self._config_file, yaml_text)
        try:
            env_temp = self._stage_file(self._env_file, env_text)
        except Exception:
            yaml_temp.unlink(missing_ok=True)
            raise

        self._commit_staged_files(
            yaml_temp,
            env_temp,
            original_yaml_text=original_yaml_text,
            original_env_text=original_env_text,
        )

        self._settings_loader = lambda: candidate
        return self.read_runtime_settings()

    def _build_candidate_settings(
        self,
        yaml_doc: dict[str, Any],
        env_values: dict[str, str],
        *,
        current_settings: SentinelSettings,
    ) -> SentinelSettings:
        merged = load_yaml_settings(self._config_file, required=False)
        merged.update(
            {
                "neo4j_uri": yaml_doc["neo4j"]["uri"],
                "neo4j_user": yaml_doc["neo4j"]["user"],
                "neo4j_database": yaml_doc["neo4j"]["database"],
                "graphiti_dry_run": yaml_doc["graphiti"]["dry_run"],
                "graphiti_episode_source": yaml_doc["graphiti"]["episode_source"],
                "llm_provider": yaml_doc["models"]["llm"]["provider"],
                "llm_model": yaml_doc["models"]["llm"]["model"],
                "llm_base_url": yaml_doc["models"]["llm"]["base_url"],
                "embedder_model": yaml_doc["models"]["embedder"]["model"],
                "embedder_api_base": yaml_doc["models"]["embedder"].get("api_base"),
                "embedding_dim": yaml_doc["models"]["embedder"]["dim"],
                "reranker_model": yaml_doc["models"]["reranker"].get("model"),
                "reranker_base_url": yaml_doc["models"]["reranker"].get("base_url"),
                "search_num_results": yaml_doc["search"]["num_results"],
                "risk_search_num_results": yaml_doc["search"]["risk_num_results"],
                "search_min_score": yaml_doc["search"]["min_score"],
                "risk_threshold": yaml_doc["risk"]["threshold"],
                "milvus_uri": yaml_doc["milvus"]["uri"],
                "milvus_input_events_collection": yaml_doc["milvus"][
                    "input_events_collection"
                ],
                "kv_ttl_days": yaml_doc["milvus"]["kv_ttl_days"],
                "stash_semantic_top_k": yaml_doc["milvus"]["stash_semantic_top_k"],
                "stash_rerank_min_score": yaml_doc["milvus"]["stash_rerank_min_score"],
                "stash_rerank_enabled": yaml_doc["milvus"]["stash_rerank_enabled"],
                "batch_max_per_person": yaml_doc["milvus"]["batch_max_per_person"],
                "blacklist_event_similarity_threshold": yaml_doc["blacklist"][
                    "event_similarity_threshold"
                ],
                "blacklist_person_min_hits": yaml_doc["blacklist"]["person_min_hits"],
                "neo4j_password": env_values.get("NEO4J_PASSWORD")
                or current_settings.require_neo4j_password(),
                "llm_api_key": env_values.get("LLM_API_KEY")
                or current_settings.require_llm_api_key(),
                "dashboard_admin_password": env_values.get("DASHBOARD_ADMIN_PASSWORD")
                or current_settings.optional_dashboard_admin_password(),
                "dashboard_access_token": env_values.get("DASHBOARD_ACCESS_TOKEN")
                or current_settings.optional_dashboard_access_token(),
                "dashboard_refresh_token": env_values.get("DASHBOARD_REFRESH_TOKEN")
                or current_settings.optional_dashboard_refresh_token(),
                "embedder_api_key": env_values.get("EMBEDDER_API_KEY")
                or current_settings._optional_secret_value(
                    current_settings.embedder_api_key
                ),
                "reranker_api_key": env_values.get("RERANKER_API_KEY")
                or current_settings._optional_secret_value(
                    current_settings.reranker_api_key
                ),
                "milvus_token": env_values.get("MILVUS_TOKEN")
                or current_settings.optional_milvus_token(),
            }
        )
        try:
            return SentinelSettings(_env_file=None, **merged)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _secret_state(value: str | None) -> SecretFieldState:
        if not value:
            return SecretFieldState(configured=False, masked_hint=None)
        return SecretFieldState(configured=True, masked_hint="****")

    @staticmethod
    def _set_secret(
        env_values: dict[str, str],
        key: str,
        value: str,
    ) -> None:
        if value and value.strip():
            env_values[key] = value

    @staticmethod
    def _validate_env_values(env_values: dict[str, str]) -> None:
        for key, value in env_values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"{key} cannot contain newlines")
            if "${" in value:
                raise ValueError(f"{key} cannot contain dotenv interpolation syntax")

    @classmethod
    def _reject_process_env_overrides(
        cls,
        payload: RuntimeSettingsUpdatePayload,
        current_settings: SentinelSettings,
    ) -> None:
        changed = cls._changed_non_secret_env_keys(payload, current_settings)
        configured = sorted(changed.intersection(os.environ))
        if configured:
            names = ", ".join(configured)
            raise ValueError(
                f"{names} are set in process environment and cannot be changed "
                "from Web Settings"
            )

    @staticmethod
    def _changed_non_secret_env_keys(
        payload: RuntimeSettingsUpdatePayload,
        current_settings: SentinelSettings,
    ) -> set[str]:
        changed: set[str] = set()

        comparisons: list[tuple[str, Any, Any]] = [
            ("NEO4J_URI", payload.services.neo4j.uri, current_settings.neo4j_uri),
            ("NEO4J_USER", payload.services.neo4j.user, current_settings.neo4j_user),
            (
                "NEO4J_DATABASE",
                payload.services.neo4j.database,
                current_settings.neo4j_database,
            ),
            (
                "GRAPHITI_DRY_RUN",
                payload.services.graphiti.dry_run,
                current_settings.graphiti_dry_run,
            ),
            (
                "LLM_PROVIDER",
                payload.models.llm.provider,
                current_settings.llm_provider,
            ),
            ("LLM_MODEL", payload.models.llm.model, current_settings.llm_model),
            (
                "LLM_BASE_URL",
                payload.models.llm.base_url,
                current_settings.llm_base_url,
            ),
            (
                "EMBEDDER_MODEL",
                payload.models.embedder.model,
                current_settings.embedder_model,
            ),
            (
                "EMBEDDER_API_BASE",
                payload.models.embedder.api_base,
                current_settings.effective_embedder_api_base,
            ),
            (
                "EMBEDDING_DIM",
                payload.models.embedder.embedding_dim,
                current_settings.embedding_dim,
            ),
            (
                "RERANKER_MODEL",
                payload.models.reranker.model,
                current_settings.effective_reranker_model,
            ),
            (
                "RERANKER_BASE_URL",
                payload.models.reranker.base_url,
                current_settings.effective_reranker_base_url,
            ),
            (
                "SEARCH_NUM_RESULTS",
                payload.runtime.search.num_results,
                current_settings.search_num_results,
            ),
            (
                "RISK_SEARCH_NUM_RESULTS",
                payload.runtime.search.risk_num_results,
                current_settings.risk_search_num_results,
            ),
            (
                "SEARCH_MIN_SCORE",
                payload.runtime.search.min_score,
                current_settings.search_min_score,
            ),
            (
                "RISK_THRESHOLD",
                payload.runtime.risk.threshold,
                current_settings.risk_threshold,
            ),
            ("MILVUS_URI", payload.services.milvus.uri, current_settings.milvus_uri),
            (
                "MILVUS_INPUT_EVENTS_COLLECTION",
                payload.services.milvus.input_events_collection,
                current_settings.milvus_input_events_collection,
            ),
            (
                "KV_TTL_DAYS",
                payload.runtime.stash.kv_ttl_days,
                current_settings.kv_ttl_days,
            ),
            (
                "STASH_SEMANTIC_TOP_K",
                payload.runtime.stash.semantic_top_k,
                current_settings.stash_semantic_top_k,
            ),
            (
                "STASH_RERANK_MIN_SCORE",
                payload.runtime.stash.rerank_min_score,
                current_settings.stash_rerank_min_score,
            ),
            (
                "STASH_RERANK_ENABLED",
                payload.runtime.stash.rerank_enabled,
                current_settings.stash_rerank_enabled,
            ),
            (
                "BATCH_MAX_PER_PERSON",
                payload.runtime.batch.max_per_person,
                current_settings.batch_max_per_person,
            ),
            (
                "BLACKLIST_EVENT_SIMILARITY_THRESHOLD",
                payload.runtime.blacklist.event_similarity_threshold,
                current_settings.blacklist_event_similarity_threshold,
            ),
            (
                "BLACKLIST_PERSON_MIN_HITS",
                payload.runtime.blacklist.person_min_hits,
                current_settings.blacklist_person_min_hits,
            ),
        ]

        for key, submitted, current in comparisons:
            if submitted != current:
                changed.add(key)
        return changed

    @staticmethod
    def _preserve_fallback_value(
        submitted_value: str,
        *,
        raw_value: str | None,
        effective_value: str,
    ) -> str | None:
        normalized = submitted_value.strip()
        if raw_value is None and normalized == effective_value:
            return None
        return normalized or raw_value

    def _read_yaml_document(self) -> dict[str, Any]:
        if not self._config_file.exists():
            return {}
        with self._config_file.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return raw if isinstance(raw, dict) else {}

    def _render_yaml_document(self, yaml_doc: dict[str, Any]) -> str:
        return yaml.safe_dump(yaml_doc, allow_unicode=True, sort_keys=False)

    def _stage_file(self, target: Path, content: str) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=target.parent,
            suffix=".tmp",
        ) as handle:
            handle.write(content)
            return Path(handle.name)

    def _read_env_values(self) -> dict[str, str]:
        if not self._env_file.exists():
            return {}
        return {
            key: value
            for key, value in dotenv_values(
                self._env_file,
                interpolate=False,
            ).items()
            if value is not None
        }

    @staticmethod
    def _format_env_value(value: str) -> str:
        if all(char not in value for char in (" ", "#", '"', "'", "\t", "\n")):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _render_env_values(
        self,
        current_lines: list[str],
        env_values: dict[str, str],
    ) -> str:
        ordered_keys: list[str] = []
        rendered_lines: list[str] = []

        for raw_line in current_lines:
            stripped = raw_line.lstrip()
            if not raw_line or stripped.startswith("#") or "=" not in raw_line:
                rendered_lines.append(raw_line)
                continue
            key = self._env_line_key(raw_line)
            if key in EDITABLE_NON_SECRET_ENV_KEYS:
                continue
            if key in env_values:
                rendered_lines.append(
                    f"{key}={self._format_env_value(env_values[key])}"
                )
                ordered_keys.append(key)
            else:
                rendered_lines.append(raw_line)

        for key, value in sorted(env_values.items()):
            if key in ordered_keys:
                continue
            rendered_lines.append(f"{key}={self._format_env_value(value)}")

        return "\n".join(rendered_lines).rstrip() + "\n"

    @staticmethod
    def _env_line_key(raw_line: str) -> str | None:
        key, _ = raw_line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        return key or None

    def _commit_staged_files(
        self,
        yaml_temp: Path,
        env_temp: Path,
        *,
        original_yaml_text: str | None,
        original_env_text: str | None,
    ) -> None:
        try:
            yaml_temp.replace(self._config_file)
            env_temp.replace(self._env_file)
            os.chmod(self._env_file, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            self._restore_file(self._config_file, original_yaml_text)
            self._restore_file(self._env_file, original_env_text)
            raise
        finally:
            yaml_temp.unlink(missing_ok=True)
            env_temp.unlink(missing_ok=True)

    @staticmethod
    def _restore_file(target: Path, original_text: str | None) -> None:
        if original_text is None:
            target.unlink(missing_ok=True)
            return
        target.write_text(original_text, encoding="utf-8")

    def _current_updated_at(self) -> str:
        runtime_settings = getattr(
            getattr(self._settings_loader, "__self__", None),
            "get_updated_at",
            None,
        )
        if callable(runtime_settings):
            return runtime_settings()
        return datetime.now().isoformat(timespec="seconds")

    @classmethod
    def from_active_settings(
        cls,
        settings_loader: Callable[[], SentinelSettings],
        active_settings: SentinelSettings | None = None,
    ) -> RuntimeSettingsService:
        settings = active_settings or settings_loader()
        env_file = settings.resolved_env_file_path() or Path.cwd() / ".env"
        config_file = settings.resolved_config_file_path()
        return cls(
            config_file=config_file,
            env_file=env_file,
            settings_loader=settings_loader,
        )
