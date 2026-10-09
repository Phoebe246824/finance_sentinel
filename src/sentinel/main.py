"""
Sentinel 舆情分析系统 — Pipeline 主入口
=========================================
用户输入 / 外部 payload → 黑名单过滤 → 分类 → 图谱 → 搜索 → Dashboard。

调用方式:
  uv run python -m sentinel.main
"""

import argparse
import asyncio
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from crewai.flow.flow import Flow, listen, router, start

from sentinel.blacklist.stores.factory import create_store_bundle
from sentinel.config import (
    SentinelSettings,
    get_profile_config,
    get_settings,
    render_prompt,
)
from sentinel.graph import (
    add_event_to_graph,
    close_graph_client,
    filter_search_result_by_subject_episodes,
    get_subject_episode_uuids,
    graph_episode_content_count,
    hybrid_search,
    init_graph_client,
)
from sentinel.models import (
    EventSource,
    NormalizedEvent,
)
from sentinel.pipeline.batch import batch_graph_event_with_related_stash
from sentinel.pipeline.blacklist_gate import (
    BlacklistGateResult,
    build_blacklist_store_config,
    evaluate_blacklist_gate,
    record_blacklist_matches,
)
from sentinel.pipeline.classification import execute_classification
from sentinel.pipeline.dashboard import execute_dashboard
from sentinel.pipeline.llm_json import generate_pipeline_json
from sentinel.pipeline.risk import evaluate_risk, second_evaluate_risk
from sentinel.utils.logging import (
    get_logger,
    print_banner,
    print_error,
    print_info,
    print_warn,
    setup_file_logging,
)
from sentinel.utils.text import (
    extract_person_id_numbers,
    extract_subject_id_numbers,
    sanitize_text_input,
)
from sentinel.web.repository import EventResultRepository
from sentinel.web.serialization import pipeline_result_to_event_payload

# (Ingestion 由外部消息源或用户输入触发，不再使用模拟接入)
LOG_MESSAGE_PREVIEW_CHARS = 500


@dataclass(frozen=True, slots=True)
class PipelineStageUpdate:
    stage_key: str
    stage_label: str
    stage_index: int
    stage_total: int
    detail: str = ""
    event_id: str | None = None
    status: str = "running"
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class PipelineRunResult:
    event_id: str
    normalized_event: NormalizedEvent
    status: str
    entered_flow: bool
    gate_result: BlacklistGateResult | None = None
    trend_report: Any | None = None
    graph_result: dict[str, Any] | None = None
    first_risk_context: dict[str, Any] | None = None
    second_risk_context: dict[str, Any] | None = None
    batch_summary: dict[str, Any] | None = None
    message: str = ""


class PipelineObserver(Protocol):
    async def on_stage(self, update: PipelineStageUpdate) -> None: ...


async def emit_stage(
    observer: PipelineObserver | None,
    update: PipelineStageUpdate,
) -> None:
    if observer is not None:
        await observer.on_stage(update)


# ============================================================
#  Stage 3: Graph — Graphiti 知识图谱构图
# ============================================================


async def get_graphiti_client(app_settings: SentinelSettings):
    """获取 Graphiti 客户端"""
    return await init_graph_client(app_settings)


