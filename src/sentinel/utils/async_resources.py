"""异步资源（LLM 客户端、HTTP 连接等）的统一关闭工具。"""

from typing import Any


async def close_resource(resource: Any) -> None:
    if resource is None:
        return

    close_fn = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close_fn is None:
        return

    result = close_fn()
    if hasattr(result, "__await__"):
        await result


async def close_inner_http_client(resource: Any) -> None:
    """Close an inner AsyncOpenAI or httpx client if present."""
    if resource is None:
        return
    for attr in ("client", "_client"):
        inner = getattr(resource, attr, None)
        if inner is None:
            continue
        if callable(getattr(inner, "is_closed", None)) and inner.is_closed():
            continue
        await close_resource(inner)
