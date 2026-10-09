from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentinel.blacklist.management import (
    BlacklistConflictError,
    BlacklistDuplicateError,
    BlacklistNotFoundError,
    BlacklistValidationError,
)
from sentinel.config import SentinelSettings
from sentinel.web.analysis_tasks import AnalysisTaskPayload
from sentinel.web.api import (
    DashboardAuthConfig,
    create_stream_token,
    install_dashboard_api_exception_handlers,
    verify_stream_token,
)
from sentinel.web.api import (
    router as web_api_router,
)
from sentinel.web.models import (
    DashboardOverviewPayload,
    DashboardStatsPayload,
    PaginatedEventsPayload,
    SentinelEventPayload,
    TrendReportPayload,
)
from sentinel.web.settings_checks import (
    SettingsCheckResponsePayload,
    SettingsCheckResultPayload,
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
    SearchRuntimePayload,
    SecretFieldState,
    ServicesSettingsPayload,
    StashRuntimePayload,
)

AUTH_CONFIG = DashboardAuthConfig(
    user_name="admin",
    password="test-dashboard-password",
    access_token="test-dashboard-token",
    refresh_token="test-dashboard-refresh-token",
)
AUTH_HEADERS = {"Authorization": AUTH_CONFIG.access_token}


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_model": "gpt-4o",
        "dashboard_admin_password": AUTH_CONFIG.password,
        "dashboard_access_token": AUTH_CONFIG.access_token,
        "dashboard_refresh_token": AUTH_CONFIG.refresh_token,
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def make_event(event_id: str = "EVT-WEB") -> SentinelEventPayload:
    return SentinelEventPayload(
        event_id=event_id,
        source="news",
        event_type="负面舆情",
        risk_level="high",
        risk_score=0.91,
        summary="摘要",
        raw_content="P01 高风险事件",
        timestamp="2026-01-01T12:00:00",
        key_entities=[{"name": "P01", "type": "PERSON"}],
        reasoning="推理",
        dimension_scores={"risk": 0.91},
        trend_report=TrendReportPayload(
            category_name="金融",
            category_confidence=0.8,
            severity_name="重大",
            severity_confidence=0.7,
            intent_analysis="意图",
            trend_prediction="趋势",
        ),
    )


class FakeRepository:
    def __init__(self) -> None:
        self.events = [make_event()]

    def get_result(self, event_id: str):
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None

    def list_results(
        self,
        *,
        page,
        page_size,
        source=None,
        risk_level=None,
        event_type=None,
        keyword=None,
    ):
        del event_type
        items = self.events
        if source:
            items = [event for event in items if event.source == source]
        if risk_level:
            items = [event for event in items if event.risk_level == risk_level]
        if keyword:
            lowered = keyword.lower()
            items = [
                event
                for event in items
                if lowered in event.event_id.lower()
                or lowered in event.raw_content.lower()
                or lowered in event.summary.lower()
            ]
        return PaginatedEventsPayload(
            items=items[(page - 1) * page_size : page * page_size],
            total=len(items),
            page=page,
            page_size=page_size,
            current=page,
            size=page_size,
        )

    def overview(self):
        return DashboardOverviewPayload(
            stats=DashboardStatsPayload(
                total_events=len(self.events),
                high_risk_count=1,
            ),
            risk_distribution={"high": 1, "medium": 0, "low": 0},
            source_distribution={"news": 1},
            recent_events=self.events,
            updated_at="2026-01-01T12:00:00",
        )


class TruncatedRepository(FakeRepository):
    def __init__(self) -> None:
        self.events = [
            make_event(),
            SentinelEventPayload(
                event_id="EVT-STASHED",
                analysis_status="stashed",
                source="news",
                event_type="负面舆情",
                risk_level="unassessed",
                risk_score=0.0,
                summary="未触发分析",
                raw_content="普通输入事件",
                timestamp="2026-01-01T13:00:00",
                reasoning="黑名单未命中，未进入完整分析流",
            ),
        ]

    def list_results(
        self,
        *,
        page,
        page_size,
        source=None,
        risk_level=None,
        event_type=None,
        keyword=None,
    ):
        result = super().list_results(
            page=page,
            page_size=page_size,
            source=source,
            risk_level=risk_level,
            event_type=event_type,
            keyword=keyword,
        )
        result.truncated = True
        return result

    def overview(self):
        return DashboardOverviewPayload(
            stats=DashboardStatsPayload(
                total_events=2,
                high_risk_count=1,
                unassessed_count=1,
                data_truncated=True,
            ),
            risk_distribution={"high": 1, "medium": 0, "low": 0},
            source_distribution={"news": 2},
            recent_events=self.events,
            updated_at="2026-01-01T13:00:00",
            truncated=True,
        )


