"""按推荐顺序自动回放 blacklist/Milvus/filter 功能测试样例。"""

import asyncio
import os
import re
import sys
from pathlib import Path

from scripts.blacklist_demo_assertions import (
    Neo4jCaseInspector,
    assert_case_state,
    collect_case_state_snapshot,
)
from scripts.blacklist_demo_cases import TEST_CASES
from scripts.reset_and_seed_demo_state import (
    DemoStateResetSummary,
    format_reset_summary,
    reset_and_seed_demo_state,
)
from sentinel.utils.logging import get_logger, setup_file_logging
from sentinel.utils.stage_timer import stage, timed_stages

ROOT = Path(__file__).resolve().parents[1]
PROMPT_TEXT = "请输入消息内容:"
WAIT_TIMEOUT_SECONDS = 300
SHUTDOWN_TIMEOUT_SECONDS = 10
EVENT_ID_PATTERN = re.compile(r"EVENT_ID:\s*([A-Za-z0-9_-]+)")


DETAIL_LOGGER = get_logger("scripts.blacklist_kv_demo")


def log_detail(*args: object, sep: str = " ", end: str = "\n") -> None:
    text = sep.join(str(arg) for arg in args) + end
    if text:
        DETAIL_LOGGER.info("%s", text.rstrip("\n"))


class ReadPromptError(Exception):
    """子进程提示等待失败 — 携带已缓冲的子进程输出。"""

    def __init__(
        self,
        reason: str,
        context: str,
        accumulated: str,
        returncode: int | None = None,
    ):
        self.reason = reason
        self.context = context
        self.accumulated = accumulated
        self.returncode = returncode
        parts = [f"read_until_prompt {reason}: {context}"]
        if returncode is not None:
            parts.append(f"(exit code {returncode})")
        super().__init__("; ".join(parts))


def print_case(case: dict) -> None:
    separator = "=" * 100
    print(separator)
    print(case["title"])
    print("- 输入文本:")
    print(case["text"])
    print("- 预期检查点:")
    for item in case["expect"]:
        print(f"  - {item}")


async def read_until_prompt(process: asyncio.subprocess.Process, context: str) -> str:
    """读取子进程 stdout 直到看见 PROMPT_TEXT。"""
    assert process.stdout is not None
    output_parts: list[str] = []
    accumulated = ""
    try:
        while True:
            chunk = await asyncio.wait_for(
                process.stdout.read(1024), timeout=WAIT_TIMEOUT_SECONDS
            )
            if not chunk:
                try:
                    remaining = await asyncio.wait_for(
                        process.stdout.read(), timeout=1.0
                    )
                    if remaining:
                        text = remaining.decode("utf-8", errors="replace")
                        print(text, end="")
                        output_parts.append(text)
                        accumulated += text
                except (asyncio.TimeoutError, Exception):
                    pass

                exit_code: int | None = None
                try:
                    exit_code = await asyncio.wait_for(process.wait(), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
                raise ReadPromptError(
                    reason="child_stdout_closed",
                    context=context,
                    accumulated="".join(output_parts),
                    returncode=exit_code,
                )
            text = chunk.decode("utf-8", errors="replace")
            print(text, end="")
            output_parts.append(text)
            accumulated += text
            if PROMPT_TEXT in accumulated:
                break
    except asyncio.TimeoutError:
        exit_code: int | None = None
        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=0.1)
        except (asyncio.TimeoutError, Exception):
            pass
        raise ReadPromptError(
            reason="timeout",
            context=context,
            accumulated="".join(output_parts),
            returncode=exit_code,
        )
    return "".join(output_parts)


def extract_event_id(output: str) -> str | None:
    matches = EVENT_ID_PATTERN.findall(output)
    if not matches:
        return None
    return matches[-1]


async def collect_neo4j_baseline(cases: list[dict]) -> dict[str, int]:
    inspector = Neo4jCaseInspector()
    baseline = {}
    for case in cases:
        state = await inspector.inspect_case(case)
        baseline[case["id"]] = int(state.get("content_count") or 0)
    return baseline


async def validate_after_case(
    case: dict,
    processed_cases: list[dict],
    neo4j_baseline: dict[str, int],
) -> None:
    snapshot = await collect_case_state_snapshot(processed_cases)
    failures = assert_case_state(case, snapshot)
    filtered_failures = []
    neo4j_duplicate_failures = []

    for failure in failures:
        if not failure.path.startswith("neo4j."):
            filtered_failures.append(failure)
            continue

        case_state = snapshot["cases"].get(failure.case_id, {})
        neo4j_state = case_state.get("neo4j", {})
        before_count = neo4j_baseline.get(failure.case_id, 0)
        after_count = int(neo4j_state.get("content_count") or 0)
        expected_neo4j = failure.expected

        if before_count > 0:
            if after_count == before_count:
                log_detail(
                    f"- Neo4j baseline 校验通过 [{failure.case_id}]: "
                    f"before={before_count}, after={after_count}，未重复构图"
                )
            else:
                neo4j_duplicate_failures.append(
                    f"[{failure.case_id}] neo4j.content_count: before={before_count}, after={after_count}，疑似重复构图"
                )
            continue

        if failure.path == "neo4j.content_count" and expected_neo4j == 0:
            if after_count == before_count:
                continue
            neo4j_duplicate_failures.append(
                f"[{failure.case_id}] neo4j.content_count: expected no new graph, before={before_count}, after={after_count}"
            )
            continue

        filtered_failures.append(failure)

    state = snapshot["cases"].get(case["id"], {})
    log_detail("- 数据库状态快照:")
    log_detail(f"  Milvus: {state.get('milvus')}")
    log_detail(f"  Neo4j: {state.get('neo4j')}")
    if filtered_failures or neo4j_duplicate_failures:
        log_detail("- 校验结果: FAIL")
        for failure in filtered_failures:
            log_detail(
                f"  [{failure.case_id}] {failure.path}: "
                f"expected={failure.expected!r}, observed={failure.observed!r}"
            )
        for failure in neo4j_duplicate_failures:
            log_detail(f"  {failure}")
        raise AssertionError(f"case {case['id']} database validation failed")
    log_detail("- 校验结果: PASS")


