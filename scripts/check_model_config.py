"""检查 LLM/embedder/reranker 模型配置的本地诊断脚本。"""

import argparse
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sentinel.config import get_settings
from sentinel.utils.litellm_embedding import embed_text
from sentinel.utils.litellm_models import litellm_model_name, litellm_rerank_model_name
from sentinel.utils.litellm_rerank import rerank_scores
from sentinel.utils.litellm_text import generate_text

LIVE_WARNING = (
    "WARNING: live model checks may consume user account quota; token use is tiny "
    "and each distinct model configuration is called at most once."
)
EXIT_CANCELLED = 2
THINKING_DISABLED_EXTRA_BODY = {
    "enable_thinking": False,
    "thinking": {"type": "disabled"},
}


@dataclass(frozen=True)
class ModelCheck:
    label: str
    kind: str
    model: str
    base_url: str
    api_key: str
    provider: str

    @property
    def litellm_model(self) -> str:
        if self.kind == "reranker":
            return litellm_rerank_model_name(self.model)
        return litellm_model_name(self.provider, self.model)


@dataclass(frozen=True)
class ModelCheckResult:
    label: str
    status: str
    detail: str = ""

    def line(self) -> str:
        if self.detail:
            return f"{self.status} live {self.label}: {self.detail}"
        return f"{self.status} live {self.label}"


def _mask_secret(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _redact_text(value: object, secrets: Sequence[str]) -> str:
    redacted = str(value)
    for secret in sorted(
        {secret for secret in secrets if secret}, key=len, reverse=True
    ):
        redacted = redacted.replace(secret, _mask_secret(secret))
    return redacted


def _build_model_checks(settings: Any) -> list[ModelCheck]:
    return [
        ModelCheck(
            label="llm",
            kind="llm",
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.require_llm_api_key(),
            provider=settings.llm_provider,
        ),
        ModelCheck(
            label="embedder",
            kind="embedder",
            model=settings.embedder_model,
            base_url=settings.effective_embedder_api_base,
            api_key=settings.effective_embedder_api_key_value(),
            provider=settings.llm_provider,
        ),
        ModelCheck(
            label="reranker",
            kind="reranker",
            model=settings.effective_reranker_model,
            base_url=settings.effective_reranker_base_url,
            api_key=settings.effective_reranker_api_key_value(),
            provider=settings.llm_provider,
        ),
    ]


def _print_static_checks(checks: Sequence[ModelCheck]) -> None:
    for check in checks:
        print(
            f"STATIC PASS {check.label}: kind={check.kind} "
            f"model={check.litellm_model} "
            f"base_url={check.base_url} api_key={_mask_secret(check.api_key)}"
        )


def _deduplicate_checks(checks: Sequence[ModelCheck]) -> list[ModelCheck]:
    seen = set()
    unique = []
    for check in checks:
        key = (check.kind, check.litellm_model, check.base_url, check.api_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(check)
    return unique


def _confirm_live_checks(confirm_input: Callable[[str], str] = input) -> bool:
    print(LIVE_WARNING)
    try:
        answer = confirm_input("Type 'yes' to run live model checks: ")
    except EOFError:
        return False
    return answer == "yes"


async def _run_live_check(settings, check: ModelCheck) -> None:
    if check.kind == "llm":
        await generate_text(
            settings,
            prompt="ping",
            model=check.model,
            api_key=check.api_key,
            base_url=check.base_url,
            temperature=0,
            max_completion_tokens=4,
            extra_body=THINKING_DISABLED_EXTRA_BODY,
        )
        return

    if check.kind == "embedder":
        await embed_text(
            settings,
            "x",
            model=check.model,
            api_key=check.api_key,
            base_url=check.base_url,
        )
        return

    await rerank_scores(
        query="x",
        documents=["x"],
        model=check.model,
        api_key=check.api_key,
        base_url=check.base_url,
    )


async def run_live_checks(settings: Any) -> list[ModelCheckResult]:
    checks = _deduplicate_checks(_build_model_checks(settings))
    secrets = [check.api_key for check in checks]
    results: list[ModelCheckResult] = []
    for check in checks:
        try:
            await _run_live_check(settings, check)
        except Exception as exc:
            results.append(
                ModelCheckResult(check.label, "FAIL", _redact_text(exc, secrets))
            )
        else:
            results.append(ModelCheckResult(check.label, "PASS"))
    return results


async def _run_live_checks(settings: Any, checks: Sequence[ModelCheck]) -> int:
    failures = 0
    unique_checks = _deduplicate_checks(checks)
    secrets = [check.api_key for check in unique_checks]
    for check in unique_checks:
        try:
            await _run_live_check(settings, check)
        except Exception as exc:
            failures += 1
            print(f"FAIL live {check.label}: {_redact_text(exc, secrets)}")
        else:
            print(f"PASS live {check.label}")
    return 1 if failures else 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Sentinel non-Graphiti model configuration.",
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Only print static configuration; do not prompt for live checks.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Deprecated compatibility flag; live checks are the default.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the live-check confirmation prompt.",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Any] = get_settings,
    confirm_input: Callable[[str], str] = input,
) -> int:
    args = _parse_args(argv)
    try:
        settings = settings_loader()
    except Exception as exc:
        print(f"FAIL settings: {exc}")
        return 1

    checks = _build_model_checks(settings)
    _print_static_checks(checks)
    if args.static_only:
        return 0
    if args.yes:
        print(LIVE_WARNING)
        return asyncio.run(_run_live_checks(settings, checks))
    if not args.yes and not _confirm_live_checks(confirm_input):
        print("Live checks cancelled.")
        return EXIT_CANCELLED
    return asyncio.run(_run_live_checks(settings, checks))


if __name__ == "__main__":
    raise SystemExit(main())
