"""Graphiti/Neo4j 客户端构建与生命周期管理。"""

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.jina_reranker_client import JinaRerankerClient
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from sentinel.config import SentinelSettings, get_settings
from sentinel.utils.async_resources import close_inner_http_client, close_resource


async def init_graph_client(app_settings: SentinelSettings | None = None) -> Graphiti:
    settings = app_settings or get_settings()
    llm_client = OpenAIGenericClient(
        config=LLMConfig(
            api_key=settings.require_llm_api_key(),
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
    )

    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model=settings.embedder_model,
            api_key=settings.effective_embedder_api_key_value(),
            base_url=settings.effective_embedder_api_base,
        )
    )

    cross_encoder = JinaRerankerClient(
        config=LLMConfig(
            api_key=settings.effective_reranker_api_key_value(),
            model=settings.effective_reranker_model,
            base_url=settings.effective_reranker_base_url,
        )
    )

    graph_driver = Neo4jDriver(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.require_neo4j_password(),
        database=settings.neo4j_database,
    )

    graphiti = Graphiti(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.require_neo4j_password(),
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
        graph_driver=graph_driver,
    )

    await graphiti.build_indices_and_constraints()
    return graphiti


async def close_graph_client(graphiti: Graphiti) -> None:
    for client in (
        getattr(graphiti, "llm_client", None),
        getattr(graphiti, "embedder", None),
        getattr(graphiti, "cross_encoder", None),
    ):
        try:
            await close_resource(client)
        except RuntimeError as e:
            if "Event loop is closed" not in str(e):
                raise
        try:
            await close_inner_http_client(client)
        except RuntimeError as e:
            if "Event loop is closed" not in str(e):
                raise

    try:
        await graphiti.close()
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            return
        raise
