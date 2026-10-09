"""设置页的配置数据模型与校验。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HttpUrlStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^https?://",
    ),
]
Neo4jUriStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^(bolt|neo4j)(\+s|\+ssc)?://",
    ),
]
MilvusCollectionStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    ),
]


class SecretFieldState(BaseModel):
    configured: bool = False
    masked_hint: str | None = None


class LlmSettingsPayload(BaseModel):
    provider: str
    model: str
    base_url: str


class EmbedderSettingsPayload(BaseModel):
    model: str
    api_base: str
    embedding_dim: int


class RerankerSettingsPayload(BaseModel):
    model: str
    base_url: str


class ModelsSettingsPayload(BaseModel):
    llm: LlmSettingsPayload
    embedder: EmbedderSettingsPayload
    reranker: RerankerSettingsPayload


class Neo4jSettingsPayload(BaseModel):
    uri: str
    user: str
    database: str


class MilvusSettingsPayload(BaseModel):
    uri: str
    input_events_collection: str


class GraphitiSettingsPayload(BaseModel):
    dry_run: bool


class ServicesSettingsPayload(BaseModel):
    neo4j: Neo4jSettingsPayload
    milvus: MilvusSettingsPayload
    graphiti: GraphitiSettingsPayload


class SearchRuntimePayload(BaseModel):
    num_results: int
    risk_num_results: int
    min_score: float


class RiskRuntimePayload(BaseModel):
    threshold: float


class StashRuntimePayload(BaseModel):
    kv_ttl_days: int
    semantic_top_k: int
    rerank_min_score: float
    rerank_enabled: bool


class BatchRuntimePayload(BaseModel):
    max_per_person: int


class BlacklistRuntimePayload(BaseModel):
    event_similarity_threshold: float
    person_min_hits: int


class RuntimeSettingsPayload(BaseModel):
    search: SearchRuntimePayload
    risk: RiskRuntimePayload
    stash: StashRuntimePayload
    batch: BatchRuntimePayload
    blacklist: BlacklistRuntimePayload


class RuntimeSettingsSecretsPayload(BaseModel):
    neo4j_password: SecretFieldState
    llm_api_key: SecretFieldState
    embedder_api_key: SecretFieldState
    reranker_api_key: SecretFieldState
    milvus_token: SecretFieldState


class RuntimeSettingsMetaPayload(BaseModel):
    updated_at: str


class RuntimeSettingsResponsePayload(BaseModel):
    models: ModelsSettingsPayload
    services: ServicesSettingsPayload
    runtime: RuntimeSettingsPayload
    secrets: RuntimeSettingsSecretsPayload
    meta: RuntimeSettingsMetaPayload


class LlmSettingsUpdatePayload(BaseModel):
    provider: NonBlankStr
    model: NonBlankStr
    base_url: HttpUrlStr
    api_key: str = ""


class EmbedderSettingsUpdatePayload(BaseModel):
    model: NonBlankStr
    api_base: HttpUrlStr
    api_key: str = ""
    embedding_dim: int = Field(ge=1, le=65535)


class RerankerSettingsUpdatePayload(BaseModel):
    model: NonBlankStr
    base_url: HttpUrlStr
    api_key: str = ""


class ModelsSettingsUpdatePayload(BaseModel):
    llm: LlmSettingsUpdatePayload
    embedder: EmbedderSettingsUpdatePayload
    reranker: RerankerSettingsUpdatePayload


class Neo4jSettingsUpdatePayload(BaseModel):
    uri: Neo4jUriStr
    user: NonBlankStr
    password: str = ""
    database: NonBlankStr


class MilvusSettingsUpdatePayload(BaseModel):
    uri: NonBlankStr
    token: str = ""
    input_events_collection: MilvusCollectionStr


class GraphitiSettingsUpdatePayload(BaseModel):
    dry_run: bool


class ServicesSettingsUpdatePayload(BaseModel):
    neo4j: Neo4jSettingsUpdatePayload
    milvus: MilvusSettingsUpdatePayload
    graphiti: GraphitiSettingsUpdatePayload


class SearchRuntimeUpdatePayload(BaseModel):
    num_results: int = Field(ge=1, le=500)
    risk_num_results: int = Field(ge=1, le=500)
    min_score: float = Field(ge=0.0, le=1.0)


class RiskRuntimeUpdatePayload(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)


class StashRuntimeUpdatePayload(BaseModel):
    kv_ttl_days: int = Field(ge=1, le=3650)
    semantic_top_k: int = Field(ge=1, le=500)
    rerank_min_score: float = Field(ge=0.0, le=1.0)
    rerank_enabled: bool


class BatchRuntimeUpdatePayload(BaseModel):
    max_per_person: int = Field(ge=1, le=500)


class BlacklistRuntimeUpdatePayload(BaseModel):
    event_similarity_threshold: float = Field(ge=0.0, le=1.0)
    person_min_hits: int = Field(ge=1, le=100)


class RuntimeSettingsSectionUpdatePayload(BaseModel):
    search: SearchRuntimeUpdatePayload
    risk: RiskRuntimeUpdatePayload
    stash: StashRuntimeUpdatePayload
    batch: BatchRuntimeUpdatePayload
    blacklist: BlacklistRuntimeUpdatePayload


class RuntimeSettingsUpdatePayload(BaseModel):
    models: ModelsSettingsUpdatePayload
    services: ServicesSettingsUpdatePayload
    runtime: RuntimeSettingsSectionUpdatePayload