class FakeTaskManager:
    def __init__(self) -> None:
        self.last_settings = None
        self.active = False

    def create_task(self, text: str, settings=None):
        self.last_settings = settings
        return AnalysisTaskPayload(
            task_id="task-test",
            status="running",
            stage_key="queued",
            stage_label="排队中",
            stage_index=0,
            stage_total=8,
            stage_detail=text,
            stage_updated_at="2026-01-01T12:00:00",
        )

    def metrics_snapshot(self, *, now=None):
        del now
        return {
            "completed_tasks": 3,
            "avg_processing_latency_ms": 1450,
            "events_per_minute": 2.0,
            "uptime_hours": 1.5,
        }

    def get_task(self, task_id: str):
        if task_id == "task-test":
            return AnalysisTaskPayload(task_id=task_id, status="running")
        return None

    async def stream_updates(self, task_id: str):
        yield AnalysisTaskPayload(
            task_id=task_id,
            status="success",
            event_id="EVT-WEB",
            stage_key="complete",
            stage_label="分析完成",
            stage_index=8,
            stage_total=8,
            stage_detail="done",
            stage_updated_at="2026-01-01T12:00:01",
        )

    def has_active_tasks(self) -> bool:
        return self.active


class FakeRuntimeSettingsService:
    def __init__(self) -> None:
        self.saved_payload = None
        self.current_model = "gpt-4o"
        self.current_dry_run = False

    def read_runtime_settings(self):
        return RuntimeSettingsResponsePayload(
            models=ModelsSettingsPayload(
                llm=LlmSettingsPayload(
                    provider="openai",
                    model=self.current_model,
                    base_url="https://api.openai.com/v1",
                ),
                embedder=EmbedderSettingsPayload(
                    model="BAAI/bge-m3",
                    api_base="https://api.siliconflow.cn/v1",
                    embedding_dim=1024,
                ),
                reranker=RerankerSettingsPayload(
                    model="BAAI/bge-reranker-v2-m3",
                    base_url="https://api.siliconflow.cn/v1",
                ),
            ),
            services=ServicesSettingsPayload(
                neo4j=Neo4jSettingsPayload(
                    uri="bolt://localhost:7687",
                    user="neo4j",
                    database="neo4j",
                ),
                milvus=MilvusSettingsPayload(
                    uri="http://localhost:19530",
                    input_events_collection="input_events",
                ),
                graphiti=GraphitiSettingsPayload(dry_run=self.current_dry_run),
            ),
            runtime=RuntimeSettingsPayload(
                search=SearchRuntimePayload(
                    num_results=10,
                    risk_num_results=20,
                    min_score=0.0,
                ),
                risk=RiskRuntimePayload(threshold=0.7),
                stash=StashRuntimePayload(
                    kv_ttl_days=90,
                    semantic_top_k=10,
                    rerank_min_score=0.7,
                    rerank_enabled=True,
                ),
                batch=BatchRuntimePayload(max_per_person=20),
                blacklist=BlacklistRuntimePayload(
                    event_similarity_threshold=0.5,
                    person_min_hits=1,
                ),
            ),
            secrets=RuntimeSettingsSecretsPayload(
                neo4j_password=SecretFieldState(configured=True, masked_hint="****"),
                llm_api_key=SecretFieldState(configured=True, masked_hint="****"),
                embedder_api_key=SecretFieldState(configured=True, masked_hint="****"),
                reranker_api_key=SecretFieldState(configured=True, masked_hint="****"),
                milvus_token=SecretFieldState(configured=False, masked_hint=None),
            ),
            meta=RuntimeSettingsMetaPayload(updated_at="2026-07-02T12:00:00"),
        )

    def save_runtime_settings(self, payload):
        self.saved_payload = payload
        self.current_model = payload.models.llm.model
        self.current_dry_run = payload.services.graphiti.dry_run
        return self.read_runtime_settings()

    def current_settings(self):
        return make_settings(
            llm_model=self.current_model,
            graphiti_dry_run=self.current_dry_run,
        )


class FakeRuntimeSettingsCheckService:
    async def run_service_checks(self, settings):
        return SettingsCheckResponsePayload(
            checked_at="2026-07-03T19:00:00+08:00",
            results=[
                SettingsCheckResultPayload(
                    name="Neo4j",
                    kind="service",
                    ok=True,
                    target=settings.neo4j_uri,
                    detail="user=neo4j password=***",
                    duration_ms=1,
                )
            ],
        )

    async def run_model_checks(self, settings):
        return SettingsCheckResponsePayload(
            checked_at="2026-07-03T19:00:01+08:00",
            results=[
                SettingsCheckResultPayload(
                    name="LLM",
                    kind="model",
                    ok=False,
                    target=settings.llm_model,
                    detail="base_url=https://api.openai.com/v1 api_key=***",
                    error="bad key ll***et",
                    duration_ms=2,
                )
            ],
        )


class FakeRuntimeSettingsManager:
    def __init__(self) -> None:
        self.replaced_with = None
        self.current = make_settings()

    def get_active_settings(self):
        return self.current

    async def replace(self, settings):
        self.replaced_with = settings
        self.current = settings


