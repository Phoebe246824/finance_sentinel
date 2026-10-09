"""Web analysis task lifecycle and SSE history management."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from sentinel.main import PipelineRunResult, PipelineStageUpdate
from sentinel.utils.logging import get_logger
from sentinel.web.repository import EventResultRepository
from sentinel.web.serialization import pipeline_result_to_event_payload

logger = get_logger(__name__)
PUBLIC_FAILURE_MESSAGE = "分析任务失败，请查看服务日志"


@dataclass(slots=True)
class AnalysisTaskPayload:
    task_id: str
    status: str
    event_id: str | None = None
    error_message: str | None = None
    stage_key: str | None = None
    stage_label: str | None = None
    stage_index: int | None = None
    stage_total: int | None = None
    stage_detail: str | None = None
    stage_updated_at: str | None = None

    def to_dict(self) -> dict[str, object | None]:
        return {
            "task_id": self.task_id,
            "event_id": self.event_id,
            "status": self.status,
            "error_message": self.error_message,
            "stage_key": self.stage_key,
            "stage_label": self.stage_label,
            "stage_index": self.stage_index,
            "stage_total": self.stage_total,
            "stage_detail": self.stage_detail,
            "stage_updated_at": self.stage_updated_at,
        }


@dataclass(slots=True)
class _TaskState:
    payload: AnalysisTaskPayload
    history: list[AnalysisTaskPayload] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None
    updated_at: datetime = field(default_factory=datetime.now)


class QueueObserver:
    def __init__(self, manager: AnalysisTaskManager, task_id: str) -> None:
        self._manager = manager
        self._task_id = task_id

    async def on_stage(self, update: PipelineStageUpdate) -> None:
        await self._manager.publish_stage(self._task_id, update)


Runner = Callable[[str, QueueObserver, object], Awaitable[PipelineRunResult]]


class AnalysisTaskManager:
    def __init__(
        self,
        *,
        runner: Runner,
        repository: EventResultRepository,
        max_running_tasks: int = 1,
        terminal_ttl: timedelta = timedelta(minutes=30),
        run_timeout: timedelta = timedelta(minutes=10),
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._max_running_tasks = max_running_tasks
        self._terminal_ttl = terminal_ttl
        self._run_timeout = run_timeout
        self._tasks: dict[str, _TaskState] = {}
        self._started_at = datetime.now()
        self._completed_task_count = 0
        self._completed_latency_total_ms = 0
        self._completed_timestamps: deque[datetime] = deque()
        self._accepting_tasks = True

    def create_task(self, text: str, settings) -> AnalysisTaskPayload:
        if not self._accepting_tasks:
            raise RuntimeError("分析服务正在关闭，请稍后重试")
        self.prune_terminal_tasks(now=datetime.now())
        active_count = sum(
            1
            for state in self._tasks.values()
            if state.payload.status not in {"success", "failed", "cancelled"}
        )
        if active_count >= self._max_running_tasks:
            raise RuntimeError("已有真实分析任务正在运行，请稍后再试")
        task_id = f"task-{uuid4().hex[:12]}"
        payload = AnalysisTaskPayload(
            task_id=task_id,
            status="queued",
            stage_key="queued",
            stage_label="排队中",
            stage_index=0,
            stage_total=8,
            stage_detail="任务已创建",
            stage_updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        state = _TaskState(payload=payload, history=[payload])
        self._tasks[task_id] = state
        state.task = asyncio.create_task(self._run(task_id, text, settings))
        return payload

    def get_task(self, task_id: str) -> AnalysisTaskPayload | None:
        state = self._tasks.get(task_id)
        return state.payload if state else None

    async def publish_stage(
        self,
        task_id: str,
        update: PipelineStageUpdate,
    ) -> None:
        state = self._tasks[task_id]
        status = update.status
        if status == "success":
            status = "running"
        state.payload = AnalysisTaskPayload(
            task_id=task_id,
            status=status,
            event_id=update.event_id,
            stage_key=update.stage_key,
            stage_label=update.stage_label,
            stage_index=update.stage_index,
            stage_total=update.stage_total,
            stage_detail=update.detail,
            stage_updated_at=update.updated_at.isoformat(timespec="seconds"),
        )
        state.updated_at = datetime.now()
        await self._record_history(state, state.payload)

    async def stream_updates(self, task_id: str) -> AsyncIterator[AnalysisTaskPayload]:
        state = self._tasks.get(task_id)
        if state is None:
            raise KeyError(task_id)
        position = 0
        while True:
            async with state.condition:
                while position >= len(state.history):
                    await state.condition.wait()
                update = state.history[position]
            position += 1
            yield update
            if update.status in {"success", "failed", "cancelled"}:
                return

    def prune_terminal_tasks(self, *, now: datetime) -> None:
        expired = [
            task_id
            for task_id, state in self._tasks.items()
            if state.payload.status in {"success", "failed", "cancelled"}
            and now - state.updated_at > self._terminal_ttl
        ]
        for task_id in expired:
            del self._tasks[task_id]

    def has_active_tasks(self) -> bool:
        return any(
            state.payload.status not in {"success", "failed", "cancelled"}
            for state in self._tasks.values()
        )

    def metrics_snapshot(
        self, *, now: datetime | None = None
    ) -> dict[str, int | float | None]:
        current = now or datetime.now()
        self._prune_completed_timestamps(now=current)
        avg_latency = None
        if self._completed_task_count:
            avg_latency = int(
                self._completed_latency_total_ms / self._completed_task_count
            )
        uptime_hours = max(0.0, (current - self._started_at).total_seconds() / 3600)
        return {
            "completed_tasks": self._completed_task_count,
            "avg_processing_latency_ms": avg_latency,
            "events_per_minute": float(len(self._completed_timestamps)),
            "uptime_hours": round(uptime_hours, 2),
        }

    async def shutdown(self) -> None:
        self._accepting_tasks = False
        active_states = [
            state
            for state in self._tasks.values()
            if state.task is not None
            and not state.task.done()
            and state.payload.status not in {"success", "failed", "cancelled"}
        ]
        for state in active_states:
            state.task.cancel()
        if active_states:
            await asyncio.gather(
                *(state.task for state in active_states if state.task is not None),
                return_exceptions=True,
            )
        for state in active_states:
            if state.payload.status in {"success", "failed", "cancelled"}:
                continue
            cancelled = AnalysisTaskPayload(
                task_id=state.payload.task_id,
                status="cancelled",
                event_id=state.payload.event_id,
                error_message="分析服务正在关闭，任务已取消",
                stage_key="cancelled",
                stage_label="任务已取消",
                stage_index=state.payload.stage_index,
                stage_total=state.payload.stage_total,
                stage_detail="分析服务正在关闭，任务已取消",
                stage_updated_at=datetime.now().isoformat(timespec="seconds"),
            )
            state.payload = cancelled
            state.updated_at = datetime.now()
            await self._record_history(state, cancelled)

    async def _run(self, task_id: str, text: str, settings) -> None:
        started_at = datetime.now()
        state = self._tasks[task_id]
        state.payload = AnalysisTaskPayload(
            task_id=task_id,
            status="running",
            event_id=state.payload.event_id,
            error_message=state.payload.error_message,
            stage_key=state.payload.stage_key,
            stage_label=state.payload.stage_label,
            stage_index=state.payload.stage_index,
            stage_total=state.payload.stage_total,
            stage_detail=state.payload.stage_detail,
            stage_updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        state.updated_at = datetime.now()
        await self._record_history(state, state.payload)
        try:
            result = await asyncio.wait_for(
                self._runner(text, QueueObserver(self, task_id), settings),
                timeout=self._run_timeout.total_seconds(),
            )
            payload = pipeline_result_to_event_payload(result)
            await self._repository.save_result(
                payload,
                status=result.status,
                settings=settings,
            )
            finished_at = datetime.now()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            self._record_completed_metrics(duration_ms, finished_at)
            terminal = AnalysisTaskPayload(
                task_id=task_id,
                status="success",
                event_id=result.event_id,
                stage_key="complete",
                stage_label="分析完成",
                stage_index=8,
                stage_total=8,
                stage_detail=result.message,
                stage_updated_at=datetime.now().isoformat(timespec="seconds"),
            )
        except asyncio.TimeoutError:
            terminal = AnalysisTaskPayload(
                task_id=task_id,
                status="failed",
                error_message="分析任务超时，请稍后重试",
                stage_key="failed",
                stage_label="分析失败",
                stage_index=8,
                stage_total=8,
                stage_detail="分析任务超时，请稍后重试",
                stage_updated_at=datetime.now().isoformat(timespec="seconds"),
            )
        except Exception as exc:
            logger.error(
                "analysis task failed: %s",
                type(exc).__name__,
                exc_info=False,
            )
            terminal = AnalysisTaskPayload(
                task_id=task_id,
                status="failed",
                error_message=PUBLIC_FAILURE_MESSAGE,
                stage_key="failed",
                stage_label="分析失败",
                stage_index=8,
                stage_total=8,
                stage_detail=PUBLIC_FAILURE_MESSAGE,
                stage_updated_at=datetime.now().isoformat(timespec="seconds"),
            )
        state.payload = terminal
        state.updated_at = datetime.now()
        await self._record_history(state, terminal)

    def _record_completed_metrics(
        self,
        duration_ms: int,
        finished_at: datetime,
    ) -> None:
        self._completed_task_count += 1
        self._completed_latency_total_ms += duration_ms
        self._completed_timestamps.append(finished_at)
        self._prune_completed_timestamps(now=finished_at)

    def _prune_completed_timestamps(self, *, now: datetime) -> None:
        minute_ago = now - timedelta(minutes=1)
        while self._completed_timestamps and self._completed_timestamps[0] < minute_ago:
            self._completed_timestamps.popleft()

    @staticmethod
    async def _record_history(
        state: _TaskState,
        payload: AnalysisTaskPayload,
    ) -> None:
        async with state.condition:
            state.history.append(payload)
            state.condition.notify_all()
