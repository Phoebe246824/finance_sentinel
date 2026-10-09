"""Tests for fixed runtime profile configuration loading."""

import traceback
from pathlib import Path
from string import Formatter

import pytest
from pydantic import ValidationError

from sentinel.config import (
    PROFILE_CONFIG_DIR,
    PromptRenderError,
    PromptTemplate,
    render_prompt,
)

CATEGORY_IDS = (
    "intl_politics",
    "tech",
    "economy",
    "society",
    "public_health",
    "public_safety",
    "energy",
    "finance",
)


PIPELINE_PROMPT_NAMES = (
    "normalization",
    "graph_extraction",
    "classification",
    "risk_first",
    "risk_second",
)
EXPECTED_REPOSITORY_PROMPTS = {
    **{f"prompts/pipeline/{name}.md": name for name in PIPELINE_PROMPT_NAMES},
    **{
        f"prompts/dashboard/{category}/{prompt_name}.md": (
            f"dashboard.{category}.{prompt_name}"
        )
        for category in ("general", *CATEGORY_IDS)
        for prompt_name in ("intent_analysis", "trend_prediction")
    },
}
PROMPT_VARIABLE_VALUES = {
    "normalization": {
        "raw_content": "representative raw event marker",
        "current_datetime": "2026-07-14T12:00:00+08:00",
        "output_schema": "Return JSON object marker.",
    },
    "classification": {
        "title": "representative title marker",
        "raw_content": "representative raw event marker",
        "category_options": "- public_notice: Public Notice",
        "default_event_type": "information_event",
        "summary_instruction": "Summarize observable facts.",
        "output_schema": "Return JSON object marker.",
    },
    "risk": {
        "risk_dimensions": "urgency: response time sensitivity",
        "event_type": "public_notice",
        "event_summary": "representative event summary marker",
        "key_entities": {"organization": "Example Organization"},
        "event_time": "2026-07-14 12:00:00",
        "source": "news",
        "related_events": "representative related context marker",
        "output_schema": "Return JSON object marker.",
    },
    "dashboard_intent": {
        "category_name": "公共安全",
        "category_confidence": "0.91",
        "event_text": "representative dashboard event marker",
    },
    "dashboard_trend": {
        "category_name": "公共安全",
        "category_confidence": "0.91",
        "severity_name": "高",
        "severity_confidence": "0.87",
        "short_term": "未来 24 小时",
        "medium_term": "未来 7 天",
        "long_term": "未来 30 天",
        "event_text": "representative dashboard event marker",
        "intent_analysis": "representative intent analysis marker",
    },
}


def prompt_variable_values(logical_name: str) -> dict[str, object]:
    if logical_name in {"risk_first", "risk_second"}:
        return PROMPT_VARIABLE_VALUES["risk"]
    if logical_name.endswith(".intent_analysis"):
        return PROMPT_VARIABLE_VALUES["dashboard_intent"]
    if logical_name.endswith(".trend_prediction"):
        return PROMPT_VARIABLE_VALUES["dashboard_trend"]
    return PROMPT_VARIABLE_VALUES[logical_name]


def prompt_field_names(body: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(body)
        if field_name is not None
    }


def repository_prompt_templates(profile) -> dict[str, PromptTemplate]:
    templates = {
        name: getattr(profile.prompts.pipeline, name) for name in PIPELINE_PROMPT_NAMES
    }
    templates.update(
        {
            "dashboard.general.intent_analysis": (
                profile.prompts.dashboard.general.intent_analysis
            ),
            "dashboard.general.trend_prediction": (
                profile.prompts.dashboard.general.trend_prediction
            ),
        }
    )
    for category in CATEGORY_IDS:
        resolved_category, prompt_pair = profile.prompts.dashboard.resolve(category)
        assert resolved_category == category
        templates[f"dashboard.{category}.intent_analysis"] = prompt_pair.intent_analysis
        templates[f"dashboard.{category}.trend_prediction"] = (
            prompt_pair.trend_prediction
        )
    return templates