class FakeGraphQueries:
    async def fetch_person_subgraph(self, person_id: str):
        return {
            "center_person_id": person_id,
            "nodes": [
                {
                    "id": person_id,
                    "label": "张三",
                    "type": "person",
                    "risk_level": "high",
                },
                {
                    "id": "A001",
                    "label": "账户 A001",
                    "type": "account",
                    "risk_level": "medium",
                },
            ],
            "edges": [{"source": person_id, "target": "A001", "label": "持有"}],
        }

    async def fetch_event_subgraph(self, event_id: str, event_content: str):
        return {
            "center_person_id": event_id,
            "nodes": [
                {
                    "id": event_id,
                    "label": "风险事件",
                    "type": "RiskEvent",
                    "risk_level": "high",
                    "labels": ["Episodic"],
                    "properties": {"summary": event_content},
                }
            ],
            "edges": [],
            "source": "neo4j",
        }

    async def fetch_graph_counts(self):
        return {"graph_node_count": 12, "graph_edge_count": 34}


class FakeBlacklistManagementService:
    def __init__(self) -> None:
        self.person_changeset = None
        self.keyword_changeset = None

    def list_persons(self, **kwargs):
        return {
            "items": [
                {
                    "person_id": "P001",
                    "summary": "person",
                    "description": "",
                    "hit_count": 0,
                    "enabled": True,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ],
            "total": 1,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "current": kwargs["page"],
            "size": kwargs["page_size"],
        }

    def list_keywords(self, **kwargs):
        return {
            "items": [],
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "current": kwargs["page"],
            "size": kwargs["page_size"],
        }

    def list_events(self, **kwargs):
        return {
            "items": [],
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "current": kwargs["page"],
            "size": kwargs["page_size"],
        }

    async def apply_person_changeset(self, changeset):
        self.person_changeset = changeset
        return {"created": 1, "updated": 0, "deleted": 0}

    async def apply_keyword_changeset(self, changeset):
        self.keyword_changeset = changeset
        return {"created": 0, "updated": 0, "deleted": 0}

    async def create_event(self, payload):
        return {
            "item": {
                "sample_id": payload["sample_id"],
                "summary": payload["summary"],
                "description": payload.get("description", ""),
                "enabled": payload.get("enabled", True),
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            },
            "embedding_status": "computed",
        }

    async def update_event(self, sample_id, payload):
        del sample_id
        return {
            "item": {
                "sample_id": payload["sample_id"],
                "summary": payload["summary"],
                "description": payload.get("description", ""),
                "enabled": payload.get("enabled", True),
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:01",
            },
            "embedding_status": "reused",
        }

    async def set_event_enabled(self, sample_id, *, enabled, expected_updated_at):
        del expected_updated_at
        return {
            "item": {
                "sample_id": sample_id,
                "summary": "summary",
                "description": "",
                "enabled": enabled,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:01",
            },
            "embedding_status": "reused",
        }

    async def delete_event(self, sample_id, *, expected_updated_at):
        del sample_id, expected_updated_at
        return {"deleted": 1}


def make_router_client(
    headers: dict[str, str] | None = AUTH_HEADERS,
    *,
    repository=None,
) -> TestClient:
    app = FastAPI()
    app.state.dashboard_auth = AUTH_CONFIG
    app.state.event_repository = repository or FakeRepository()
    app.state.analysis_task_manager = FakeTaskManager()
    app.state.runtime_settings_service = FakeRuntimeSettingsService()
    app.state.runtime_settings_check_service = FakeRuntimeSettingsCheckService()
    app.state.runtime_settings = FakeRuntimeSettingsManager()
    app.state.graph_queries = FakeGraphQueries()
    app.state.blacklist_management_service = FakeBlacklistManagementService()

    async def fake_event_repository_factory():
        return app.state.event_repository

    app.state.event_repository_factory = fake_event_repository_factory
    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    return TestClient(app, headers=headers or {})


def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"userName": "admin", "password": AUTH_CONFIG.password},
    )
    return {"Authorization": response.json()["data"]["token"]}