async def execute_single_graph_build(
    app_settings: SentinelSettings,
    event: NormalizedEvent,
) -> list:
    """
    知识图谱构建：Graphiti Episode 写入 + 实体/关系提取

    Args:
        app_settings: 全局配置
        event: 标准化事件

    Returns:
        list[dict]: GraphBuildResult 列表
    """
    logger = get_logger("main.graph")
    graphiti = await get_graphiti_client(app_settings)
    dry_run = app_settings.graphiti_dry_run

    if dry_run:
        print_info("DRY RUN: 跳过图谱写入（提取结果仍会显示）")
        logger.info("DRY RUN mode enabled, skipping Neo4j writes")

    logger.info(
        "Graphiti client initialized: neo4j=%s, llm=%s, embedder=%s",
        app_settings.neo4j_uri,
        app_settings.llm_model,
        app_settings.embedder_model,
    )
    print_info("Graphiti 客户端初始化完成")

    build_results = []

    group_id = app_settings.graphiti_episode_source
    logger.info("writing event_id=%s, group_id=%s", event.event_id, group_id)

    timestamp = event.timestamp

    try:
        existing_content_count = await graph_episode_content_count(
            graphiti, event.raw_content, group_id
        )
        if existing_content_count > 0 and not dry_run:
            print_info("Neo4j 已存在该文本 Episode，跳过单条构图")
            logger.info(
                "skip graph write for existing episode: event_id=%s, group_id=%s, content_count=%d",
                event.event_id,
                group_id,
                existing_content_count,
            )
            build_results.append(
                {
                    "event_id": event.event_id,
                    "success": True,
                    "skipped": True,
                    "skip_reason": "existing_episode_content",
                    "existing_content_count": existing_content_count,
                    "entities_extracted": 0,
                    "relations_created": 0,
                }
            )
            return build_results

        result = await add_event_to_graph(
            graphiti=graphiti,
            event_text=event.raw_content,
            reference_time=timestamp,
            source_description=f"{event.source}:{event.event_type}",
            group_id=group_id,
            dry_run=dry_run,
            app_settings=app_settings,
        )

        entities = result.get("entities_extracted", 0)
        relations = result.get("relations_created", 0)
        if dry_run:
            print_info(
                f"提取完成（dry run，未写入数据库）: {entities} 个实体, {relations} 条关系"
            )
            logger.info(
                "DRY RUN: extraction complete, skipped Neo4j write: entities=%d, relations=%d",
                entities,
                relations,
            )
        else:
            print_info(f"写入成功: {entities} 个实体, {relations} 条关系")
            logger.info(
                "graph write success: entities=%d, relations=%d", entities, relations
            )

        build_results.append(
            {
                "event_id": event.event_id,
                "success": True,
                "entities_extracted": entities,
                "relations_created": relations,
            }
        )

    except Exception as e:
        print_error("图谱写入失败")
        logger.error("graph write failed: %s", e, exc_info=True)
        build_results.append(
            {
                "event_id": event.event_id,
                "success": False,
                "error": str(e),
            }
        )
    finally:
        total_nodes = sum(r.get("entities_extracted", 0) for r in build_results)
        total_edges = sum(r.get("relations_created", 0) for r in build_results)
        logger.info(
            "graph build done: %d episodes, %d nodes, %d edges",
            len(build_results),
            total_nodes,
            total_edges,
        )

        await close_graph_client(graphiti)

    return build_results


# ============================================================
#  Stage 4: Search — 混合搜索演示
# ============================================================


async def execute_search(
    app_settings: SentinelSettings,
    event: NormalizedEvent,
    num_results: int | None = None,
    group_id: str = "sentinel",
) -> dict:
    logger = get_logger("main.search")

    if num_results is None:
        num_results = app_settings.search_num_results

    result = {}
    graphiti = None
    subject_id_numbers = extract_subject_id_numbers(event.raw_content)
    try:
        print_info("正在初始化 Graphiti 搜索客户端...")
        graphiti = await init_graph_client(app_settings)
        print_info("Graphiti 搜索客户端初始化完成")

        logger.info(
            "hybrid_search: query=%s, group_id=%s, num_results=%d",
            event.raw_content,
            group_id,
            num_results,
        )
        if subject_id_numbers:
            logger.info("subject_id_numbers=%s", subject_id_numbers)

        subject_episode_uuids: set[str] = set()
        if subject_id_numbers:
            subject_episode_uuids = await get_subject_episode_uuids(
                graphiti, subject_id_numbers, group_id
            )
            logger.info("subject_episode_count=%d", len(subject_episode_uuids))

        min_score = app_settings.search_min_score
        logger.info("min_score=%.2f", min_score)

        result = await asyncio.wait_for(
            hybrid_search(
                graphiti=graphiti,
                query=event.raw_content,
                group_id=group_id,
                num_results=num_results,
                min_score=min_score,
            ),
            timeout=20,
        )
        before_scope_count = len(result.get("results", [])) if result else 0
        result = filter_search_result_by_subject_episodes(
            result, subject_episode_uuids, subject_id_numbers
        )
        after_scope_count = len(result.get("results", [])) if result else 0

        print_info("搜索成功")
        if subject_id_numbers:
            logger.info(
                "subject episode filter: %d -> %d",
                before_scope_count,
                after_scope_count,
            )

        reranked_items = result.get("results", []) if result else []

        reranked_nodes = [item for item in reranked_items if item.get("type") == "node"]
        reranked_edges = [item for item in reranked_items if item.get("type") == "edge"]
        reranked_episodes = [
            item for item in reranked_items if item.get("type") == "episode"
        ]

        logger.info(
            "global_rerank_topk: total=%d, nodes=%d, edges=%d, episodes=%d",
            len(reranked_items),
            len(reranked_nodes),
            len(reranked_edges),
            len(reranked_episodes),
        )

        if result is None:
            result = {}
        result["reranked_nodes"] = reranked_nodes
        result["reranked_edges"] = reranked_edges
        result["reranked_episodes"] = reranked_episodes

    except asyncio.TimeoutError:
        print_warn("搜索超时，跳过检索")
        logger.warning("hybrid_search timed out after 20s")
        result = result or {}
        result.setdefault("reranked_nodes", [])
        result.setdefault("reranked_edges", [])
        result.setdefault("reranked_episodes", [])
    except Exception as e:
        print_error("搜索失败，跳过检索")
        logger.error("search failed: %s: %s", type(e).__name__, e)
        logger.error("stack:\n%s", traceback.format_exc())
        result = result or {}
        result.setdefault("reranked_nodes", [])
        result.setdefault("reranked_edges", [])
        result.setdefault("reranked_episodes", [])

    finally:
        if graphiti is not None:
            await close_graph_client(graphiti)
            logger.info("Graphiti client closed")

    logger.info("search complete")
    return result


