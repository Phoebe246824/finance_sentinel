"""Check configured RAGFlow retrieval without writing external data."""

import argparse
import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from sentinel.config import SentinelSettings, get_settings
from sentinel.ragflow.client import RagflowClient
from sentinel.ragflow.context import (
    format_knowledge_for_prompt,
    ragflow_config_from_settings,
)

DEFAULT_QUERY = "反洗钱 可疑交易 跑分 虚拟币 资金归集 风险识别"


async def _run_check(settings: SentinelSettings, query: str) -> int:
    config = ragflow_config_from_settings(settings)
    if not config.ready:
        print(
            "RAGFlow is not ready. Check config/config.yaml ragflow settings "
            "and RAGFLOW_API_KEY."
        )
        return 1

    result = await RagflowClient(config).retrieve(query)
    chunks = result.get("chunks", [])
    print(f"ready={result.get('ready')} chunks={len(chunks)}")
    formatted = format_knowledge_for_prompt(result, max_chars=1500)
    if formatted:
        print(formatted)
    return 0 if result.get("ready") else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Any] = get_settings,
) -> int:
    parser = argparse.ArgumentParser(description="Check RAGFlow retrieval settings.")
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    args = parser.parse_args(list(argv) if argv is not None else None)

    return asyncio.run(_run_check(settings_loader(), args.query))


if __name__ == "__main__":
    raise SystemExit(main())
