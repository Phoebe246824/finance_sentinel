"""Tests for web analysis task lifecycle and public error payloads."""

import asyncio
from datetime import datetime, timedelta

import pytest

from sentinel.config import SentinelSettings
from sentinel.main import PipelineRunResult, PipelineStageUpdate
from sentinel.models import EventSource, NormalizedEvent
from sentinel.web.analysis_tasks import AnalysisTaskManager


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str | None]] = []

    async def save_result(self, event, status: str, settings=None) -> None:
        self.saved.append(
            (event.event_id, status, getattr(settings, "llm_model", None))
        )


def make_settings(**overrides) -> SentinelSettings:
    values = {
        "neo4j_password": "neo4j-secret",
        "llm_api_key": "llm-secret",
        "llm_model": "gpt-4o",
    }
    values.update(overrides)
    return SentinelSettings(_env_file=None, **values)


def make_result() -> PipelineRunResult:
    event = NormalizedEvent(
        event_id="EVT-TASK",
        source=EventSource.NEWS,
        raw_content="task text",
        title="task",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )
    return PipelineRunResult(
        event_id="EVT-TASK",
        normalized_event=event,
        status="stashed",
        entered_flow=False,
        message="stored only",
    )


@pytest.mark.asyncio
async def test_task_manager_streams_success_and_saves_result():
    release = asyncio.Event()

    async def runner(text, observer, settings):
        del settings
        await observer.on_stage(
            PipelineStageUpdate(
                stage_key="normalize",
                stage_label="事件标准化",
                stage_index=1,
                stage_total=8,
                event_id="EVT-TASK",
            )
        )
        await observer.on_stage(
            PipelineStageUpdate(
                stage_key="complete",
                stage_label="分析完成",
                stage_index=8,
                stage_total=8,
                event_id="EVT-TASK",
                status="success",
            )
        )
        await release.wait()
        return make_result()

    repository = FakeRepository()
    manager = AnalysisTaskManager(runner=runner, repository=repository)

    initial = manager.create_task("task text", make_settings())
    updates = []
    stream = manager.stream_updates(initial.task_id)
    updates.append(await anext(stream))
    updates.append(await anext(stream))
    updates.append(await anext(stream))

    assert updates[-1].status == "running"
    assert manager.get_task(initial.task_id).status == "running"

    with pytest.raises(RuntimeError, match="已有真实分析任务正在运行"):
        manager.create_task("task text 2", make_settings())

    release.set()
    async for update in stream:
        updates.append(update)
        if update.status in {"success", "failed"}:
            break

    assert updates[-1].status == "success"
    assert updates[-1].event_id == "EVT-TASK"
    assert repository.saved == [("EVT-TASK", "stashed", "gpt-4o")]


@pytest.mark.asyncio
async def test_task_manager_reports_failure(caplog: pytest.LogCaptureFixture):
    async def runner(text, observer, settings):
        del text, observer, settings
        raise RuntimeError("pipeline exploded with rag-secret")

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())

    initial = manager.create_task("task text", make_settings())
    updates = []
    async for update in manager.stream_updates(initial.task_id):
        updates.append(update)
        if update.status in {"success", "failed"}:
            break

    assert updates[-1].status == "failed"
    assert updates[-1].error_message == "分析任务失败，请查看服务日志"
    assert updates[-1].stage_detail == "分析任务失败，请查看服务日志"
    assert "rag-secret" not in str(updates[-1].to_dict())
    assert "pipeline exploded" not in caplog.text
    assert "rag-secret" not in caplog.text


@pytest.mark.asyncio
async def test_task_manager_prunes_terminal_tasks_by_ttl():
    async def runner(text, observer, settings):
        del text, observer, settings
        return make_result()

    manager = AnalysisTaskManager(
        runner=runner,
        repository=FakeRepository(),
        terminal_ttl=timedelta(seconds=1),
    )
    task = manager.create_task("task text", make_settings())
    async for update in manager.stream_updates(task.task_id):
        if update.status in {"success", "failed"}:
            break
    manager._tasks[task.task_id].updated_at = datetime.now() - timedelta(seconds=5)

    manager.prune_terminal_tasks(now=datetime.now())

    assert manager.get_task(task.task_id) is None


@pytest.mark.asyncio
async def test_task_manager_rejects_second_active_task_before_runner_starts():
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(text, observer, settings):
        del text, observer, settings
        started.set()
        await release.wait()
        return make_result()

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())

    first = manager.create_task("task one", make_settings())

    with pytest.raises(RuntimeError, match="已有真实分析任务正在运行"):
        manager.create_task("task two", make_settings())

    await started.wait()
    release.set()
    async for update in manager.stream_updates(first.task_id):
        if update.status in {"success", "failed"}:
            break