def test_repository_profile_declares_complete_prompt_catalog() -> None:
    from sentinel.config import get_profile_config, reset_profile_config_cache

    reset_profile_config_cache()
    try:
        profile = get_profile_config()
        templates = repository_prompt_templates(profile)

        assert profile.dashboard.force_category is None
        assert set(profile.prompts.dashboard.categories) == set(CATEGORY_IDS)
        assert set(templates) == set(EXPECTED_REPOSITORY_PROMPTS.values())
        for relative_path, logical_name in EXPECTED_REPOSITORY_PROMPTS.items():
            template = templates[logical_name]
            assert template.source_path.relative_to(PROFILE_CONFIG_DIR) == Path(
                relative_path
            )
            assert template.logical_name == logical_name
            assert template.body.strip()

        filesystem_paths = {
            path.relative_to(PROFILE_CONFIG_DIR).as_posix()
            for path in (PROFILE_CONFIG_DIR / "prompts").rglob("*.md")
        }
        assert filesystem_paths == set(EXPECTED_REPOSITORY_PROMPTS)

        for logical_name, template in templates.items():
            if logical_name == "graph_extraction":
                continue
            values = prompt_variable_values(logical_name)
            assert prompt_field_names(template.body) == set(values)
            rendered = render_prompt(template, **values)
            assert rendered.strip()
            if logical_name == "normalization":
                assert values["raw_content"] in rendered
            elif logical_name.startswith("dashboard."):
                assert values["category_name"] in rendered
            else:
                assert values["output_schema"] in rendered
    finally:
        reset_profile_config_cache()


def write_profile(root: Path, *, include_risk_first: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "profile.yaml").write_text(
        """
id: test-profile
display_name: Test Profile
description: Test runtime profile.
graph:
  entities:
    - name: Event
      description: Observable event.
      fields:
        event_kind: Event kind.
    - name: Organization
      description: Organization involved in the event.
  edges:
    - name: Involves
      description: Connects an event to a participant.
      fields:
        role: Participant role.
  edge_type_map:
    - source: Event
      target: Organization
      edges:
        - Involves
risk:
  dimensions:
    urgency: How quickly the event needs attention.
    credibility: How reliable the reported evidence is.
classification:
  default_event_type: public_event
  summary_instruction: Summarize the event for operators.
  categories:
    public_notice:
      display_name: Public Notice
      keywords:
        - advisory
dashboard:
  force_category: null
  force_category_confidence: 0.9
  analysis_target: Public impact and response.
prompts:
  pipeline:
    normalization: prompts/pipeline/normalization.md
    graph_extraction: prompts/pipeline/graph_extraction.md
    classification: prompts/pipeline/classification.md
    risk_first: prompts/pipeline/risk_first.md
    risk_second: prompts/pipeline/risk_second.md
  dashboard:
    general:
      intent_analysis: prompts/dashboard/general/intent_analysis.md
      trend_prediction: prompts/dashboard/general/trend_prediction.md
    categories:
      public_safety:
        intent_analysis: prompts/dashboard/public_safety/intent_analysis.md
        trend_prediction: prompts/dashboard/public_safety/trend_prediction.md
""",
        encoding="utf-8",
    )
    prompt_text = {
        "prompts/pipeline/normalization.md": (
            "Normalize {raw_content}\n{output_schema}"
        ),
        "prompts/pipeline/graph_extraction.md": (
            "Graph prompt with {literal_graph_brace}"
        ),
        "prompts/pipeline/classification.md": (
            "Classify {raw_content}\n{output_schema}"
        ),
        "prompts/pipeline/risk_first.md": (
            "Risk first {event_summary}\n{output_schema}"
        ),
        "prompts/pipeline/risk_second.md": (
            "Risk second {related_events}\n{output_schema}"
        ),
        "prompts/dashboard/general/intent_analysis.md": ("General intent {event_text}"),
        "prompts/dashboard/general/trend_prediction.md": (
            "General trend {intent_analysis}"
        ),
        "prompts/dashboard/public_safety/intent_analysis.md": (
            "Safety intent {event_text}"
        ),
        "prompts/dashboard/public_safety/trend_prediction.md": (
            "Safety trend {short_term} {intent_analysis}"
        ),
    }
    if not include_risk_first:
        del prompt_text["prompts/pipeline/risk_first.md"]
    for name, text in prompt_text.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def write_profile_with_override(
    root: Path,
    old: str,
    new: str,
) -> None:
    write_profile(root)
    profile_path = root / "profile.yaml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(old, new),
        encoding="utf-8",
    )