# ============================================================
#  将 payload 转换为 NormalizedEvent
# ============================================================


def normalization_output_schema() -> str:
    return (
        "Return strict JSON with these fields: source, raw_content, title, "
        "timestamp, structured_data, trace_id, content_type, event_type. "
        "source must be one of news, chat, transaction, behavior, or string; "
        "timestamp must use ISO format."
    )


async def normalize_payload_to_event(
    payload: dict | NormalizedEvent,
    app_settings: SentinelSettings,
) -> NormalizedEvent:
    logger = get_logger("main.normalizer")

    if isinstance(payload, NormalizedEvent):
        return payload

    raw_content = payload.get("data", json.dumps(payload))
    profile = get_profile_config()
    prompt = render_prompt(
        profile.prompts.pipeline.normalization,
        raw_content=raw_content,
        current_datetime=datetime.now().isoformat(timespec="seconds"),
        output_schema=normalization_output_schema(),
    )

    try:
        result_dict = await generate_pipeline_json(
            app_settings,
            prompt=prompt,
            temperature=0.3,
        )
        source = result_dict.get("source", "news")
        if isinstance(source, str):
            source = EventSource(source)
        # TODO: 日志记录标准化结果
        return NormalizedEvent(
            event_id=str(uuid.uuid4()),
            source=source,
            raw_content=raw_content,
            title=result_dict.get("title") or "",
            structured_data=result_dict.get("structured_data") or {},
            timestamp=result_dict.get("timestamp") or datetime.now(),
            ingestion_time=result_dict.get("ingestion_time") or datetime.now(),
            trace_id=result_dict.get("trace_id") or "",
            content_type=result_dict.get("content_type") or "text",
            event_type=result_dict.get("event_type") or "",
        )
    except Exception as e:
        print_error("事件标准化失败")
        logger.error("normalize_event failed: %s", e, exc_info=True)
        return NormalizedEvent(
            event_id=str(uuid.uuid4()),
            source=EventSource.NEWS,
            raw_content=raw_content,
            title="",
            structured_data={},
            timestamp=datetime.now(),
            ingestion_time=datetime.now(),
            trace_id="",
            content_type="text",
            event_type="",
        )


# ============================================================
#  CrewAI Flow 封装
# ============================================================


