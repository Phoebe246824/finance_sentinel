"""Web 看板 FastAPI：ArtD 兼容 envelope、认证与路由映射。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from sentinel.blacklist.management import BlacklistManagementError
from sentinel.config import SentinelSettings
from sentinel.web.models import (
    BlacklistEnabledPayload,
    BlacklistEventCreatePayload,
    BlacklistEventUpdatePayload,
    BlacklistKeywordBatchPayload,
    BlacklistPersonBatchPayload,
    DashboardOverviewPayload,
)
from sentinel.web.settings_checks import RuntimeSettingsCheckService
from sentinel.web.settings_models import RuntimeSettingsUpdatePayload

router = APIRouter()
logger = logging.getLogger(__name__)
STREAM_TOKEN_TTL_SECONDS = 15 * 60


class LoginRequest(BaseModel):
    user_name: str = Field(alias="userName")
    password: str


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True, slots=True)
class DashboardAuthConfig:
    user_name: str
    password: str | None
    access_token: str
    refresh_token: str
    roles: tuple[str, ...] = ("R_SUPER", "R_ADMIN")


def ok(data: Any, msg: str = "success") -> dict[str, Any]:
    return {"code": 200, "msg": msg, "data": data}


def error(status_code: int, msg: str) -> dict[str, Any]:
    return {"code": status_code, "msg": msg, "data": None}


def create_dashboard_auth_config(settings: SentinelSettings) -> DashboardAuthConfig:
    return DashboardAuthConfig(
        user_name=settings.dashboard_admin_user,
        password=settings.optional_dashboard_admin_password(),
        access_token=(
            settings.optional_dashboard_access_token() or secrets.token_urlsafe(32)
        ),
        refresh_token=(
            settings.optional_dashboard_refresh_token() or secrets.token_urlsafe(32)
        ),
    )


def refresh_dashboard_auth_config(
    settings: SentinelSettings,
    current: DashboardAuthConfig,
) -> DashboardAuthConfig:
    return DashboardAuthConfig(
        user_name=settings.dashboard_admin_user,
        password=settings.optional_dashboard_admin_password(),
        access_token=settings.optional_dashboard_access_token() or current.access_token,
        refresh_token=settings.optional_dashboard_refresh_token()
        or current.refresh_token,
    )


def dashboard_auth_config(request: Request) -> DashboardAuthConfig:
    auth = getattr(request.app.state, "dashboard_auth", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="看板认证未初始化")
    return auth


def install_dashboard_api_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content=error(exc.status_code, msg=str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=422,
            content=error(422, msg="请求参数校验失败"),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "dashboard api unexpected error: type=%s path=%s",
            type(exc).__name__,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=error(500, msg="服务内部错误"),
        )


def require_dashboard_auth(
    request: Request,
) -> None:
    auth = dashboard_auth_config(request)
    if request.headers.get("Authorization") == auth.access_token:
        return
    raise HTTPException(status_code=401, detail="未授权")


def require_dashboard_stream_auth(
    request: Request,
    task_id: str,
    token: str | None = Query(default=None),
) -> None:
    auth = dashboard_auth_config(request)
    if request.headers.get("Authorization") == auth.access_token:
        return
    if token is not None and verify_stream_token(
        task_id,
        token,
        signing_key=auth.access_token,
    ):
        return
    raise HTTPException(status_code=401, detail="未授权")


PROTECTED_ROUTE_DEPENDENCIES = [Depends(require_dashboard_auth)]


def require_blacklist_management_auth(request: Request) -> None:
    require_dashboard_auth(request)
    auth = dashboard_auth_config(request)
    roles = tuple(getattr(auth, "roles", ()))
    if {"R_SUPER", "R_ADMIN"}.isdisjoint(roles):
        raise HTTPException(status_code=403, detail="无黑名单管理权限")


BLACKLIST_MANAGEMENT_DEPENDENCIES = [Depends(require_blacklist_management_auth)]


def create_stream_token(
    task_id: str,
    signing_key: str,
    *,
    now: float | None = None,
) -> str:
    expires_at = int(
        (now if now is not None else time.time()) + STREAM_TOKEN_TTL_SECONDS
    )
    signature = _stream_token_signature(task_id, expires_at, signing_key)
    return f"{task_id}.{expires_at}.{signature}"


def verify_stream_token(
    task_id: str,
    token: str,
    signing_key: str,
    *,
    now: float | None = None,
) -> bool:
    try:
        token_task_id, expires_at_text, signature = token.split(".", 2)
        expires_at = int(expires_at_text)
    except ValueError:
        return False
    if token_task_id != task_id:
        return False
    if expires_at < int(now if now is not None else time.time()):
        return False
    expected_signature = _stream_token_signature(token_task_id, expires_at, signing_key)
    return hmac.compare_digest(signature, expected_signature)


def _stream_token_signature(
    task_id: str,
    expires_at: int,
    signing_key: str,
) -> str:
    return hmac.new(
        signing_key.encode("utf-8"),
        f"{task_id}:{expires_at}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def event_repository(request: Request):
    repository = getattr(request.app.state, "event_repository", None)
    if repository is not None:
        return repository
    factory = getattr(request.app.state, "event_repository_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="事件仓库未初始化")
    repository = await factory()
    request.app.state.event_repository = repository
    return repository


def task_manager(request: Request):
    manager = getattr(request.app.state, "analysis_task_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="分析任务管理器未初始化")
    return manager


def runtime_settings_service(request: Request):
    service = getattr(request.app.state, "runtime_settings_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="运行时配置服务未初始化")
    return service


def runtime_settings_check_service(request: Request):
    service = getattr(request.app.state, "runtime_settings_check_service", None)
    if service is not None:
        return service
    service = RuntimeSettingsCheckService()
    request.app.state.runtime_settings_check_service = service
    return service


def active_settings(request: Request):
    runtime_settings = getattr(request.app.state, "runtime_settings", None)
    if runtime_settings is not None:
        return runtime_settings.get_active_settings()
    settings = getattr(request.app.state, "settings", None)
    if settings is not None:
        return settings
    raise HTTPException(status_code=503, detail="运行时配置未初始化")


def graph_queries(request: Request):
    queries = getattr(request.app.state, "graph_queries", None)
    if queries is None:
        raise HTTPException(status_code=503, detail="图谱查询能力未初始化")
    return queries


async def blacklist_management_service(request: Request):
    service = getattr(request.app.state, "blacklist_management_service", None)
    if service is not None:
        return service
    factory = getattr(request.app.state, "blacklist_management_service_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="黑名单管理服务未初始化")
    service = await factory(request)
    request.app.state.blacklist_management_service = service
    return service


def _blacklist_error(exc: BlacklistManagementError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _dashboard_overview_payload(request: Request) -> DashboardOverviewPayload:
    repository = await event_repository(request)
    base = repository.overview()
    manager = task_manager(request)
    queries = graph_queries(request)
    try:
        runtime_metrics = manager.metrics_snapshot()
    except Exception as exc:
        logger.warning(
            "dashboard runtime metrics snapshot failed: type=%s",
            type(exc).__name__,
        )
        runtime_metrics = {
            "avg_processing_latency_ms": None,
            "events_per_minute": None,
            "uptime_hours": None,
        }
        base.stats.runtime_metrics_available = False
    try:
        graph_counts = await queries.fetch_graph_counts()
    except Exception as exc:
        logger.warning(
            "dashboard graph counts query failed: type=%s",
            type(exc).__name__,
        )
        graph_counts = {"graph_node_count": None, "graph_edge_count": None}
        base.stats.graph_metrics_available = False

    latency_ms = runtime_metrics.get("avg_processing_latency_ms")
    events_per_minute = runtime_metrics.get("events_per_minute")
    uptime_hours = runtime_metrics.get("uptime_hours")
    graph_node_count = graph_counts.get("graph_node_count")
    graph_edge_count = graph_counts.get("graph_edge_count")
    base.stats.avg_processing_latency_ms = (
        int(latency_ms) if latency_ms is not None else None
    )
    base.stats.events_per_minute = (
        float(events_per_minute) if events_per_minute is not None else None
    )
    base.stats.uptime_hours = float(uptime_hours) if uptime_hours is not None else None
    base.stats.graph_node_count = (
        int(graph_node_count) if graph_node_count is not None else None
    )
    base.stats.graph_edge_count = (
        int(graph_edge_count) if graph_edge_count is not None else None
    )
    return base


@router.post("/api/auth/login")
async def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
    auth = dashboard_auth_config(request)
    if auth.password is None:
        raise HTTPException(status_code=503, detail="看板登录密码未配置")
    if payload.user_name != auth.user_name or payload.password != auth.password:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return ok(
        {
            "token": auth.access_token,
            "refreshToken": auth.refresh_token,
        }
    )


@router.get("/api/user/info", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def user_info(request: Request) -> dict[str, Any]:
    auth = dashboard_auth_config(request)
    return ok(
        {
            "buttons": ["analysis:start", "events:view"],
            "roles": list(getattr(auth, "roles", ("R_SUPER", "R_ADMIN"))),
            "userId": 1,
            "userName": auth.user_name,
            "email": f"{auth.user_name}@sentinel.local",
            "avatar": "",
        }
    )


@router.get("/api/dashboard/overview", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def dashboard_overview(request: Request) -> dict[str, Any]:
    return ok((await _dashboard_overview_payload(request)).model_dump())


@router.get("/api/events", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def events(
    request: Request,
    current: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source: str | None = None,
    risk_level: str | None = None,
    event_type: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    resolved_page = current or page
    resolved_size = size or page_size
    repository = await event_repository(request)
    result = repository.list_results(
        page=resolved_page,
        page_size=resolved_size,
        source=source,
        risk_level=risk_level,
        event_type=event_type,
        keyword=keyword,
    )
    return ok(result.model_dump())


@router.get("/api/events/{event_id}", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def event_detail(request: Request, event_id: str) -> dict[str, Any]:
    repository = await event_repository(request)
    event = repository.get_result(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在，或尚未完成写入")
    return ok(event.model_dump())


@router.get("/api/stats", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def stats(request: Request) -> dict[str, Any]:
    return ok((await _dashboard_overview_payload(request)).stats.model_dump())


@router.get(
    "/api/stats/risk-distribution",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def risk_distribution_data(request: Request) -> dict[str, Any]:
    repository = await event_repository(request)
    overview = repository.overview()
    return ok(
        {
            "distribution": overview.risk_distribution,
            "truncated": overview.truncated,
            "data_truncated": overview.stats.data_truncated,
        }
    )


@router.get(
    "/api/stats/source-distribution",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def source_distribution_data(request: Request) -> dict[str, Any]:
    repository = await event_repository(request)
    overview = repository.overview()
    return ok(
        {
            "distribution": overview.source_distribution,
            "truncated": overview.truncated,
            "data_truncated": overview.stats.data_truncated,
        }
    )


@router.get("/api/graph/person", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def graph_person(
    request: Request,
    person_id: str = Query(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    try:
        data = await graph_queries(request).fetch_person_subgraph(person_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("person graph query failed: type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "图谱查询失败", "data": None},
        )
    return ok(data)


@router.get("/api/graph/events/{event_id}", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def graph_event(request: Request, event_id: str) -> dict[str, Any]:
    repository = await event_repository(request)
    event = repository.get_result(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    try:
        data = await graph_queries(request).fetch_event_subgraph(
            event_id,
            event.raw_content,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("event graph query failed: type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "图谱查询失败", "data": None},
        )
    return ok(data)


@router.get("/api/blacklist/persons", dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES)
async def blacklist_persons(
    request: Request,
    current: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    return ok(
        service.list_persons(
            keyword=keyword,
            enabled=enabled,
            page=current or page,
            page_size=size or page_size,
        )
    )


@router.post(
    "/api/blacklist/persons:batch",
    dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES,
)
async def blacklist_persons_batch(
    request: Request,
    payload: BlacklistPersonBatchPayload,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.apply_person_changeset(payload.model_dump())
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.get("/api/blacklist/keywords", dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES)
async def blacklist_keywords(
    request: Request,
    current: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    return ok(
        service.list_keywords(
            keyword=keyword,
            enabled=enabled,
            page=current or page,
            page_size=size or page_size,
        )
    )


@router.post(
    "/api/blacklist/keywords:batch",
    dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES,
)
async def blacklist_keywords_batch(
    request: Request,
    payload: BlacklistKeywordBatchPayload,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.apply_keyword_changeset(payload.model_dump())
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.get("/api/blacklist/events", dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES)
async def blacklist_events(
    request: Request,
    current: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    return ok(
        service.list_events(
            keyword=keyword,
            enabled=enabled,
            page=current or page,
            page_size=size or page_size,
        )
    )


@router.post("/api/blacklist/events", dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES)
async def create_blacklist_event(
    request: Request,
    payload: BlacklistEventCreatePayload,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.create_event(payload.model_dump())
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.put(
    "/api/blacklist/events/{sample_id}",
    dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES,
)
async def update_blacklist_event(
    request: Request,
    sample_id: str,
    payload: BlacklistEventUpdatePayload,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.update_event(
            sample_id,
            payload.model_dump(),
        )
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.patch(
    "/api/blacklist/events/{sample_id}/enabled",
    dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES,
)
async def update_blacklist_event_enabled(
    request: Request,
    sample_id: str,
    payload: BlacklistEnabledPayload,
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.set_event_enabled(
            sample_id,
            enabled=payload.enabled,
            expected_updated_at=payload.expected_updated_at,
        )
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.delete(
    "/api/blacklist/events/{sample_id}",
    dependencies=BLACKLIST_MANAGEMENT_DEPENDENCIES,
)
async def delete_blacklist_event(
    request: Request,
    sample_id: str,
    expected_updated_at: str = Query(..., min_length=1, max_length=64),
) -> dict[str, Any]:
    service = await blacklist_management_service(request)
    try:
        data = await service.delete_event(
            sample_id,
            expected_updated_at=expected_updated_at,
        )
    except BlacklistManagementError as exc:
        raise _blacklist_error(exc) from exc
    return ok(data)


@router.get(
    "/api/settings/runtime",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def get_runtime_settings(request: Request) -> dict[str, Any]:
    payload = runtime_settings_service(request).read_runtime_settings()
    return ok(payload.model_dump())


@router.put(
    "/api/settings/runtime",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def update_runtime_settings(
    request: Request,
    payload: RuntimeSettingsUpdatePayload,
) -> dict[str, Any]:
    current_settings = request.app.state.runtime_settings.get_active_settings()
    desired_milvus_token = (
        payload.services.milvus.token or current_settings.optional_milvus_token() or ""
    )
    milvus_target_changed = any(
        (
            payload.services.milvus.uri != current_settings.milvus_uri,
            payload.services.milvus.input_events_collection
            != current_settings.milvus_input_events_collection,
            desired_milvus_token != (current_settings.optional_milvus_token() or ""),
        )
    )
    if milvus_target_changed and task_manager(request).has_active_tasks():
        raise HTTPException(
            status_code=409,
            detail="存在运行中的分析任务时，不能切换 Milvus 连接或 collection，请等待任务完成后再保存该类配置",
        )

    service = runtime_settings_service(request)
    try:
        saved = service.save_runtime_settings(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="配置校验失败，请检查必填项、取值范围和密钥格式",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="配置保存失败，请检查配置文件权限",
        ) from exc
    new_settings = service.current_settings()
    await request.app.state.runtime_settings.replace(new_settings)
    request.app.state.dashboard_auth = refresh_dashboard_auth_config(
        new_settings,
        dashboard_auth_config(request),
    )
    graph_query_factory = getattr(request.app.state, "graph_queries_factory", None)
    if graph_query_factory is not None:
        request.app.state.graph_queries = graph_query_factory(new_settings)
    request.app.state.event_repository = None
    request.app.state.blacklist_management_service = None
    return ok(saved.model_dump(), msg="配置已保存，新任务将使用最新配置")


@router.post(
    "/api/settings/runtime/checks/services",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def check_runtime_services(request: Request) -> dict[str, Any]:
    settings = request.app.state.runtime_settings.get_active_settings()
    payload = await runtime_settings_check_service(request).run_service_checks(settings)
    return ok(payload.model_dump())


@router.post(
    "/api/settings/runtime/checks/models",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def check_runtime_models(request: Request) -> dict[str, Any]:
    settings = request.app.state.runtime_settings.get_active_settings()
    payload = await runtime_settings_check_service(request).run_model_checks(settings)
    return ok(payload.model_dump())


@router.post("/api/tasks/analyze", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def create_analysis_task(
    request: Request,
    payload: AnalyzeRequest,
) -> dict[str, Any]:
    try:
        settings = request.app.state.runtime_settings.get_active_settings()
        task = task_manager(request).create_task(payload.text, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(task.to_dict())


@router.delete("/api/tasks/{task_id}", dependencies=PROTECTED_ROUTE_DEPENDENCIES)
async def cancel_analysis_task(task_id: str) -> dict[str, Any]:
    del task_id
    raise HTTPException(status_code=409, detail="真实分析流程暂不支持取消")


@router.post(
    "/api/tasks/{task_id}/stream-token",
    dependencies=PROTECTED_ROUTE_DEPENDENCIES,
)
async def create_analysis_task_stream_token(
    request: Request,
    task_id: str,
) -> dict[str, Any]:
    if task_manager(request).get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    auth = dashboard_auth_config(request)
    return ok(
        {
            "token": create_stream_token(task_id, auth.access_token),
            "expires_in_seconds": STREAM_TOKEN_TTL_SECONDS,
        }
    )


@router.get(
    "/api/tasks/{task_id}/stream",
    dependencies=[Depends(require_dashboard_stream_auth)],
)
async def stream_analysis_task(request: Request, task_id: str) -> StreamingResponse:
    async def event_stream():
        try:
            async for update in task_manager(request).stream_updates(task_id):
                yield (
                    "event: update\n"
                    f"data: {json.dumps(update.to_dict(), ensure_ascii=False)}\n\n"
                )
        except KeyError:
            yield (
                "event: update\n"
                f"data: {json.dumps({'task_id': task_id, 'status': 'failed', 'error_message': '任务不存在'}, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