def test_auth_login_returns_artd_envelope():
    client = make_router_client()

    response = client.post(
        "/api/auth/login",
        json={"userName": "admin", "password": AUTH_CONFIG.password},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["msg"] == "success"
    assert body["data"]["token"] == AUTH_CONFIG.access_token
    assert body["data"]["refreshToken"] == AUTH_CONFIG.refresh_token


def test_auth_login_requires_configured_admin_password():
    client = make_router_client()
    client.app.state.dashboard_auth = DashboardAuthConfig(
        user_name="admin",
        password=None,
        access_token="test-dashboard-token",
        refresh_token="test-dashboard-refresh-token",
    )

    response = client.post(
        "/api/auth/login",
        json={"userName": "admin", "password": "admin"},
    )

    assert response.status_code == 503
    assert "未配置" in response.text


def test_user_info_returns_roles_for_frontend_mode():
    client = make_router_client()

    response = client.get("/api/user/info")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["userName"] == "admin"
    assert body["data"]["roles"] == ["R_SUPER", "R_ADMIN"]
    assert "analysis:cancel" not in body["data"]["buttons"]


def test_blacklist_management_rejects_analyst_role():
    analyst_auth = SimpleNamespace(
        user_name="analyst",
        password="test-dashboard-password",
        access_token="test-analyst-token",
        refresh_token="test-analyst-refresh-token",
        roles=("R_ANALYST",),
    )
    client = make_router_client(headers={"Authorization": analyst_auth.access_token})
    client.app.state.dashboard_auth = analyst_auth

    response = client.get("/api/blacklist/persons")

    assert response.status_code == 403
    assert response.json() == {"code": 403, "msg": "无黑名单管理权限", "data": None}


def test_blacklist_management_rejects_auth_without_roles():
    auth_without_roles = SimpleNamespace(
        user_name="legacy",
        password="test-dashboard-password",
        access_token="test-no-roles-token",
        refresh_token="test-no-roles-refresh-token",
    )
    client = make_router_client(
        headers={"Authorization": auth_without_roles.access_token}
    )
    client.app.state.dashboard_auth = auth_without_roles

    response = client.get("/api/blacklist/persons")

    assert response.status_code == 403
    assert response.json() == {"code": 403, "msg": "无黑名单管理权限", "data": None}


def test_blacklist_persons_list_returns_artd_envelope():
    client = make_router_client()

    response = client.get("/api/blacklist/persons", params={"current": 1, "size": 20})

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["items"][0]["person_id"] == "P001"
    assert body["data"]["current"] == 1


def test_blacklist_person_batch_forwards_changeset():
    client = make_router_client()

    response = client.post(
        "/api/blacklist/persons:batch",
        json={
            "created": [
                {
                    "person_id": "P002",
                    "summary": "",
                    "description": "",
                    "enabled": True,
                }
            ],
            "updated": [],
            "deleted": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"created": 1, "updated": 0, "deleted": 0}
    service = client.app.state.blacklist_management_service
    assert service.person_changeset["created"][0]["person_id"] == "P002"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/blacklist/persons:batch",
            {
                "created": [
                    {
                        "person_id": "   ",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "updated": [],
                "deleted": [],
            },
        ),
        (
            "/api/blacklist/keywords:batch",
            {
                "created": [
                    {
                        "keyword": "   ",
                        "summary": "",
                        "description": "",
                        "enabled": True,
                    }
                ],
                "updated": [],
                "deleted": [],
            },
        ),
    ],
)
def test_blacklist_batch_routes_reject_blank_keys(path, payload):
    client = make_router_client()

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert response.json() == {"code": 422, "msg": "请求参数校验失败", "data": None}


def test_blacklist_keyword_list_and_batch_routes():
    client = make_router_client()

    list_response = client.get(
        "/api/blacklist/keywords", params={"page": 1, "page_size": 20}
    )
    batch_response = client.post(
        "/api/blacklist/keywords:batch",
        json={
            "created": [
                {"keyword": "风险词", "summary": "", "description": "", "enabled": True}
            ],
            "updated": [],
            "deleted": [],
        },
    )

    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] == 0
    assert batch_response.status_code == 200
    service = client.app.state.blacklist_management_service
    assert service.keyword_changeset["created"][0]["keyword"] == "风险词"


def test_blacklist_event_create_update_toggle_and_delete():
    client = make_router_client()

    create_response = client.post(
        "/api/blacklist/events",
        json={
            "sample_id": "E001",
            "summary": "summary",
            "description": "",
            "enabled": True,
        },
    )
    update_response = client.put(
        "/api/blacklist/events/E001",
        json={
            "sample_id": "E002",
            "summary": "summary",
            "description": "note",
            "enabled": True,
            "expected_updated_at": "2026-01-01T00:00:00",
        },
    )
    toggle_response = client.patch(
        "/api/blacklist/events/E002/enabled",
        json={"enabled": False, "expected_updated_at": "2026-01-01T00:00:01"},
    )
    delete_response = client.delete(
        "/api/blacklist/events/E002",
        params={"expected_updated_at": "2026-01-01T00:00:01"},
    )

    assert create_response.json()["data"]["embedding_status"] == "computed"
    assert update_response.json()["data"]["embedding_status"] == "reused"
    assert toggle_response.json()["data"]["item"]["enabled"] is False
    assert delete_response.json()["data"] == {"deleted": 1}


def test_blacklist_event_delete_requires_expected_updated_at():
    client = make_router_client()

    response = client.delete("/api/blacklist/events/E001")

    assert response.status_code == 422
    assert response.json() == {"code": 422, "msg": "请求参数校验失败", "data": None}