@timed_stages()
async def reset_demo_state() -> DemoStateResetSummary:
    with stage("reset Neo4j and Milvus demo state"):
        summary = await reset_and_seed_demo_state()
    for line in format_reset_summary(summary):
        log_detail(line)
    return summary


async def main() -> int:
    logs_dir = ROOT / "logs"
    detail_log_dir = logs_dir / "blacklist_kv_demo"
    main_log_dir = logs_dir / "blacklist_kv_demo_main"
    detail_log_path = setup_file_logging(str(detail_log_dir))

    process = None
    try:
        print(f"自动回放详细日志文件: {detail_log_path}")
        print(f"Sentinel Pipeline 流程日志目录: {main_log_dir}")
        print(
            "[1/3] 重置 Neo4j 与 Sentinel Milvus demo 数据，并预置黑名单测试数据...\n"
        )
        await reset_demo_state()

        print("\n[2/3] 输出本次自动回放的测试数据与检查点\n")
        for case in TEST_CASES:
            print_case(case)

        print("\n记录 Neo4j 运行前 baseline，用于判断是否新增重复构图\n")
        neo4j_baseline = await collect_neo4j_baseline(TEST_CASES)
        for case in TEST_CASES:
            log_detail(
                f"  [{case['id']}] neo4j.content_count.before={neo4j_baseline[case['id']]}"
            )

        print("\n[3/3] 启动 Sentinel Pipeline 并按顺序自动写入测试数据\n")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-m",
            "sentinel.main",
            "--log-dir",
            str(main_log_dir),
            cwd=str(ROOT),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        assert process.stdin is not None
        assert process.stdout is not None

        await read_until_prompt(process, "initial startup")

        processed_cases: list[dict] = []
        for index, case in enumerate(TEST_CASES, start=1):
            assert process.stdin is not None
            print(f"[{index}/{len(TEST_CASES)}] 运行 {case['id']}")
            print_case(case)
            process.stdin.write((case["text"] + "\n").encode("utf-8"))
            await process.stdin.drain()
            output = await read_until_prompt(process, f"case {case['id']}")
            processed_case = {**case, "event_id": extract_event_id(output)}
            processed_cases.append(processed_case)
            await validate_after_case(processed_case, processed_cases, neo4j_baseline)

        assert process.stdin is not None
        process.stdin.write(b"exit\n")
        await process.stdin.drain()
        process.stdin.close()

        returncode = await process.wait()
        if returncode != 0:
            raise RuntimeError(f"Sentinel Pipeline exited with code {returncode}")

        print("=" * 100)
        print("自动回放完成，请结合日志与 Milvus 检查结果")
        print("=" * 100)
        return 0
    except ReadPromptError as e:
        if process is not None:
            _report_child_failure(e, process)
        return 1
    except AssertionError as e:
        print(f"\n[ERROR] 数据库校验失败: {e}")
        return 1
    except RuntimeError as e:
        print(f"\n[ERROR] 子进程异常退出: {e}")
        return 1
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


def _report_child_failure(
    err: ReadPromptError, process: asyncio.subprocess.Process
) -> None:
    """Print a structured failure report for a subprocess crash / timeout."""
    exit_str = (
        str(err.returncode) if err.returncode is not None else "仍在运行 (timeout)"
    )
    report_lines = [
        "\n" + "!" * 70,
        f"[ERROR] 子进程异常 — {err.reason}",
        f"[ERROR] 上下文: {err.context}",
        f"[ERROR] 子进程状态: {exit_str}",
    ]
    if err.accumulated:
        summary = err.accumulated
        if len(summary) > 3000:
            summary = "(最后 3000 字符)\n" + summary[-3000:]
        report_lines.append(f"[ERROR] 子进程最后输出 ({len(err.accumulated)} chars):")
        report_lines.append(summary)
    report_lines.append("!" * 70)
    report = "\n".join(report_lines) + "\n"
    print(report, end="", file=sys.stderr)
    DETAIL_LOGGER.error("%s", report.rstrip("\n"))


def main_sync() -> int:
    return asyncio.run(main())


if __name__ == "__main__":
    sys.exit(main_sync())