def test_profile_config_loads_yaml_and_markdown(
    tmp_path: Path,
) -> None:
    # Given: a fixed-shape profile directory with YAML and prompt Markdown files.
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    # When: the runtime profile is loaded from an explicit directory.
    profile = profile_module._load_profile_config(tmp_path)

    # Then: structured values and loaded prompt text are parsed.
    assert profile.id == "test-profile"
    assert profile.graph.entities[0].fields == {"event_kind": "Event kind."}
    assert profile.graph.edge_type_map[0].edges == ("Involves",)
    assert profile.risk.dimensions["urgency"] == (
        "How quickly the event needs attention."
    )
    assert profile.classification.default_event_type == "public_event"
    assert profile.classification.categories["public_notice"].keywords == ("advisory",)
    assert profile.dashboard.analysis_target == "Public impact and response."
    assert profile.prompts.pipeline.risk_first.body.startswith("Risk first")


def test_profile_loads_typed_pipeline_and_dashboard_prompts(
    tmp_path: Path,
) -> None:
    write_profile(tmp_path)
    from sentinel.config.profile import _load_profile_config

    profile = _load_profile_config(tmp_path)

    normalization = profile.prompts.pipeline.normalization
    assert normalization.body == "Normalize {raw_content}\n{output_schema}"
    assert {
        name: getattr(profile.prompts.pipeline, name).logical_name
        for name in (
            "normalization",
            "graph_extraction",
            "classification",
            "risk_first",
            "risk_second",
        )
    } == {
        "normalization": "normalization",
        "graph_extraction": "graph_extraction",
        "classification": "classification",
        "risk_first": "risk_first",
        "risk_second": "risk_second",
    }
    assert (
        normalization.source_path
        == (tmp_path / "prompts/pipeline/normalization.md").resolve()
    )
    assert profile.prompts.dashboard.general.intent_analysis.body.startswith(
        "General intent"
    )
    assert set(profile.prompts.dashboard.categories) == {"public_safety"}


def test_dashboard_prompt_resolution_uses_category_or_general(tmp_path: Path) -> None:
    write_profile(tmp_path)
    from sentinel.config.profile import _load_profile_config

    dashboard = _load_profile_config(tmp_path).prompts.dashboard

    category, prompts = dashboard.resolve("public_safety")
    assert category == "public_safety"
    assert prompts.intent_analysis.body.startswith("Safety intent")

    category, prompts = dashboard.resolve("missing")
    assert category == "general"
    assert prompts.intent_analysis.body.startswith("General intent")


def test_get_profile_config_caches_until_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    try:
        first = profile_module.get_profile_config()
        normalization_path = tmp_path / "prompts/pipeline/normalization.md"
        normalization_path.write_text("Changed {raw_content}", encoding="utf-8")

        cached = profile_module.get_profile_config()
        assert cached is first
        assert cached.prompts.pipeline.normalization.body.startswith("Normalize")

        profile_module.reset_profile_config_cache()
        changed = profile_module.get_profile_config()
        assert changed is not first
        assert changed.prompts.pipeline.normalization.body == "Changed {raw_content}"
    finally:
        profile_module.reset_profile_config_cache()


def test_render_prompt_substitutes_values_and_allows_unused_values() -> None:
    template = PromptTemplate(
        logical_name="pipeline.normalization",
        source_path=Path("/profiles/normalization.md"),
        body="Normalize {raw_content}; literal {{brace}}",
    )

    rendered = render_prompt(template, raw_content="event", unused="ignored")

    assert rendered == "Normalize event; literal {brace}"


@pytest.mark.parametrize(
    "body",
    ["Missing {required}", "Malformed {brace"],
)
def test_render_prompt_wraps_format_errors_without_leaking_values(body: str) -> None:
    template = PromptTemplate(
        logical_name="pipeline.secret_test",
        source_path=Path("/profiles/secret.md"),
        body=body,
    )
    secret = "SECRET event value"

    with pytest.raises(PromptRenderError) as exc_info:
        render_prompt(template, supplied=secret)

    message = str(exc_info.value)
    assert "pipeline.secret_test" in message
    assert "/profiles/secret.md" in message
    assert "KeyError" in message or "ValueError" in message
    assert secret not in message