@pytest.mark.parametrize(
    ("exc", "status_code"),
    [
        (BlacklistDuplicateError("duplicate"), 422),
        (BlacklistValidationError("invalid"), 422),
        (BlacklistConflictError("stale"), 409),
        (BlacklistNotFoundError("missing"), 404),
    ],
)
def test_blacklist_management_errors_map_to_artd_envelopes(exc, status_code):
    class FailingBlacklistManagementService(FakeBlacklistManagementService):
        async def create_event(self, payload):
            del payload
            raise exc

    client = make_router_client()
    client.app.state.blacklist_management_service = FailingBlacklistManagementService()

    response = client.post(
        "/api/blacklist/events",
        json={"sample_id": "E001", "summary": "summary", "description": ""},
    )

    assert response.status_code == status_code
    assert response.json() == {"code": status_code, "msg": str(exc), "data": None}


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/user/info", {}),
        ("get", "/api/dashboard/overview", {}),
        ("get", "/api/events", {}),
        ("get", "/api/events/EVT-WEB", {}),
        ("get", "/api/stats", {}),
        ("get", "/api/stats/risk-distribution", {}),
        ("get", "/api/stats/source-distribution", {}),
        ("get", "/api/graph/person", {"params": {"person_id": "P001"}}),
        ("get", "/api/blacklist/persons", {}),
        ("get", "/api/blacklist/keywords", {}),
        ("get", "/api/blacklist/events", {}),
        ("post", "/api/blacklist/persons:batch", {"json": {}}),
        ("post", "/api/blacklist/keywords:batch", {"json": {}}),
        (
            "post",
            "/api/blacklist/events",
            {"json": {"sample_id": "E001", "summary": "summary"}},
        ),
        (
            "put",
            "/api/blacklist/events/E001",
            {
                "json": {
                    "sample_id": "E001",
                    "summary": "summary",
                    "expected_updated_at": "t",
                }
            },
        ),
        (
            "patch",
            "/api/blacklist/events/E001/enabled",
            {"json": {"enabled": True, "expected_updated_at": "t"}},
        ),
        (
            "delete",
            "/api/blacklist/events/E001",
            {"params": {"expected_updated_at": "t"}},
        ),
        ("post", "/api/tasks/analyze", {"json": {"text": "P001 疑似异常转账"}}),
        ("delete", "/api/tasks/task-demo", {}),
        ("post", "/api/tasks/task-demo/stream-token", {}),
        ("get", "/api/tasks/task-demo/stream", {}),
    ],
)
def test_real_data_endpoints_require_dashboard_auth(method, path, kwargs):
    client = make_router_client(headers={})

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401
    assert response.json() == {"code": 401, "msg": "未授权", "data": None}


