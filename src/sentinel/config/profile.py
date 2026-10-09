"""Runtime profile configuration loading."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Generic, Literal, TypeVar, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, create_model
from pydantic_core import CoreSchema, core_schema

from sentinel.config.settings import PROJECT_ROOT

type YamlValue = (
    str | int | float | bool | None | list[YamlValue] | dict[str, YamlValue]
)

PROFILE_CONFIG_DIR: Final = PROJECT_ROOT / "config" / "profile"
KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


@dataclass(frozen=True, slots=True, init=False, eq=False)
class FrozenMapping(Mapping[KeyT, ValueT], Generic[KeyT, ValueT]):
    """Tuple-backed immutable mapping with typed Pydantic serialization."""

    _items: tuple[tuple[KeyT, ValueT], ...]

    def __init__(self, values: Mapping[KeyT, ValueT] | None = None) -> None:
        object.__setattr__(self, "_items", tuple((values or {}).items()))

    def __getitem__(self, key: KeyT) -> ValueT:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[KeyT]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: object,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        key_type, value_type = get_args(source_type)
        mapping_schema = handler.generate_schema(dict[key_type, value_type])
        return core_schema.no_info_after_validator_function(
            cls,
            mapping_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: dict(value.items()),
                return_schema=mapping_schema,
            ),
        )


class FrozenProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PromptRenderError(ValueError):
    """Raised when a profile prompt cannot be rendered."""


class PromptTemplate(FrozenProfileModel):
    logical_name: str
    source_path: Path
    body: str


class GraphTypeConfig(FrozenProfileModel):
    name: str
    description: str
    fields: FrozenMapping[str, str] = Field(default_factory=FrozenMapping)


class EdgeTypeMapEntry(FrozenProfileModel):
    source: str
    target: str
    edges: tuple[str, ...]


class GraphProfileConfig(FrozenProfileModel):
    entities: tuple[GraphTypeConfig, ...]
    edges: tuple[GraphTypeConfig, ...]
    edge_type_map: tuple[EdgeTypeMapEntry, ...]


class ClassificationCategoryConfig(FrozenProfileModel):
    display_name: str
    keywords: tuple[str, ...] = Field(default_factory=tuple)


class ClassificationProfileConfig(FrozenProfileModel):
    default_event_type: str = "information_event"
    summary_instruction: str = "Summarize the event in one sentence."
    categories: FrozenMapping[str, ClassificationCategoryConfig] = Field(
        default_factory=FrozenMapping
    )


class RiskProfileConfig(FrozenProfileModel):
    dimensions: FrozenMapping[str, str]


class DashboardProfileConfig(FrozenProfileModel):
    force_category: str | None = None
    force_category_confidence: float = 1.0
    analysis_target: str = "General event impact and response."


class PipelinePromptPathConfig(FrozenProfileModel):
    normalization: str
    graph_extraction: str
    classification: str
    risk_first: str
    risk_second: str


class DashboardPromptPairPathConfig(FrozenProfileModel):
    intent_analysis: str
    trend_prediction: str


class DashboardPromptPathConfig(FrozenProfileModel):
    general: DashboardPromptPairPathConfig
    categories: dict[str, DashboardPromptPairPathConfig] = Field(default_factory=dict)


class PromptPathConfig(FrozenProfileModel):
    pipeline: PipelinePromptPathConfig
    dashboard: DashboardPromptPathConfig


class LoadedPipelinePrompts(FrozenProfileModel):
    normalization: PromptTemplate
    graph_extraction: PromptTemplate
    classification: PromptTemplate
    risk_first: PromptTemplate
    risk_second: PromptTemplate


class LoadedDashboardPromptPair(FrozenProfileModel):
    intent_analysis: PromptTemplate
    trend_prediction: PromptTemplate


class LoadedDashboardPrompts(FrozenProfileModel):
    general: LoadedDashboardPromptPair
    categories: FrozenMapping[str, LoadedDashboardPromptPair] = Field(
        default_factory=FrozenMapping
    )

    def resolve(self, category: str) -> tuple[str, LoadedDashboardPromptPair]:
        prompts = self.categories.get(category)
        if prompts is not None:
            return category, prompts
        return "general", self.general


class LoadedPrompts(FrozenProfileModel):
    pipeline: LoadedPipelinePrompts
    dashboard: LoadedDashboardPrompts


class ProfileConfig(FrozenProfileModel):
    id: str
    display_name: str
    description: str = ""
    graph: GraphProfileConfig
    risk: RiskProfileConfig
    classification: ClassificationProfileConfig
    dashboard: DashboardProfileConfig = Field(default_factory=DashboardProfileConfig)
    prompts: LoadedPrompts

    def graphiti_extraction_config(
        self,
    ) -> tuple[
        dict[str, type[BaseModel]],
        dict[str, type[BaseModel]],
        dict[tuple[str, str], list[str]],
    ]:
        entity_types = {
            entity.name: _create_graphiti_model(entity)
            for entity in self.graph.entities
        }
        edge_types = {
            edge.name: _create_graphiti_model(edge) for edge in self.graph.edges
        }
        edge_type_map = {
            (entry.source, entry.target): list(entry.edges)
            for entry in self.graph.edge_type_map
        }
        edge_type_map.setdefault(("Entity", "Entity"), list(edge_types))
        return entity_types, edge_types, edge_type_map


class RawProfileConfig(FrozenProfileModel):
    id: str
    display_name: str
    description: str = ""
    graph: GraphProfileConfig
    risk: RiskProfileConfig
    classification: ClassificationProfileConfig
    dashboard: DashboardProfileConfig = Field(default_factory=DashboardProfileConfig)
    prompts: PromptPathConfig


def _duplicate_name(
    graph_types: tuple[GraphTypeConfig, ...],
) -> str | None:
    seen: set[str] = set()
    for graph_type in graph_types:
        if graph_type.name in seen:
            return graph_type.name
        seen.add(graph_type.name)
    return None


def _type_names(graph_types: tuple[GraphTypeConfig, ...]) -> set[str]:
    return {graph_type.name for graph_type in graph_types}


def _validate_graph_type_names(graph: GraphProfileConfig) -> None:
    duplicate_entity = _duplicate_name(graph.entities)
    if duplicate_entity is not None:
        raise ValueError(f"duplicate graph entity name: {duplicate_entity}")
    duplicate_edge = _duplicate_name(graph.edges)
    if duplicate_edge is not None:
        raise ValueError(f"duplicate graph edge name: {duplicate_edge}")


def _raise_unknown_graph_reference(
    *,
    reference_kind: Literal["source entity", "target entity", "edge type"],
    reference_name: str,
) -> None:
    raise ValueError(
        f"unknown {reference_kind} in profile edge_type_map: {reference_name}"
    )


def _validate_edge_type_map(graph: GraphProfileConfig) -> None:
    entity_names = _type_names(graph.entities)
    edge_names = _type_names(graph.edges)
    for entry in graph.edge_type_map:
        if entry.source not in entity_names:
            _raise_unknown_graph_reference(
                reference_kind="source entity",
                reference_name=entry.source,
            )
        if entry.target not in entity_names:
            _raise_unknown_graph_reference(
                reference_kind="target entity",
                reference_name=entry.target,
            )
        for edge_name in entry.edges:
            if edge_name not in edge_names:
                _raise_unknown_graph_reference(
                    reference_kind="edge type",
                    reference_name=edge_name,
                )


def _validate_graph_profile(graph: GraphProfileConfig) -> None:
    _validate_graph_type_names(graph)
    _validate_edge_type_map(graph)


def _create_graphiti_model(graph_type: GraphTypeConfig) -> type[BaseModel]:
    field_definitions = {
        field_name: (
            str | None,
            Field(None, description=field_description),
        )
        for field_name, field_description in graph_type.fields.items()
    }
    model = create_model(
        graph_type.name,
        __base__=BaseModel,
        __doc__=graph_type.description,
        **field_definitions,
    )
    return model


def _read_yaml_mapping(path: Path) -> Mapping[str, YamlValue]:
    if not path.exists():
        raise FileNotFoundError(f"profile YAML file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"profile YAML must contain a mapping: {path}")
    return raw


def render_prompt(template: PromptTemplate, **values: object) -> str:
    try:
        return template.body.format_map(values)
    except Exception as exc:
        render_error = PromptRenderError(
            f"failed to render prompt {template.logical_name} from "
            f"{template.source_path}: {type(exc).__name__}"
        )
    raise render_error


def _read_prompt(
    root: Path,
    logical_name: str,
    relative_path: str,
) -> PromptTemplate:
    prompt_path = Path(relative_path)
    if prompt_path.is_absolute():
        raise ValueError(f"profile prompt path must be relative: {relative_path}")
    resolved_root = root.resolve()
    path = (root / prompt_path).resolve(strict=False)
    if not path.is_relative_to(resolved_root):
        raise ValueError(
            f"profile prompt path must stay inside profile config directory: "
            f"{relative_path}"
        )
    if not path.exists():
        raise FileNotFoundError(f"profile prompt file not found: {path}")
    return PromptTemplate(
        logical_name=logical_name,
        source_path=path,
        body=path.read_text(encoding="utf-8").strip(),
    )


def _load_prompt_pair(
    root: Path,
    category: str,
    paths: DashboardPromptPairPathConfig,
) -> LoadedDashboardPromptPair:
    return LoadedDashboardPromptPair(
        intent_analysis=_read_prompt(
            root,
            f"dashboard.{category}.intent_analysis",
            paths.intent_analysis,
        ),
        trend_prediction=_read_prompt(
            root,
            f"dashboard.{category}.trend_prediction",
            paths.trend_prediction,
        ),
    )


def _load_prompt_catalog(
    root: Path,
    paths: PromptPathConfig,
) -> LoadedPrompts:
    return LoadedPrompts(
        pipeline=LoadedPipelinePrompts(
            normalization=_read_prompt(
                root,
                "normalization",
                paths.pipeline.normalization,
            ),
            graph_extraction=_read_prompt(
                root,
                "graph_extraction",
                paths.pipeline.graph_extraction,
            ),
            classification=_read_prompt(
                root,
                "classification",
                paths.pipeline.classification,
            ),
            risk_first=_read_prompt(
                root,
                "risk_first",
                paths.pipeline.risk_first,
            ),
            risk_second=_read_prompt(
                root,
                "risk_second",
                paths.pipeline.risk_second,
            ),
        ),
        dashboard=LoadedDashboardPrompts(
            general=_load_prompt_pair(root, "general", paths.dashboard.general),
            categories=FrozenMapping(
                {
                    category: _load_prompt_pair(root, category, pair_paths)
                    for category, pair_paths in paths.dashboard.categories.items()
                }
            ),
        ),
    )


def _load_profile_config(root: Path) -> ProfileConfig:
    raw = RawProfileConfig.model_validate(_read_yaml_mapping(root / "profile.yaml"))
    _validate_graph_profile(raw.graph)
    prompts = _load_prompt_catalog(root, raw.prompts)
    return ProfileConfig(
        id=raw.id,
        display_name=raw.display_name,
        description=raw.description,
        graph=raw.graph,
        risk=raw.risk,
        classification=raw.classification,
        dashboard=raw.dashboard,
        prompts=prompts,
    )


@lru_cache(maxsize=1)
def get_profile_config() -> ProfileConfig:
    return _load_profile_config(PROFILE_CONFIG_DIR)


def reset_profile_config_cache() -> None:
    get_profile_config.cache_clear()
