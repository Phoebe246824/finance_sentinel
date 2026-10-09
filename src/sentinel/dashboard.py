"""
Sentinel Web Dashboard factory.
"""

from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI

from sentinel.blacklist.management import BlacklistManagementService
from sentinel.blacklist.stores.factory import create_store_bundle
from sentinel.blacklist.stores.runtime import (
    get_runtime_store_bundle,
    reset_runtime_store_bundle_cache_async,
)
from sentinel.config import SentinelSettings, get_profile_config, get_settings
from sentinel.graph.person_graph import (
    fetch_event_subgraph,
    fetch_graph_counts,
    fetch_person_subgraph,
)
from sentinel.graph.query_client import init_read_only_graph_client
from sentinel.main import process_message
from sentinel.pipeline.blacklist_gate import build_blacklist_store_config
from sentinel.utils.async_resources import close_resource
from sentinel.web.analysis_tasks import AnalysisTaskManager
from sentinel.web.api import (
    create_dashboard_auth_config,
    install_dashboard_api_exception_handlers,
)
from sentinel.web.api import (
    router as web_api_router,
)
from sentinel.web.repository import EventResultRepository
from sentinel.web.settings_runtime import RuntimeSettingsManager
from sentinel.web.settings_service import RuntimeSettingsService
from sentinel.web.spa import mount_spa

GRAPH_COUNTS_CACHE_TTL_SECONDS = 30.0


class GraphQueries:
    def __init__(self, settings: SentinelSettings) -> None:
        self._settings = settings
        self.group_id = settings.graphiti_episode_source
        self._counts_cache: dict[str, int] | None = None
        self._counts_cache_expires_at = 0.0

    async def _graph_client(self):
        return await init_read_only_graph_client(self._settings)

    async def fetch_person_subgraph(self, person_id: str):
        graph = await self._graph_client()
        try:
            return await fetch_person_subgraph(
                graphiti=graph,
                person_id=person_id,
                group_id=self.group_id,
            )
        finally:
            await graph.close()

    async def fetch_event_subgraph(self, event_id: str, event_content: str):
        graph = await self._graph_client()
        try:
            return await fetch_event_subgraph(
                graphiti=graph,
                event_id=event_id,
                event_content=event_content,
                group_id=self.group_id,
            )
        finally:
            await graph.close()

    async def fetch_graph_counts(self):
        now = monotonic()
        if self._counts_cache is not None and now < self._counts_cache_expires_at:
            return dict(self._counts_cache)

        graph = await self._graph_client()
        try:
            counts = await fetch_graph_counts(graphiti=graph, group_id=self.group_id)
            self._counts_cache = dict(counts)
            self._counts_cache_expires_at = now + GRAPH_COUNTS_CACHE_TTL_SECONDS
            return counts
        finally:
            await graph.close()


def create_dashboard_app(settings: SentinelSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    get_profile_config()

    async def runner(text, observer, runtime_settings):
        return await process_message(
            text,
            runtime_settings,
            observer=observer,
            return_result=True,
        )

    async def repository_factory() -> EventResultRepository:
        current_settings = app.state.runtime_settings.get_active_settings()
        config = build_blacklist_store_config(current_settings)
        bundle = await get_runtime_store_bundle(config)
        return EventResultRepository(bundle.events)

    async def blacklist_management_service_factory(
        request,
    ) -> BlacklistManagementService:
        current_settings = request.app.state.runtime_settings.get_active_settings()
        config = build_blacklist_store_config(current_settings)
        bundle = await get_runtime_store_bundle(config)
        return BlacklistManagementService(bundle)

    class LazyRepository:
        async def save_result(self, event, status: str, settings=None) -> None:
            settings_snapshot = (
                settings or app.state.runtime_settings.get_active_settings()
            )
            config = build_blacklist_store_config(settings_snapshot)
            bundle = create_store_bundle(config)
            try:
                repository = EventResultRepository(bundle.events)
                await repository.save_result(event, status)
            finally:
                await close_resource(bundle)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.event_repository = await repository_factory()
        try:
            yield
        finally:
            await app.state.analysis_task_manager.shutdown()
            await reset_runtime_store_bundle_cache_async()

    app = FastAPI(title="Sentinel Dashboard", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.runtime_settings = RuntimeSettingsManager(app_settings)
    app.state.runtime_settings_service = RuntimeSettingsService.from_active_settings(
        app.state.runtime_settings.get_active_settings,
        active_settings=app_settings,
    )
    app.state.dashboard_auth = create_dashboard_auth_config(app_settings)
    app.state.analysis_task_manager = AnalysisTaskManager(
        runner=runner,
        repository=LazyRepository(),
    )
    app.state.event_repository_factory = repository_factory
    app.state.blacklist_management_service_factory = (
        blacklist_management_service_factory
    )
    app.state.graph_queries_factory = GraphQueries
    app.state.graph_queries = GraphQueries(app_settings)

    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    mount_spa(app)
    return app