class SentinelPipelineFlow(Flow):
    """
    Sentinel 舆情分析系统 Pipeline Flow
    """

    def __init__(
        self,
        app_settings: SentinelSettings,
        normalized_event=None,
        store_bundle=None,
        stash_store=None,
        id_numbers=None,
        observer: PipelineObserver | None = None,
    ):
        super().__init__()
        self.settings = app_settings
        self.normalized_event = normalized_event
        self._store_bundle = store_bundle
        self._stash_store = stash_store
        self._id_numbers = id_numbers or []
        self._observer = observer
        self._log = get_logger("main.flow")

    async def _emit(
        self,
        stage_key: str,
        stage_label: str,
        stage_index: int,
        detail: str = "",
        status: str = "running",
    ) -> None:
        event_id = self.normalized_event.event_id if self.normalized_event else None
        await emit_stage(
            self._observer,
            PipelineStageUpdate(
                stage_key=stage_key,
                stage_label=stage_label,
                stage_index=stage_index,
                stage_total=8,
                detail=detail,
                event_id=event_id,
                status=status,
            ),
        )

    @start()
    async def classification(self):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 2: Classification — 事件分类")
        self._log.info("=" * 60)
        self._log.info(
            "input: event_id=%s, source=%s, content=%.80s",
            event.event_id if event else None,
            event.source.value if event else None,
            event.raw_content if event else "",
        )
        self.normalized_event = (
            await execute_classification(self.settings, event) if event else None
        )
        if self.normalized_event:
            self._log.info(
                "output: event_type=%s, entities=%s",
                self.normalized_event.event_type,
                list(self.normalized_event.structured_data.keys()),
            )
        await self._emit("classification", "事件分类", 3, "分类完成")

    @listen(classification)
    async def single_graph_build(self):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 3: Graph — 单条构图")
        self._log.info("=" * 60)
        self._log.info(
            "input: event_id=%s, event_type=%s",
            event.event_id if event else None,
            event.event_type if event else None,
        )
        if event is None:
            self.state["graph_result"] = None
            self._log.info("output: success=%s, entities=%d, relations=%d", None, 0, 0)
            return None
        results = await execute_single_graph_build(self.settings, event)
        result = results[0] if results else None
        self.state["graph_result"] = result
        self._log.info(
            "output: success=%s, entities=%d, relations=%d",
            result.get("success") if result else None,
            result.get("entities_extracted", 0) if result else 0,
            result.get("relations_created", 0) if result else 0,
        )
        if (
            result
            and result.get("success")
            and self._stash_store is not None
            and event is not None
            and not self.settings.graphiti_dry_run
        ):
            await self._stash_store.mark_events_graph_built([event.event_id])
            self._log.info("marked current event as graph built: %s", event.event_id)
        await self._emit("single_graph", "单条构图", 4, "构图完成")
        return result

    @listen(single_graph_build)
    async def search_first_risk_context(self, result):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 4: Search — 首次风险上下文检索")
        self._log.info("=" * 60)
        if event is None:
            self.state["first_risk_context"] = {}
            return {}
        risk_num_results = self.settings.risk_search_num_results
        context = await execute_search(
            self.settings, event, num_results=risk_num_results
        )
        self.state["first_risk_context"] = context
        await self._emit("first_search", "首次检索", 5, "首次风险上下文检索完成")
        return context

    @listen(search_first_risk_context)
    async def first_risk_evaluation(self, result):
        classified_event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 5: Risk — 首次风险评估")
        self._log.info("=" * 60)
        self._log.info(
            "input: event_id=%s, risk_level=%s, risk_score=%s",
            classified_event.event_id if classified_event else None,
            classified_event.risk_level if classified_event else None,
            classified_event.risk_score if classified_event else None,
        )
        if classified_event:
            risk_result = await evaluate_risk(
                self.settings, classified_event, self.state.get("first_risk_context")
            )
            self.normalized_event.risk_level = risk_result["risk_level"]
            self.normalized_event.risk_score = risk_result["risk_score"]
            self.normalized_event.reasoning = risk_result["reasoning"]
            self.normalized_event.dimension_scores = risk_result.get(
                "dimension_scores", {}
            )
            self._log.info(
                "first risk evaluation: level=%s, score=%.2f",
                risk_result["risk_level"],
                risk_result["risk_score"],
            )
        self._log.info(
            "output: risk_level=%s, risk_score=%s",
            self.normalized_event.risk_level if self.normalized_event else None,
            self.normalized_event.risk_score if self.normalized_event else None,
        )
        await self._emit("first_risk", "首次风险评估", 6, "首次风险评估完成")
        return result

    @router(first_risk_evaluation)
    def route_post_first_risk(self, result):
        event = self.normalized_event
        if event is None:
            self._log.info("route_post_first_risk=complete, event is None")
            return "complete"
        risk_threshold = self.settings.risk_threshold
        if event.risk_score > risk_threshold:
            self._log.info(
                "route_post_first_risk=batch_graph, score=%.2f > %.2f",
                event.risk_score,
                risk_threshold,
            )
            return "batch_graph"
        self._log.info(
            "route_post_first_risk=complete, score=%.2f <= %.2f",
            event.risk_score,
            risk_threshold,
        )
        return "complete"

    @listen("batch_graph")
    async def batch_graph_build_from_stash(self, result):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 6: Graph — 批量补图")
        self._log.info("=" * 60)
        if event is None:
            self.state["graph_result"] = None
            return None
        batch_summary = await batch_graph_event_with_related_stash(
            self.settings,
            self._stash_store,
            self._id_numbers,
            event,
        )
        self.state["graph_result"] = batch_summary
        await self._emit("batch_graph", "批量补图", 7, "高风险事件触发批量补图")
        return batch_summary

    @listen(batch_graph_build_from_stash)
    async def search_second_risk_context(self, result):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 7: Search — 二次风险上下文检索")
        self._log.info("=" * 60)
        if event is None:
            self.state["second_risk_context"] = {}
            return {}

        batch_summary = result if isinstance(result, dict) else {}
        fetched_count = int(batch_summary.get("fetched_count") or 0)
        eligible_count = int(batch_summary.get("eligible_count") or 0)
        batched_count = int(batch_summary.get("batched_count") or 0)
        if batched_count == 0:
            self.state["skip_second_risk"] = True
            self.state["second_risk_context"] = None
            self._log.info(
                "skip second search/evaluation: fetched_count=%d, eligible_count=%d, batched_count=0",
                fetched_count,
                eligible_count,
            )
            if fetched_count == 0:
                print_info("Milvus 事件库回捞为空，跳过二次检索和二次风险评估")
            elif eligible_count == 0:
                print_info("Milvus 回捞候选均未通过过滤，跳过二次检索和二次风险评估")
            else:
                print_info(
                    "Milvus 回捞后无新增候选需要批量构图，跳过二次检索和二次风险评估"
                )
            return self.state.get("first_risk_context", {})

        self.state["skip_second_risk"] = False
        risk_num_results = self.settings.risk_search_num_results
        context = await execute_search(
            self.settings, event, num_results=risk_num_results
        )
        self.state["second_risk_context"] = context
        return context

    @listen(search_second_risk_context)
    async def second_risk_evaluation_stage(self, result):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 7b: Risk — 二次风险评估")
        self._log.info("=" * 60)
        if event is None:
            return result
        if self.state.get("skip_second_risk"):
            self._log.info("skip second risk evaluation, keep first risk result")
            return self.state.get("first_risk_context", {})
        context = self.state.get("second_risk_context", {})
        risk_result = await second_evaluate_risk(self.settings, event, context)
        self.normalized_event.risk_level = risk_result["risk_level"]
        self.normalized_event.risk_score = risk_result["risk_score"]
        self.normalized_event.reasoning = risk_result["reasoning"]
        self.normalized_event.dimension_scores = risk_result.get("dimension_scores", {})
        self.state["second_risk_applied"] = True
        self._log.info(
            "second evaluation output: level=%s, score=%.2f",
            risk_result["risk_level"],
            risk_result["risk_score"],
        )
        await self._emit("second_risk", "二次风险评估", 7, "二次风险评估完成")
        return context

    @router(second_risk_evaluation_stage)
    def route_post_second_risk(self, result):
        event = self.normalized_event
        if event is None:
            self._log.info("route_post_second_risk=complete, event is None")
            return "complete"
        risk_threshold = self.settings.risk_threshold
        if event.risk_score > risk_threshold:
            self._log.info(
                "route_post_second_risk=dashboard, score=%.2f > %.2f",
                event.risk_score,
                risk_threshold,
            )
            return "go_dashboard"
        self._log.info(
            "route_post_second_risk=complete, score=%.2f <= %.2f",
            event.risk_score,
            risk_threshold,
        )
        return "complete"

    @listen("go_dashboard")
    async def dashboard(self, result):
        event = self.normalized_event
        self._log.info("=" * 60)
        self._log.info("Stage 8: Dashboard — 意图分析与趋势预测")
        self._log.info("=" * 60)
        if event is None:
            self._log.info("output: complete")
            return "complete"
        context = self.state.get("second_risk_context") or self.state.get(
            "first_risk_context"
        )
        if context is None:
            context = {}
        self._log.info(
            "input: context_results_count=%d",
            len(context.get("results", [])) if context else 0,
        )
        report = await execute_dashboard(self.settings, event, context)
        self.state["trend_report"] = report
        await self._emit("dashboard", "趋势预测", 8, "意图分析与趋势预测完成")
        self._log.info("output: complete")
        return "complete"

    @listen("complete")
    def end(self):
        self._log.info("pipeline finished")
        print_info("Pipeline 消息处理完成")


