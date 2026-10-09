import asyncio
import sys

import pytest
from rich.console import Console

from scripts import run_blacklist_kv_demo as demo
from sentinel.utils import stage_timer
from sentinel.utils.stage_timer import StageTimer


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.stdout = object()
        self.returncode = None
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._last = self._values[-1] if self._values else 0.0

    def perf_counter(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last

    def paired_perf_counter(self) -> float:
        if self._values:
            self._last = self._values[0]
            if len(self._values) > 1:
                self._values.pop(0)
        return self._last


class MutableClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def perf_counter(self) -> float:
        return self.value


def render_rich_text(renderable: object) -> str:
    console = Console(force_terminal=False, color_system=None, width=120)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


@pytest.mark.asyncio
async def test_main_catches_assertion_failure(monkeypatch, capsys):
    fake_process = FakeProcess()
    prompts_seen = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_process

    async def fake_read_until_prompt(process, context):
        nonlocal prompts_seen
        prompts_seen += 1
        return "EVENT_ID: E001\n"

    async def fake_validate_after_case(case, processed_cases, neo4j_baseline):
        raise AssertionError("case case_01 database validation failed")

    monkeypatch.setattr(
        demo,
        "TEST_CASES",
        [{"id": "case_01", "title": "Case", "text": "hello", "expect": []}],
    )
    monkeypatch.setattr(
        demo,
        "reset_demo_state",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        demo,
        "collect_neo4j_baseline",
        lambda cases: asyncio.sleep(0, result={"case_01": 0}),
    )
    monkeypatch.setattr(demo, "validate_after_case", fake_validate_after_case)
    monkeypatch.setattr(demo, "read_until_prompt", fake_read_until_prompt)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await demo.main() == 1

    captured = capsys.readouterr()
    assert (
        "[ERROR] 数据库校验失败: case case_01 database validation failed"
        in captured.out
    )
    assert "Traceback" not in captured.err
    assert prompts_seen == 2


def test_child_failure_report_prints_child_output_to_stderr(capsys):
    err = demo.ReadPromptError(
        reason="timeout",
        context="case case_01",
        accumulated="child output",
        returncode=None,
    )

    demo._report_child_failure(err, FakeProcess())

    captured = capsys.readouterr()
    assert "[ERROR] 子进程异常 — timeout" in captured.err
    assert "[ERROR] 子进程最后输出 (12 chars):" in captured.err
    assert "child output" in captured.err


@pytest.mark.asyncio
async def test_main_launches_child_with_unbuffered_stdout(monkeypatch):
    fake_process = FakeProcess()
    launch = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        launch["args"] = args
        launch["kwargs"] = kwargs
        return fake_process

    async def fake_read_until_prompt(process, context):
        if context == "initial startup":
            raise demo.ReadPromptError(
                reason="timeout",
                context=context,
                accumulated="",
                returncode=None,
            )
        return ""

    monkeypatch.setattr(
        demo,
        "TEST_CASES",
        [{"id": "case_01", "title": "Case", "text": "hello", "expect": []}],
    )
    monkeypatch.setattr(
        demo,
        "reset_demo_state",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        demo,
        "collect_neo4j_baseline",
        lambda cases: asyncio.sleep(0, result={"case_01": 0}),
    )
    monkeypatch.setattr(demo, "read_until_prompt", fake_read_until_prompt)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await demo.main() == 1

    assert launch["args"][:4] == (sys.executable, "-u", "-m", "sentinel.main")
    assert launch["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"


def test_print_case_writes_details_to_stdout(capsys):
    demo.print_case(
        {
            "title": "Case title",
            "text": "case body",
            "expect": ["checkpoint"],
        }
    )

    captured = capsys.readouterr()
    assert "Case title" in captured.out
    assert "case body" in captured.out
    assert "checkpoint" in captured.out


def test_demo_script_reuses_shared_logging_helpers():
    assert not hasattr(demo, "DemoRunLogger")
    assert demo.get_logger.__module__ == "sentinel.utils.logging"


def test_setup_stage_timer_records_live_stage_completion(monkeypatch):
    live_events: list[tuple[str, object]] = []
    tick_values = iter([0.0, 0.0, 0.5, 0.5, 1.2])

    class FakeLive:
        def __init__(
            self,
            renderable,
            *,
            console=None,
            refresh_per_second=None,
            transient=None,
        ) -> None:
            del console, refresh_per_second, transient
            live_events.append(("init", renderable))

        def __enter__(self):
            live_events.append(("enter", None))
            return self

        def __exit__(self, *args):
            live_events.append(("exit", None))
            return None

        def update(self, renderable) -> None:
            live_events.append(("update", renderable))

    monkeypatch.setattr(stage_timer, "Live", FakeLive)
    monkeypatch.setattr(stage_timer.time, "perf_counter", lambda: next(tick_values))

    timer = StageTimer(
        live_enabled=True,
        console=None,
    )

    with timer:
        with timer.stage("seed keywords"):
            pass

    timings = timer.timings
    assert timings == [("seed keywords", 0.5)]
    rendered = render_rich_text(timer)
    assert "seed keywords" in rendered
    assert "0.500s" in rendered
    assert live_events[0][0] == "init"
    assert live_events[-1][0] == "exit"


def test_setup_stage_timer_live_renderable_recomputes_elapsed(monkeypatch):
    clock = MutableClock()
    live_renderable = None

    class FakeLive:
        def __init__(
            self,
            renderable,
            *,
            console=None,
            refresh_per_second=None,
            transient=None,
        ) -> None:
            del console, refresh_per_second, transient
            nonlocal live_renderable
            live_renderable = renderable

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def update(self, renderable) -> None:
            nonlocal live_renderable
            live_renderable = renderable

    monkeypatch.setattr(stage_timer, "Live", FakeLive)
    monkeypatch.setattr(stage_timer.time, "perf_counter", clock.perf_counter)

    timer = StageTimer(
        live_enabled=True,
        console=None,
    )

    with timer:
        stage = timer.stage("seed keywords")
        stage.__enter__()
        clock.value = 1.0
        first = render_rich_text(live_renderable)
        clock.value = 2.5
        second = render_rich_text(live_renderable)
        stage.__exit__(None, None, None)

    assert "seed keywords" in first
    assert "1.000s" in first
    assert "seed keywords" in second
    assert "2.500s" in second


def test_setup_stage_timer_live_renderable_rotates_status(monkeypatch):
    clock = MutableClock()
    live_renderable = None

    class FakeLive:
        def __init__(
            self,
            renderable,
            *,
            console=None,
            refresh_per_second=None,
            transient=None,
        ) -> None:
            del console, refresh_per_second, transient
            nonlocal live_renderable
            live_renderable = renderable

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def update(self, renderable) -> None:
            nonlocal live_renderable
            live_renderable = renderable

    monkeypatch.setattr(stage_timer, "Live", FakeLive)
    monkeypatch.setattr(stage_timer.time, "perf_counter", clock.perf_counter)

    timer = StageTimer(
        live_enabled=True,
        console=None,
    )

    with timer:
        stage = timer.stage("seed keywords")
        stage.__enter__()
        clock.value = 0.0
        first = render_rich_text(live_renderable)
        clock.value = 0.2
        second = render_rich_text(live_renderable)
        stage.__exit__(None, None, None)

    assert first.strip().split(maxsplit=1)[0] != second.strip().split(maxsplit=1)[0]


def test_setup_stage_timer_does_not_emit_textual_breakdown(monkeypatch, capsys):
    tick_values = iter([0.0, 0.0, 0.4, 0.4])

    monkeypatch.setattr(stage_timer.time, "perf_counter", lambda: next(tick_values))

    timer = StageTimer(live_enabled=False)

    with timer:
        with timer.stage("load settings"):
            pass

    captured = capsys.readouterr()
    assert "Duration breakdown" not in captured.out
    assert "load settings" not in captured.out
    assert not hasattr(timer, "emit_breakdown")


@pytest.mark.asyncio
async def test_reset_demo_state_calls_shared_full_reset(monkeypatch):
    detail_lines: list[str] = []
    stage_entries: list[tuple[str, str]] = []

    class FakeStage:
        def __init__(self, label: str) -> None:
            self._label = label

        def __enter__(self):
            stage_entries.append(("enter", self._label))
            return self

        def __exit__(self, *args):
            stage_entries.append(("exit", self._label))
            return None

    summary = demo.DemoStateResetSummary(
        neo4j_database="neo4j",
        deleted_neo4j_nodes=7,
        dropped_milvus_collections={
            "blacklist_keywords": True,
            "input_events": True,
        },
        person_count=1,
        keyword_count=35,
        event_count=9,
    )

    async def fake_reset_and_seed_demo_state():
        return summary

    monkeypatch.setattr(
        demo, "reset_and_seed_demo_state", fake_reset_and_seed_demo_state
    )
    monkeypatch.setattr(demo, "stage", lambda label: FakeStage(label))
    monkeypatch.setattr(demo, "log_detail", lambda line: detail_lines.append(line))

    observed = await demo.reset_demo_state()

    assert observed == summary
    assert [entry for event, entry in stage_entries if event == "enter"] == [
        "reset Neo4j and Milvus demo state"
    ]
    assert detail_lines == [
        "Reset demo state and seeded blacklist Milvus:",
        "  Neo4j (neo4j): deleted 7 graph nodes",
        "  Seeded 1 persons, 35 keywords, 9 events",
        "  Milvus collection blacklist_keywords: dropped",
        "  Milvus collection input_events: dropped",
    ]


@pytest.mark.asyncio
async def test_reset_demo_state_propagates_shared_reset_failure(monkeypatch):
    stage_entries: list[tuple[str, str]] = []

    class FakeStage:
        def __init__(self, label: str) -> None:
            self._label = label

        def __enter__(self):
            stage_entries.append(("enter", self._label))
            return self

        def __exit__(self, *args):
            stage_entries.append(("exit", self._label))
            return None

    async def fake_reset_and_seed_demo_state():
        raise RuntimeError("neo4j reset failed")

    monkeypatch.setattr(
        demo, "reset_and_seed_demo_state", fake_reset_and_seed_demo_state
    )
    monkeypatch.setattr(demo, "stage", lambda label: FakeStage(label))

    with pytest.raises(RuntimeError, match="neo4j reset failed"):
        await demo.reset_demo_state()

    assert stage_entries == [
        ("enter", "reset Neo4j and Milvus demo state"),
        ("exit", "reset Neo4j and Milvus demo state"),
    ]


@pytest.mark.asyncio
async def test_main_configures_file_logging_for_detail_logs(
    monkeypatch, tmp_path, capsys
):
    fake_process = FakeProcess()
    configured_log_dirs = []
    detail_log_path = tmp_path / "sentinel.log"

    def fake_setup_file_logging(log_dir=None):
        configured_log_dirs.append(log_dir)
        return str(detail_log_path)

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_process

    async def fake_read_until_prompt(process, context):
        if context == "initial startup":
            raise demo.ReadPromptError(
                reason="timeout",
                context=context,
                accumulated="",
                returncode=None,
            )
        return ""

    monkeypatch.setattr(demo, "setup_file_logging", fake_setup_file_logging)
    monkeypatch.setattr(
        demo,
        "TEST_CASES",
        [{"id": "case_01", "title": "Case", "text": "hello", "expect": []}],
    )
    monkeypatch.setattr(
        demo,
        "reset_demo_state",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        demo,
        "collect_neo4j_baseline",
        lambda cases: asyncio.sleep(0, result={"case_01": 0}),
    )
    monkeypatch.setattr(demo, "read_until_prompt", fake_read_until_prompt)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await demo.main() == 1

    assert configured_log_dirs == [str(demo.ROOT / "logs" / "blacklist_kv_demo")]
    captured = capsys.readouterr()
    assert f"自动回放详细日志文件: {detail_log_path}" in captured.out