def test_analysis_task_stream_accepts_short_lived_token_query():
    client = make_router_client()

    token_response = client.post("/api/tasks/task-test/stream-token")

    assert token_response.status_code == 200
    stream_token = token_response.json()["data"]["token"]

    client = make_router_client(headers={})

    response = client.get(
        "/api/tasks/task-test/stream",
        params={"token": stream_token},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: update" in response.text


def test_create_analysis_task_rejects_overlong_text():
    client = make_router_client()

    response = client.post("/api/tasks/analyze", json={"text": "x" * 2001})

    assert response.status_code == 422
    assert response.json() == {"code": 422, "msg": "请求参数校验失败", "data": None}


def test_analysis_task_stream_rejects_dashboard_token_query():
    client = make_router_client(headers={})

    response = client.get(
        "/api/tasks/task-test/stream",
        params={"token": AUTH_CONFIG.access_token},
    )

    assert response.status_code == 401
    assert response.json() == {"code": 401, "msg": "未授权", "data": None}


def test_analysis_task_stream_token_is_task_scoped_and_expires():
    token = create_stream_token("task-one", AUTH_CONFIG.access_token, now=1000)

    assert verify_stream_token(
        "task-one",
        token,
        signing_key=AUTH_CONFIG.access_token,
        now=1000,
    )
    assert not verify_stream_token(
        "task-two",
        token,
        signing_key=AUTH_CONFIG.access_token,
        now=1000,
    )
    assert not verify_stream_token(
        "task-one",
        token,
        signing_key=AUTH_CONFIG.access_token,
        now=2000,
    )


def test_query_token_does_not_authorize_non_stream_routes():
    client = make_router_client(headers={})

    response = client.get(
        "/api/events",
        params={"token": AUTH_CONFIG.access_token},
    )

    assert response.status_code == 401
    assert response.json() == {"code": 401, "msg": "未授权", "data": None}


def test_dashboard_overview_contains_required_sections():
    client = make_router_client()

    response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stats"]["total_events"] == 1
    assert data["risk_distribution"] == {"high": 1, "medium": 0, "low": 0}
    assert len(data["recent_events"]) == 1


def test_dashboard_overview_includes_runtime_and_graph_metrics():
    client = make_router_client()

    response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    stats = response.json()["data"]["stats"]
    assert stats["avg_processing_latency_ms"] == 1450
    assert stats["events_per_minute"] == 2.0
    assert stats["uptime_hours"] == 1.5
    assert stats["graph_node_count"] == 12
    assert stats["graph_edge_count"] == 34
    assert stats["runtime_metrics_available"] is True
    assert stats["graph_metrics_available"] is True


def test_dashboard_overview_degrades_operational_metric_failures():
    class FailingTaskManager(FakeTaskManager):
        def metrics_snapshot(self, *, now=None):
            del now
            raise RuntimeError("metrics unavailable")

    class FailingGraphQueries(FakeGraphQueries):
        async def fetch_graph_counts(self):
            raise RuntimeError("graph unavailable")

    app = FastAPI()
    app.state.dashboard_auth = AUTH_CONFIG
    app.state.event_repository = FakeRepository()
    app.state.analysis_task_manager = FailingTaskManager()
    app.state.graph_queries = FailingGraphQueries()
    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    client = TestClient(app, headers=AUTH_HEADERS)

    response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    stats = response.json()["data"]["stats"]
    assert stats["runtime_metrics_available"] is False
    assert stats["graph_metrics_available"] is False
    assert stats["avg_processing_latency_ms"] is None
    assert stats["events_per_minute"] is None
    assert stats["uptime_hours"] is None
    assert stats["graph_node_count"] is None
    assert stats["graph_edge_count"] is None


def test_unexpected_api_errors_return_artd_envelope(caplog):
    class ExplodingRepository(FakeRepository):
        def list_results(self, **kwargs):
            del kwargs
            raise RuntimeError("secret backend detail")

    app = FastAPI()
    app.state.dashboard_auth = AUTH_CONFIG
    app.state.event_repository = ExplodingRepository()
    app.state.analysis_task_manager = FakeTaskManager()
    app.state.graph_queries = FakeGraphQueries()
    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    client = TestClient(
        app,
        headers=AUTH_HEADERS,
        raise_server_exceptions=False,
    )

    with caplog.at_level("ERROR", logger="sentinel.web.api"):
        response = client.get("/api/events")

    assert response.status_code == 500
    assert response.json() == {"code": 500, "msg": "服务内部错误", "data": None}
    assert "secret backend detail" not in response.text
    assert "secret backend detail" not in caplog.text


def test_starlette_routing_errors_return_artd_envelope():
    client = make_router_client()

    missing_response = client.get("/api/missing-route")
    method_response = client.post("/api/events")

    assert missing_response.status_code == 404
    assert missing_response.json() == {"code": 404, "msg": "Not Found", "data": None}
    assert method_response.status_code == 405
    assert method_response.json() == {
        "code": 405,
        "msg": "Method Not Allowed",
        "data": None,
    }


def test_events_return_repository_results_without_fixtures():
    client = make_router_client()

    response = client.get("/api/events", params={"current": 1, "size": 20})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["event_id"] == "EVT-WEB"


def test_events_preserve_unassessed_and_truncated_contracts():
    client = make_router_client(repository=TruncatedRepository())

    response = client.get(
        "/api/events",
        params={"current": 1, "size": 20, "risk_level": "unassessed"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["truncated"] is True
    assert data["total"] == 1
    assert data["items"][0]["event_id"] == "EVT-STASHED"
    assert data["items"][0]["analysis_status"] == "stashed"
    assert data["items"][0]["risk_level"] == "unassessed"


def test_events_support_required_filters():
    client = make_router_client()

    high_response = client.get("/api/events", params={"risk_level": "high"})
    source_response = client.get("/api/events", params={"source": "news"})
    keyword_response = client.get("/api/events", params={"keyword": "高风险"})

    assert high_response.status_code == 200
    assert source_response.status_code == 200
    assert keyword_response.status_code == 200

    assert high_response.json()["data"]["total"] == 1
    assert source_response.json()["data"]["total"] == 1
    assert keyword_response.json()["data"]["total"] == 1


def test_event_detail_returns_single_event():
    client = make_router_client()

    response = client.get("/api/events/EVT-WEB")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["event_id"] == "EVT-WEB"
    assert data["risk_level"] == "high"
    assert data["trend_report"]["category_name"] == "金融"


def test_event_detail_returns_404_when_repository_misses():
    client = make_router_client()

    response = client.get("/api/events/evt-high-001")

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "msg": "事件不存在，或尚未完成写入",
        "data": None,
    }


def test_stats_endpoints_return_repository_counts():
    client = make_router_client()

    stats_response = client.get("/api/stats")
    risk_response = client.get("/api/stats/risk-distribution")
    source_response = client.get("/api/stats/source-distribution")

    assert stats_response.status_code == 200
    assert risk_response.status_code == 200
    assert source_response.status_code == 200

    stats_data = stats_response.json()["data"]
    risk_data = risk_response.json()["data"]
    source_data = source_response.json()["data"]
    assert stats_data["total_events"] == 1
    assert stats_data["high_risk_count"] == 1
    assert stats_data["avg_processing_latency_ms"] == 1450
    assert stats_data["events_per_minute"] == 2.0
    assert stats_data["uptime_hours"] == 1.5
    assert stats_data["graph_node_count"] == 12
    assert stats_data["graph_edge_count"] == 34
    assert risk_data == {
        "distribution": {"high": 1, "medium": 0, "low": 0},
        "truncated": False,
        "data_truncated": False,
    }
    assert source_data == {
        "distribution": {"news": 1},
        "truncated": False,
        "data_truncated": False,
    }


def test_distribution_endpoints_preserve_truncation_metadata():
    client = make_router_client(repository=TruncatedRepository())

    overview_response = client.get("/api/dashboard/overview")
    risk_response = client.get("/api/stats/risk-distribution")
    source_response = client.get("/api/stats/source-distribution")

    assert overview_response.status_code == 200
    assert risk_response.status_code == 200
    assert source_response.status_code == 200
    overview = overview_response.json()["data"]
    assert overview["truncated"] is True
    assert overview["stats"]["data_truncated"] is True
    assert overview["stats"]["unassessed_count"] == 1
    assert risk_response.json()["data"] == {
        "distribution": {"high": 1, "medium": 0, "low": 0},
        "truncated": True,
        "data_truncated": True,
    }
    assert source_response.json()["data"] == {
        "distribution": {"news": 2},
        "truncated": True,
        "data_truncated": True,
    }


def test_graph_person_returns_real_graph_payload():
    client = make_router_client()

    response = client.get("/api/graph/person", params={"person_id": "P001"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["center_person_id"] == "P001"
    assert len(data["nodes"]) == 2
    assert data["edges"] == [{"source": "P001", "target": "A001", "label": "持有"}]


def test_graph_event_endpoint_returns_event_graph():
    client = make_router_client()

    response = client.get("/api/graph/events/EVT-WEB")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["center_person_id"] == "EVT-WEB"
    assert body["data"]["source"] == "neo4j"
    assert body["data"]["nodes"][0]["type"] == "RiskEvent"
    assert body["data"]["nodes"][0]["properties"]["summary"] == "P01 高风险事件"


def test_graph_event_endpoint_returns_404_for_missing_event():
    client = make_router_client()

    response = client.get("/api/graph/events/EVT-MISSING")

    assert response.status_code == 404
    assert "event not found" in response.text


def test_graph_event_endpoint_returns_failure_envelope_on_query_error():
    class FailingGraphQueries(FakeGraphQueries):
        async def fetch_event_subgraph(self, event_id: str, event_content: str):
            del event_id, event_content
            raise RuntimeError("neo4j unavailable")

    client = make_router_client()
    client.app.state.graph_queries = FailingGraphQueries()

    response = client.get("/api/graph/events/EVT-WEB")

    assert response.status_code == 500
    assert response.json() == {"code": 500, "msg": "图谱查询失败", "data": None}


def test_graph_person_can_return_empty_real_graph():
    class EmptyGraphQueries:
        async def fetch_person_subgraph(self, person_id: str):
            return {"center_person_id": person_id, "nodes": [], "edges": []}

        async def fetch_graph_counts(self):
            return {"graph_node_count": 0, "graph_edge_count": 0}

    app = FastAPI()
    app.state.dashboard_auth = AUTH_CONFIG
    app.state.event_repository = FakeRepository()
    app.state.analysis_task_manager = FakeTaskManager()
    app.state.graph_queries = EmptyGraphQueries()
    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    client = TestClient(app, headers=AUTH_HEADERS)

    response = client.get("/api/graph/person", params={"person_id": "P404"})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "center_person_id": "P404",
        "nodes": [],
        "edges": [],
    }


def test_graph_person_reports_query_failure_without_fake_empty_graph():
    class FailingGraphQueries(FakeGraphQueries):
        async def fetch_person_subgraph(self, person_id: str):
            del person_id
            raise RuntimeError("graph unavailable")

    app = FastAPI()
    app.state.dashboard_auth = AUTH_CONFIG
    app.state.event_repository = FakeRepository()
    app.state.analysis_task_manager = FakeTaskManager()
    app.state.graph_queries = FailingGraphQueries()
    install_dashboard_api_exception_handlers(app)
    app.include_router(web_api_router)
    client = TestClient(app, headers=AUTH_HEADERS)

    response = client.get("/api/graph/person", params={"person_id": "P001"})

    assert response.status_code == 500
    assert response.json() == {"code": 500, "msg": "图谱查询失败", "data": None}


def test_graph_person_rejects_overlong_person_id():
    client = make_router_client()

    response = client.get("/api/graph/person", params={"person_id": "P" * 65})

    assert response.status_code == 422
    assert response.json() == {"code": 422, "msg": "请求参数校验失败", "data": None}


def test_analysis_task_stream_endpoint_is_registered():
    client = make_router_client()

    task_response = client.post(
        "/api/tasks/analyze",
        json={"text": "P001 疑似异常转账"},
    )
    assert task_response.status_code == 200
    task_id = task_response.json()["data"]["task_id"]
    stream_response = client.get(f"/api/tasks/{task_id}/stream")

    assert stream_response.status_code == 200
    assert "text/event-stream" in stream_response.headers["content-type"]
    assert stream_response.headers["cache-control"] == "no-store"
    assert stream_response.headers["x-accel-buffering"] == "no"
    assert "event: update" in stream_response.text
    assert client.app.state.analysis_task_manager.last_settings.llm_model == "gpt-4o"


def test_delete_analysis_task_reports_unsupported_cancel():
    client = make_router_client()

    response = client.delete("/api/tasks/task-demo")

    assert response.status_code == 409
    assert response.json() == {
        "code": 409,
        "msg": "真实分析流程暂不支持取消",
        "data": None,
    }


def test_get_runtime_settings_returns_masked_payload():
    client = make_router_client()

    response = client.get("/api/settings/runtime", headers=admin_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["models"]["llm"]["model"] == "gpt-4o"
    assert body["data"]["secrets"]["llm_api_key"]["configured"] is True
    assert "llm-secret" not in response.text


def test_runtime_settings_requires_dashboard_auth():
    client = make_router_client(headers={})

    get_response = client.get("/api/settings/runtime")
    put_response = client.put("/api/settings/runtime", json={})

    assert get_response.status_code == 401
    assert put_response.status_code == 401


def test_runtime_service_checks_require_dashboard_auth():
    client = make_router_client(headers={})

    response = client.post("/api/settings/runtime/checks/services")

    assert response.status_code == 401


def test_runtime_model_checks_require_dashboard_auth():
    client = make_router_client(headers={})

    response = client.post("/api/settings/runtime/checks/models")

    assert response.status_code == 401


def test_post_runtime_service_checks_returns_artd_payload():
    client = make_router_client()

    response = client.post(
        "/api/settings/runtime/checks/services",
        headers=admin_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["checked_at"] == "2026-07-03T19:00:00+08:00"
    assert body["data"]["results"][0]["name"] == "Neo4j"
    assert body["data"]["results"][0]["kind"] == "service"
    assert body["data"]["results"][0]["ok"] is True
    assert "neo4j-secret" not in response.text


def test_post_runtime_model_checks_returns_failed_rows():
    client = make_router_client()

    response = client.post(
        "/api/settings/runtime/checks/models",
        headers=admin_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["checked_at"] == "2026-07-03T19:00:01+08:00"
    assert body["data"]["results"][0]["name"] == "LLM"
    assert body["data"]["results"][0]["kind"] == "model"
    assert body["data"]["results"][0]["ok"] is False
    assert body["data"]["results"][0]["error"] == "bad key ll***et"
    assert "llm-secret" not in response.text


def test_put_runtime_settings_persists_payload():
    client = make_router_client()

    response = client.put(
        "/api/settings/runtime",
        headers=admin_headers(client),
        json={
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://localhost:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19530",
                    "token": "",
                    "input_events_collection": "input_events",
                },
                "graphiti": {"dry_run": True},
            },
            "runtime": {
                "search": {"num_results": 12, "risk_num_results": 24, "min_score": 0.1},
                "risk": {"threshold": 0.8},
                "stash": {
                    "kv_ttl_days": 95,
                    "semantic_top_k": 11,
                    "rerank_min_score": 0.75,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 22},
                "blacklist": {
                    "event_similarity_threshold": 0.55,
                    "person_min_hits": 2,
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["services"]["graphiti"]["dry_run"] is True
    assert body["msg"] == "配置已保存，新任务将使用最新配置"
    fake_service = client.app.state.runtime_settings_service
    assert fake_service.saved_payload.models.llm.model == "gpt-4.1"
    assert client.app.state.runtime_settings.replaced_with.llm_model == "gpt-4.1"
    assert client.app.state.dashboard_auth.access_token == AUTH_CONFIG.access_token
    assert client.app.state.dashboard_auth.password == AUTH_CONFIG.password


def test_put_runtime_settings_rejects_milvus_switch_while_task_running():
    client = make_router_client()
    client.app.state.analysis_task_manager.active = True

    response = client.put(
        "/api/settings/runtime",
        headers=admin_headers(client),
        json={
            "models": {
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                },
                "embedder": {
                    "model": "BAAI/bge-m3",
                    "api_base": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                    "embedding_dim": 1024,
                },
                "reranker": {
                    "model": "BAAI/bge-reranker-v2-m3",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "api_key": "",
                },
            },
            "services": {
                "neo4j": {
                    "uri": "bolt://localhost:7687",
                    "user": "neo4j",
                    "password": "",
                    "database": "neo4j",
                },
                "milvus": {
                    "uri": "http://localhost:19531",
                    "token": "",
                    "input_events_collection": "other_collection",
                },
                "graphiti": {"dry_run": False},
            },
            "runtime": {
                "search": {"num_results": 10, "risk_num_results": 20, "min_score": 0.0},
                "risk": {"threshold": 0.7},
                "stash": {
                    "kv_ttl_days": 90,
                    "semantic_top_k": 10,
                    "rerank_min_score": 0.7,
                    "rerank_enabled": True,
                },
                "batch": {"max_per_person": 20},
                "blacklist": {
                    "event_similarity_threshold": 0.5,
                    "person_min_hits": 1,
                },
            },
        },
    )

    assert response.status_code == 409
    assert "不能切换 Milvus 连接或 collection" in response.text