@pytest.mark.asyncio
async def test_task_manager_replays_ordered_history_for_late_subscriber():
    async def runner(text, observer, settings):
        del text, settings
        await observer.on_stage(
            PipelineStageUpdate(
                stage_key="normalize",
                stage_label="事件标准化",
                stage_index=1,
                stage_total=8,
                event_id="EVT-TASK",
            )
        )
        return make_result()

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())
    task = manager.create_task("task text", make_settings())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    updates = []
    async for update in manager.stream_updates(task.task_id):
        updates.append((update.status, update.stage_key))
        if update.status in {"success", "failed"}:
            break

    assert updates == [
        ("queued", "queued"),
        ("running", "queued"),
        ("running", "normalize"),
        ("success", "complete"),
    ]


@pytest.mark.asyncio
async def test_task_manager_times_out_stalled_runner():
    async def runner(text, observer, settings):
        del text, observer, settings
        await asyncio.sleep(3600)
        return make_result()

    manager = AnalysisTaskManager(
        runner=runner,
        repository=FakeRepository(),
        run_timeout=timedelta(milliseconds=10),
    )

    task = manager.create_task("task text", make_settings())
    updates = []
    async for update in manager.stream_updates(task.task_id):
        updates.append(update)
        if update.status in {"success", "failed"}:
            break

    assert updates[-1].status == "failed"
    assert updates[-1].error_message == "分析任务超时，请稍后重试"


@pytest.mark.asyncio
async def test_new_task_uses_latest_runtime_settings_snapshot():
    settings_used = []
    release_first = asyncio.Event()
    allow_finish = asyncio.Event()

    class FakeRuntimeSettings:
        def __init__(self):
            self.current = "old-model"

        def get_active_settings(self):
            return make_settings(llm_model=self.current)

    runtime = FakeRuntimeSettings()

    async def runner(text, observer, settings):
        del text, observer
        settings_used.append(settings.llm_model)
        if settings.llm_model == "old-model":
            release_first.set()
            await allow_finish.wait()
        return make_result()

    manager = AnalysisTaskManager(
        runner=runner,
        repository=FakeRepository(),
    )

    first = manager.create_task("task one", runtime.get_active_settings())
    await release_first.wait()

    runtime.current = "new-model"
    allow_finish.set()
    async for update in manager.stream_updates(first.task_id):
        if update.status in {"success", "failed"}:
            break

    second = manager.create_task("task two", runtime.get_active_settings())
    async for update in manager.stream_updates(second.task_id):
        if update.status in {"success", "failed"}:
            break

    assert settings_used == ["old-model", "new-model"]


@pytest.mark.asyncio
async def test_task_manager_reports_runtime_metrics_from_completed_tasks():
    async def runner(text, observer, settings):
        del text, observer, settings
        return make_result()

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())
    task = manager.create_task("task text", make_settings())
    async for update in manager.stream_updates(task.task_id):
        if update.status in {"success", "failed"}:
            break

    metrics = manager.metrics_snapshot(now=datetime.now())

    assert metrics["completed_tasks"] == 1
    assert metrics["avg_processing_latency_ms"] >= 0
    assert metrics["events_per_minute"] >= 1.0
    assert metrics["uptime_hours"] >= 0.0


@pytest.mark.asyncio
async def test_task_manager_metrics_use_bounded_rolling_timestamp_window():
    async def runner(text, observer, settings):
        del text, observer, settings
        return make_result()

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())
    now = datetime(2026, 1, 1, 12, 0, 0)
    recent = now - timedelta(seconds=30)
    expired = now - timedelta(minutes=2)
    manager._completed_task_count = 2
    manager._completed_latency_total_ms = 3000
    manager._completed_timestamps.extend([expired, recent])

    metrics = manager.metrics_snapshot(now=now)

    assert metrics["completed_tasks"] == 2
    assert metrics["avg_processing_latency_ms"] == 1500
    assert metrics["events_per_minute"] == 1.0
    assert list(manager._completed_timestamps) == [recent]


@pytest.mark.asyncio
async def test_task_manager_excludes_failed_tasks_from_latency_average():
    async def runner(text, observer, settings):
        del text, observer, settings
        raise RuntimeError("boom")

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())
    task = manager.create_task("task text", make_settings())
    async for update in manager.stream_updates(task.task_id):
        if update.status in {"success", "failed"}:
            break

    metrics = manager.metrics_snapshot(now=datetime.now())

    assert metrics["completed_tasks"] == 0
    assert metrics["avg_processing_latency_ms"] is None


@pytest.mark.asyncio
async def test_task_manager_shutdown_cancels_active_tasks_and_rejects_new_tasks():
    started = asyncio.Event()

    async def runner(text, observer, settings):
        del text, observer, settings
        started.set()
        await asyncio.sleep(3600)
        return make_result()

    manager = AnalysisTaskManager(runner=runner, repository=FakeRepository())
    task = manager.create_task("task text", make_settings())
    await started.wait()

    await manager.shutdown()

    payload = manager.get_task(task.task_id)
    assert payload is not None
    assert payload.status == "cancelled"
    assert payload.error_message == "分析服务正在关闭，任务已取消"
    with pytest.raises(RuntimeError, match="分析服务正在关闭"):
        manager.create_task("new task", make_settings())
