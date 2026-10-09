from pathlib import Path

import pytest

from sentinel.config import SentinelSettings
from sentinel.config.profile import (
    ClassificationProfileConfig,
    DashboardProfileConfig,
    EdgeTypeMapEntry,
    GraphProfileConfig,
    GraphTypeConfig,
    LoadedDashboardPromptPair,
    LoadedDashboardPrompts,
    LoadedPipelinePrompts,
    LoadedPrompts,
    ProfileConfig,
    PromptTemplate,
    RiskProfileConfig,
)


def make_settings(**overrides):
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_provider": "openai",
        "llm_model": "gpt-test",
        "llm_base_url": "https://llm.example/v1",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def make_profile_config() -> ProfileConfig:
    def prompt(logical_name: str, body: str) -> PromptTemplate:
        return PromptTemplate(
            logical_name=logical_name,
            source_path=Path(f"/profiles/{logical_name}.md"),
            body=body,
        )

    return ProfileConfig(
        id="writer-test",
        display_name="Writer Test",
        graph=GraphProfileConfig(
            entities=(
                GraphTypeConfig(
                    name="Incident",
                    description="Profile incident entity.",
                    fields={"status": "Incident status."},
                ),
            ),
            edges=(
                GraphTypeConfig(
                    name="RelatedTo",
                    description="Profile relation.",
                    fields={"context": "Relation context."},
                ),
            ),
            edge_type_map=(
                EdgeTypeMapEntry(
                    source="Incident",
                    target="Incident",
                    edges=("RelatedTo",),
                ),
            ),
        ),
        risk=RiskProfileConfig(dimensions={"urgency": "Urgency."}),
        classification=ClassificationProfileConfig(),
        dashboard=DashboardProfileConfig(),
        prompts=LoadedPrompts(
            pipeline=LoadedPipelinePrompts(
                normalization=prompt("normalization", "Normalization prompt"),
                graph_extraction=prompt(
                    "graph_extraction",
                    "Profile graph prompt with {literal_braces}",
                ),
                classification=prompt("classification", "Classification prompt"),
                risk_first=prompt("risk_first", "Risk first prompt"),
                risk_second=prompt("risk_second", "Risk second prompt"),
            ),
            dashboard=LoadedDashboardPrompts(
                general=LoadedDashboardPromptPair(
                    intent_analysis=prompt("intent_analysis", "Intent prompt"),
                    trend_prediction=prompt("trend_prediction", "Trend prompt"),
                )
            ),
        ),
    )


@pytest.mark.asyncio
async def test_add_event_summary_uses_explicit_settings_snapshot(
    monkeypatch,
):
    calls = []
    settings = make_settings()

    async def fake_generate_text(app_settings, **kwargs):
        calls.append((app_settings, kwargs))
        return "  摘要  "

    monkeypatch.setattr("sentinel.graph.writer.generate_text", fake_generate_text)
    monkeypatch.setattr(
        "sentinel.graph.writer.get_profile_config",
        make_profile_config,
        raising=False,
    )

    class FakeGraphiti:
        async def add_episode(self, **kwargs):
            self.add_episode_kwargs = kwargs
            return {"nodes": [], "edges": []}

    graphiti = FakeGraphiti()

    from sentinel.graph.writer import add_event_to_graph

    result = await add_event_to_graph(
        graphiti,
        event_text="原文",
        source_description="来源",
        summarize_before_extract=True,
        app_settings=settings,
    )

    assert calls[0][0] is settings
    messages = calls[0][1]["messages"]
    assert messages[0]["role"] == "system"
    assert "严谨的信息压缩助手" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "来源" in messages[1]["content"]
    assert "原文" in messages[1]["content"]
    assert graphiti.add_episode_kwargs["episode_body"] == "摘要"
    assert result["summary"] == "摘要"
    assert result["used_summary_for_extraction"] is True


@pytest.mark.asyncio
async def test_add_event_to_graph_uses_passed_profile_schema_and_prompt() -> None:
    class FakeGraphiti:
        async def add_episode(self, **kwargs):
            self.add_episode_kwargs = kwargs
            return {"nodes": [], "edges": []}

    graphiti = FakeGraphiti()
    profile = make_profile_config()

    from sentinel.graph.writer import add_event_to_graph

    await add_event_to_graph(
        graphiti,
        event_text="Profile event",
        source_description="Profile source",
        profile_config=profile,
    )

    entity_types, edge_types, edge_type_map = profile.graphiti_extraction_config()
    assert graphiti.add_episode_kwargs["entity_types"].keys() == entity_types.keys()
    assert (
        graphiti.add_episode_kwargs["entity_types"]["Incident"]
        .model_fields["status"]
        .description
        == "Incident status."
    )
    assert graphiti.add_episode_kwargs["edge_types"].keys() == edge_types.keys()
    assert graphiti.add_episode_kwargs["edge_type_map"] == edge_type_map
    assert (
        graphiti.add_episode_kwargs["custom_extraction_instructions"]
        == "Profile graph prompt with {literal_braces}"
    )


@pytest.mark.asyncio
async def test_add_event_to_graph_uses_cached_profile_when_not_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraphiti:
        async def add_episode(self, **kwargs):
            self.add_episode_kwargs = kwargs
            return {"nodes": [], "edges": []}

    graphiti = FakeGraphiti()
    profile = make_profile_config()
    calls = 0

    def fake_get_profile_config() -> ProfileConfig:
        nonlocal calls
        calls += 1
        return profile

    monkeypatch.setattr(
        "sentinel.graph.writer.get_profile_config",
        fake_get_profile_config,
        raising=False,
    )

    from sentinel.graph.writer import add_event_to_graph

    await add_event_to_graph(
        graphiti,
        event_text="Profile event",
        app_settings=make_settings(),
    )

    assert calls == 1
    assert (
        graphiti.add_episode_kwargs["custom_extraction_instructions"]
        == "Profile graph prompt with {literal_braces}"
    )


@pytest.mark.asyncio
async def test_add_event_to_graph_explicit_instructions_override_profile_prompt() -> (
    None
):
    class FakeGraphiti:
        async def add_episode(self, **kwargs):
            self.add_episode_kwargs = kwargs
            return {"nodes": [], "edges": []}

    graphiti = FakeGraphiti()

    from sentinel.graph.writer import add_event_to_graph

    await add_event_to_graph(
        graphiti,
        event_text="Profile event",
        source_description="Profile source",
        custom_extraction_instructions="Explicit prompt",
        profile_config=make_profile_config(),
    )

    assert (
        graphiti.add_episode_kwargs["custom_extraction_instructions"]
        == "Explicit prompt"
    )