def test_render_prompt_suppresses_value_error_cause_and_secret_traceback() -> None:
    secret = "SECRET event value"

    class SecretFormatValue:
        def __format__(self, format_spec: str) -> str:
            raise ValueError(secret)

    template = PromptTemplate(
        logical_name="secret_test",
        source_path=Path("/profiles/secret.md"),
        body="Format {supplied}",
    )

    with pytest.raises(PromptRenderError) as exc_info:
        render_prompt(template, supplied=SecretFormatValue())

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert secret not in formatted


@pytest.mark.parametrize(
    ("body", "value", "error_name"),
    [
        ("Format {supplied.missing}", "value", "AttributeError"),
        ("Format {supplied[2]}", ["value"], "IndexError"),
        ("Format {supplied:>20}", {"value": "secret"}, "TypeError"),
    ],
)
def test_render_prompt_wraps_all_format_lookup_errors(
    body: str,
    value: object,
    error_name: str,
) -> None:
    template = PromptTemplate(
        logical_name="pipeline.format_lookup_test",
        source_path=Path("/profiles/format_lookup.md"),
        body=body,
    )

    with pytest.raises(PromptRenderError) as exc_info:
        render_prompt(template, supplied=value)

    assert error_name in str(exc_info.value)


def test_render_prompt_suppresses_arbitrary_format_exception_details() -> None:
    secret = "SECRET event value"

    class CustomFormatError(RuntimeError):
        pass

    class SecretFormatValue:
        def __format__(self, format_spec: str) -> str:
            raise CustomFormatError(secret)

    template = PromptTemplate(
        logical_name="pipeline.custom_format_test",
        source_path=Path("/profiles/custom_format.md"),
        body="Format {supplied}",
    )

    with pytest.raises(PromptRenderError) as exc_info:
        render_prompt(template, supplied=SecretFormatValue())

    assert "CustomFormatError" in str(exc_info.value)
    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    assert secret not in formatted


def test_render_prompt_does_not_intercept_base_exceptions() -> None:
    class FormatAbort(BaseException):
        pass

    class AbortingFormatValue:
        def __format__(self, format_spec: str) -> str:
            raise FormatAbort

    template = PromptTemplate(
        logical_name="pipeline.abort_test",
        source_path=Path("/profiles/abort.md"),
        body="Format {supplied}",
    )

    with pytest.raises(FormatAbort):
        render_prompt(template, supplied=AbortingFormatValue())


def test_profile_graphiti_extraction_config_uses_profile_schema(
    tmp_path: Path,
) -> None:
    # Given: a profile defines graph entity and edge models with YAML descriptions.
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    profile = profile_module._load_profile_config(tmp_path)

    # When: Graphiti extraction configuration is built from the profile.
    entity_types, edge_types, edge_type_map = profile.graphiti_extraction_config()

    # Then: dynamic Pydantic model fields preserve profile YAML descriptions.
    event_model = entity_types["Event"]
    assert event_model.__doc__ == "Observable event."
    assert event_model.model_fields["event_kind"].description == "Event kind."
    assert event_model.model_fields["event_kind"].annotation == str | None
    assert event_model.model_fields["event_kind"].default is None

    involves_model = edge_types["Involves"]
    assert involves_model.__doc__ == "Connects an event to a participant."
    assert involves_model.model_fields["role"].description == "Participant role."
    assert involves_model.model_fields["role"].annotation == str | None
    assert involves_model.model_fields["role"].default is None

    assert edge_type_map[("Event", "Organization")] == ["Involves"]
    assert edge_type_map[("Entity", "Entity")] == ["Involves"]


@pytest.mark.parametrize(
    ("prompt_path", "match"),
    [
        ("/tmp/profile-prompt.md", "must be relative"),
        ("../outside.md", "inside profile config directory"),
    ],
)
def test_prompt_paths_must_stay_inside_profile_config_dir(
    tmp_path: Path,
    prompt_path: str,
    match: str,
) -> None:
    # Given: profile YAML points a prompt outside the fixed profile directory.
    write_profile_with_override(
        tmp_path,
        "graph_extraction: prompts/pipeline/graph_extraction.md",
        f"graph_extraction: {prompt_path}",
    )
    import sentinel.config.profile as profile_module

    # When / Then: loading rejects the unsafe prompt path before reading it.
    with pytest.raises(ValueError, match=match):
        profile_module._load_profile_config(tmp_path)