def _message_preview(message: str) -> str:
    if len(message) <= LOG_MESSAGE_PREVIEW_CHARS:
        return message
    omitted = len(message) - LOG_MESSAGE_PREVIEW_CHARS
    return f"{message[:LOG_MESSAGE_PREVIEW_CHARS]}... [truncated {omitted} chars]"


async def process_message(
    message: str,
    app_settings: SentinelSettings | None = None,
    *,
    observer: PipelineObserver | None = None,
    return_result: bool = False,
) -> str | PipelineRunResult:
    """Process one user message through the same path used by the CLI loop."""
    if app_settings is None:
        app_settings = get_settings()
    get_profile_config()

    logger = get_logger("main.flow")
    logger.info("user input preview: %s", _message_preview(message))

    payload = {"data": message}
    normalized_event = await normalize_payload_to_event(payload, app_settings)
    logger.info(
        "normalized event: event_id=%s, source=%s",
        normalized_event.event_id,
        normalized_event.source,
    )
    await emit_stage(
        observer,
        PipelineStageUpdate(
            stage_key="normalize",
            stage_label="事件标准化",
            stage_index=1,
            stage_total=8,
            detail="输入已标准化",
            event_id=normalized_event.event_id,
        ),
    )
    person_ids = extract_person_id_numbers(normalized_event.raw_content)

    store_bundle = None
    try:
        config = build_blacklist_store_config(app_settings)
        store_bundle = create_store_bundle(config)
        event_store = store_bundle.events
        await event_store.stash_event(
            normalized_event.event_id,
            normalized_event.raw_content,
            person_ids,
            normalized_event.timestamp,
        )
        await emit_stage(
            observer,
            PipelineStageUpdate(
                stage_key="event_store",
                stage_label="事件入库",
                stage_index=2,
                stage_total=8,
                detail="事件已写入 Milvus 事件库",
                event_id=normalized_event.event_id,
            ),
        )
        gate_result = await evaluate_blacklist_gate(
            app_settings,
            normalized_event,
            store_bundle,
        )
        await emit_stage(
            observer,
            PipelineStageUpdate(
                stage_key="blacklist_gate",
                stage_label="黑名单判定",
                stage_index=2,
                stage_total=8,
                detail="PASS" if gate_result.should_proceed else "未命中，停止后续分析",
                event_id=normalized_event.event_id,
            ),
        )

        if not gate_result.should_proceed:
            result = PipelineRunResult(
                event_id=normalized_event.event_id,
                normalized_event=normalized_event,
                status="stashed",
                entered_flow=False,
                gate_result=gate_result,
                message="事件未命中黑名单，已写入 Milvus 事件库",
            )
            payload = pipeline_result_to_event_payload(result)
            await event_store.update_analysis_result(
                normalized_event.event_id,
                {
                    "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                    **EventResultRepository.payload_to_store_fields(
                        payload,
                        status="stashed",
                    ),
                },
            )
            await emit_stage(
                observer,
                PipelineStageUpdate(
                    stage_key="complete",
                    stage_label="入库完成",
                    stage_index=8,
                    stage_total=8,
                    detail=result.message,
                    event_id=normalized_event.event_id,
                    status="success",
                ),
            )
            print_info(f"EVENT_ID: {normalized_event.event_id}")
            print_info(result.message)
            return result if return_result else normalized_event.event_id

        await record_blacklist_matches(normalized_event, gate_result, store_bundle)

        print_info("消息处理开始")
        flow = SentinelPipelineFlow(
            app_settings,
            normalized_event,
            store_bundle,
            event_store,
            gate_result.id_numbers,
            observer=observer,
        )
        await flow.kickoff_async()
        normalized_result_event = flow.normalized_event or normalized_event
        graph_result = flow.state.get("graph_result")
        result = PipelineRunResult(
            event_id=normalized_event.event_id,
            normalized_event=normalized_result_event,
            status="analyzed",
            entered_flow=True,
            gate_result=gate_result,
            trend_report=flow.state.get("trend_report"),
            graph_result=graph_result if isinstance(graph_result, dict) else None,
            first_risk_context=flow.state.get("first_risk_context"),
            second_risk_context=flow.state.get("second_risk_context"),
            batch_summary=(
                graph_result
                if isinstance(graph_result, dict) and "batch_results" in graph_result
                else None
            ),
            message="消息处理完成",
        )
        payload = pipeline_result_to_event_payload(result)
        await event_store.update_analysis_result(
            normalized_event.event_id,
            {
                "analysis_status": "analyzed",
                "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                **EventResultRepository.payload_to_store_fields(
                    payload,
                    status="analyzed",
                ),
            },
        )
        await emit_stage(
            observer,
            PipelineStageUpdate(
                stage_key="complete",
                stage_label="分析完成",
                stage_index=8,
                stage_total=8,
                detail=result.message,
                event_id=normalized_event.event_id,
                status="success",
            ),
        )
        print_info(f"EVENT_ID: {normalized_event.event_id}")
        print_info("消息处理完成")
        return result if return_result else normalized_event.event_id

    finally:
        if store_bundle is not None:
            await store_bundle.aclose()