def test_missing_prompt_raises_file_not_found_with_prompt_name(
    tmp_path: Path,
) -> None:
    # Given: profile YAML references a prompt file that is absent.
    write_profile(tmp_path, include_risk_first=False)
    import sentinel.config.profile as profile_module

    # When / Then: loading fails fast and names the missing prompt.
    with pytest.raises(FileNotFoundError, match="risk_first.md"):
        profile_module._load_profile_config(tmp_path)


def test_profile_yaml_must_be_mapping(
    tmp_path: Path,
) -> None:
    # Given: profile.yaml exists but has a list at the document root.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "profile.yaml").write_text("- invalid\n", encoding="utf-8")
    import sentinel.config.profile as profile_module

    # When / Then: the loader rejects non-mapping YAML clearly.
    with pytest.raises(ValueError, match="profile YAML must contain a mapping"):
        profile_module._load_profile_config(tmp_path)


def test_false_profile_yaml_is_rejected_as_non_mapping(
    tmp_path: Path,
) -> None:
    # Given: profile.yaml contains a falsy scalar, not an empty document.
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "profile.yaml").write_text("false\n", encoding="utf-8")
    import sentinel.config.profile as profile_module

    # When / Then: the loader rejects the boolean instead of treating it as empty.
    with pytest.raises(ValueError, match="profile YAML must contain a mapping"):
        profile_module._load_profile_config(tmp_path)


def test_profile_yaml_rejects_unknown_top_level_keys(
    tmp_path: Path,
) -> None:
    # Given: profile YAML includes an unsupported top-level key.
    write_profile(tmp_path)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        f"{profile_path.read_text(encoding='utf-8')}unexpected: true\n",
        encoding="utf-8",
    )
    import sentinel.config.profile as profile_module

    # When / Then: Pydantic reports the extra key clearly.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        profile_module._load_profile_config(tmp_path)


def test_profile_yaml_rejects_unknown_nested_keys(
    tmp_path: Path,
) -> None:
    # Given: a nested entity definition includes an unsupported key.
    write_profile_with_override(
        tmp_path,
        "      fields:\n        event_kind: Event kind.",
        "      fields:\n        event_kind: Event kind.\n      unexpected: true",
    )
    import sentinel.config.profile as profile_module

    # When / Then: nested model validation rejects the extra key clearly.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        profile_module._load_profile_config(tmp_path)


def test_profile_yaml_rejects_duplicate_entity_names(
    tmp_path: Path,
) -> None:
    # Given: two profile graph entities use the same Graphiti type name.
    write_profile_with_override(
        tmp_path,
        "    - name: Organization\n      description: Organization involved in the event.",
        "    - name: Event\n      description: Duplicate event type.",
    )
    import sentinel.config.profile as profile_module

    # When / Then: loading rejects the duplicate before model generation.
    with pytest.raises(ValueError, match="duplicate graph entity name: Event"):
        profile_module._load_profile_config(tmp_path)


def test_profile_yaml_rejects_duplicate_edge_names(
    tmp_path: Path,
) -> None:
    # Given: two profile graph edges use the same Graphiti type name.
    write_profile_with_override(
        tmp_path,
        "  edge_type_map:",
        "    - name: Involves\n"
        "      description: Duplicate relationship type.\n"
        "  edge_type_map:",
    )
    import sentinel.config.profile as profile_module

    # When / Then: loading rejects the duplicate before model generation.
    with pytest.raises(ValueError, match="duplicate graph edge name: Involves"):
        profile_module._load_profile_config(tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("source: Event", "source: MissingEntity", "unknown source entity"),
        ("target: Organization", "target: MissingEntity", "unknown target entity"),
        ("- Involves", "- MissingEdge", "unknown edge type"),
    ],
)
def test_profile_yaml_rejects_edge_type_map_unknown_references(
    tmp_path: Path,
    old: str,
    new: str,
    match: str,
) -> None:
    # Given: edge_type_map points at a graph type that is not declared.
    write_profile_with_override(tmp_path, old, new)
    import sentinel.config.profile as profile_module

    # When / Then: loading fails fast with a targeted reference error.
    with pytest.raises(ValueError, match=match):
        profile_module._load_profile_config(tmp_path)