async def run_flow(app_settings: SentinelSettings):
    """
    使用 CrewAI Flow 运行完整 Pipeline
    从终端输入消息进行处理
    """
    print(f"\n{'=' * 70}")
    print("  Sentinel Pipeline Flow — CrewAI Flow 驱动")
    print("  输入消息进行分析 (输入 'quit' 或 'exit' 退出)")
    print(f"{'=' * 70}")

    while True:
        try:
            print("\n请输入消息内容:")
            user_input = (await asyncio.to_thread(input, "> ")).strip()
            user_input = sanitize_text_input(user_input)

            if not user_input:
                print("消息不能为空，请重新输入")
                continue

            if user_input.lower() in ["quit", "exit", "q"]:
                print("退出程序")
                break

            await process_message(user_input, app_settings)

        except KeyboardInterrupt:
            print("\n退出程序")
            break
        except Exception as e:
            print_error("处理消息异常")
            logger = get_logger("main.flow")
            logger.error("flow exception: %s", e, exc_info=True)


# ============================================================
#  服务生命周期管理
# ============================================================


async def start_service(app_settings: SentinelSettings) -> None:
    logger = get_logger("main")
    logger.info(
        "starting full pipeline: Ingestion → Classification → Graph → Search → Dashboard"
    )
    await run_flow(app_settings)


async def shutdown_all() -> None:
    logger = get_logger("main")
    print_banner("Shutdown — 优雅关闭")
    logger.info("shutdown: stopping all services")
    await asyncio.sleep(0.1)
    elapsed = time.time() - start_time
    print_info(f"已优雅关闭，总运行时间: {elapsed:.1f}s")
    logger.info("shutdown complete, elapsed: %.1fs", elapsed)


# ============================================================
#  入口
# ============================================================

start_time = 0.0


async def _drain_pending_asyncio_tasks() -> None:
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def main() -> None:
    global start_time
    parser = argparse.ArgumentParser(
        description="Sentinel 舆情分析系统 — Pipeline 主入口"
    )
    parser.add_argument(
        "--log-dir", default=None, help="日志目录，默认写入当前项目 logs/ 目录"
    )
    args = parser.parse_args()

    log_path = setup_file_logging(args.log_dir)
    try:
        start_time = time.time()

        print("╔════════════════════════════════════════════════════════════════════╗")
        print("║           SENTINEL 舆情分析系统 — Pipeline Flow                    ║")
        print("║                                                                    ║")
        print("║   Normalize → Blacklist → Classification → Graph → Risk → Search   ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        print(f"日志文件: {log_path}")

        app_settings = get_settings()
        get_profile_config()
        get_logger("main.config").info(
            "settings loaded: neo4j=%s, database=%s, llm=%s, embedder=%s",
            app_settings.neo4j_uri,
            app_settings.neo4j_database,
            app_settings.llm_model,
            app_settings.embedder_model,
        )

        try:
            await start_service(app_settings)
        finally:
            await shutdown_all()
            await asyncio.sleep(0.05)
            await _drain_pending_asyncio_tasks()

        print("\nPipeline 处理完成")
        print(f"日志文件: {log_path}")
    finally:
        logging.shutdown()


def run_cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run_cli()