def test_profile_sequence_collections_are_immutable_after_loading(
    tmp_path: Path,
) -> None:
    # Given: a valid profile with nested sequence and mapping fields.
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    # When: the runtime profile is loaded.
    profile = profile_module._load_profile_config(tmp_path)

    # Then: sequence fields cannot be mutated through the parsed model.
    assert profile.graph.entities[0].fields == {"event_kind": "Event kind."}
    with pytest.raises(TypeError):
        profile.graph.edge_type_map[0].edges[0] = "Blocked"


def test_dashboard_prompt_categories_are_immutable_after_loading(
    tmp_path: Path,
) -> None:
    write_profile(tmp_path)
    from sentinel.config.profile import _load_profile_config

    categories = _load_profile_config(tmp_path).prompts.dashboard.categories

    with pytest.raises(TypeError):
        categories["public_safety"] = categories["public_safety"]
    with pytest.raises(TypeError):
        del categories["public_safety"]


def test_cached_profile_mappings_are_deeply_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    try:
        profile = profile_module.get_profile_config()
        mappings_and_keys = (
            (profile.graph.entities[0].fields, "event_kind"),
            (profile.classification.categories, "public_notice"),
            (profile.risk.dimensions, "urgency"),
            (profile.prompts.dashboard.categories, "public_safety"),
        )
        expected = tuple(mapping[key] for mapping, key in mappings_and_keys)

        for mapping, key in mappings_and_keys:
            with pytest.raises(TypeError):
                mapping[key] = mapping[key]
            with pytest.raises(TypeError):
                del mapping[key]

        cached = profile_module.get_profile_config()
        assert cached is profile
        assert (
            tuple(
                mapping[key]
                for mapping, key in (
                    (cached.graph.entities[0].fields, "event_kind"),
                    (cached.classification.categories, "public_notice"),
                    (cached.risk.dimensions, "urgency"),
                    (cached.prompts.dashboard.categories, "public_safety"),
                )
            )
            == expected
        )

        dimensions = profile.risk.dimensions
        assert not hasattr(dimensions, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            dimensions._items = (("injected", "value"),)

        cached = profile_module.get_profile_config()
        assert cached is profile
        assert "injected" not in cached.risk.dimensions
        assert cached.risk.dimensions["urgency"] == expected[2]
    finally:
        profile_module.reset_profile_config_cache()


def test_profile_config_can_be_dumped_as_json(
    tmp_path: Path,
) -> None:
    # Given: a valid profile with nested mappings and sequences.
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    # When: the public profile model is serialized.
    profile = profile_module._load_profile_config(tmp_path)
    dumped = profile.model_dump(mode="json")
    json_text = profile.model_dump_json()

    # Then: nested mappings remain serializable for diagnostics and APIs.
    assert dumped["graph"]["entities"][0]["fields"] == {"event_kind": "Event kind."}
    assert set(dumped["prompts"]["dashboard"]["categories"]) == {"public_safety"}
    assert (
        dumped["prompts"]["dashboard"]["categories"]["public_safety"][
            "intent_analysis"
        ]["logical_name"]
        == "dashboard.public_safety.intent_analysis"
    )
    assert '"public_safety"' in json_text
    assert "test-profile" in json_text


def test_profile_config_loads_from_fixed_default_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fixed nested profile directory is configured as the default.
    write_profile(tmp_path)
    import sentinel.config.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_CONFIG_DIR", tmp_path)
    profile_module.reset_profile_config_cache()
    try:
        profile = profile_module.get_profile_config()
    finally:
        profile_module.reset_profile_config_cache()

    # Then: the public cached loader reads the configured profile directory.
    assert profile.id == "test-profile"
    assert profile.prompts.pipeline.graph_extraction.body
    assert profile.prompts.dashboard.general.trend_prediction.body


def test_profile_graph_schema_passes_graphiti_validation(tmp_path: Path) -> None:
    # Given: a valid nested profile graph schema.
    write_profile(tmp_path)
    from graphiti_core.utils.ontology_utils.entity_types_utils import (
        validate_entity_types,
    )
    from sentinel.config.profile import _load_profile_config

    # When: Graphiti entity models are generated from that schema.
    profile = _load_profile_config(tmp_path)
    entity_types, _, _ = profile.graphiti_extraction_config()

    # Then: the schema does not collide with Graphiti protected entity fields.
    assert validate_entity_types(entity_types) is True
