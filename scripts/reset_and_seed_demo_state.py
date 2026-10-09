"""重置 Neo4j、Sentinel Milvus demo 状态并写入黑名单测试种子数据。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sentinel.blacklist.stores import create_store_bundle
from sentinel.blacklist.stores.factory import milvus_collection_names
from sentinel.config import get_settings


@dataclass(frozen=True, slots=True)
class DemoStateResetSummary:
    neo4j_database: str
    deleted_neo4j_nodes: int
    dropped_milvus_collections: dict[str, bool]
    person_count: int
    keyword_count: int
    event_count: int


PERSON_SEEDS = [
    "P105",
    "P203",
    "P204",
]

KEYWORD_SEEDS = [
    "洗钱",
    "反洗钱",
    "分拆交易",
    "涉诈",
    "涉诈账户",
    "虚拟币",
    "保证金",
    "贷款欺诈",
    "包装流水",
    "冻结",
    "新设备",
    "境外 IP",
    "短信验证码",
    "支付通道",
    "投诉",
    "返利",
    "制裁名单",
    "跨境汇款",
    "最终受益人",
    "KYC",
    "KYB",
    "套现",
    "虚假交易",
    "退款",
    "设备指纹",
    "账户接管",
    "白名单",
    "非常用设备",
    "供应链融资",
    "虚假贸易",
    "票据套利",
    "应收账款",
    "场外交易",
    "出金",
    "洗钱通道",
]

EVENT_SEEDS = [
    (
        "E-FIN-AML-001",
        "客户在短时间内向多个新开户账户转出接近阈值资金，随后资金归集至虚拟币平台，疑似分拆交易与洗钱。",
    ),
    (
        "E-FIN-FRAUD-001",
        "客户向曾被投诉的涉诈账户转账虚拟币保证金，交易设备异常且登录地点偏离常驻城市。",
    ),
    (
        "E-FIN-DEVICE-001",
        "客户账户在非常用设备和异常地理位置登录后立即发起大额转账，疑似账户盗用或电诈转账。",
    ),
    (
        "E-FIN-MULE-001",
        "多个客户向同一新开户账户集中转账，资金随后快速出金至外部支付通道，疑似跑分或资金归集账户。",
    ),
]


async def reset_neo4j_graph(
    *,
    uri: str,
    user: str,
    password: str,
    database: str,
    driver_factory: Callable[..., Any] | None = None,
) -> int:
    if driver_factory is None:
        from neo4j import AsyncGraphDatabase

        driver_factory = AsyncGraphDatabase.driver

    driver = driver_factory(uri, auth=(user, password))
    try:
        async with driver.session(database=database) as session:
            result = await session.run(
                """
                MATCH (node)
                WITH collect(node) AS nodes, count(node) AS node_count
                FOREACH (node IN nodes | DETACH DELETE node)
                RETURN node_count
                """
            )
            record = await result.single()
            if record is None:
                return 0
            return int(record["node_count"])
    finally:
        await driver.close()


def reset_milvus_collection(
    *,
    uri: str,
    token: str,
    collection_name: str,
    client_factory: Callable[..., Any] | None = None,
) -> bool:
    if client_factory is None:
        from pymilvus import MilvusClient

        client_factory = MilvusClient

    client = client_factory(uri=uri, token=token or None)
    try:
        if not client.has_collection(collection_name):
            return False
        client.drop_collection(collection_name)
        return True
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            close()


def _build_store_config(settings: Any) -> dict:
    return {
        "milvus": {
            "uri": settings.milvus_uri,
            "token": settings.optional_milvus_token() or "",
            "input_events_collection": settings.milvus_input_events_collection,
            "kv_ttl_days": settings.kv_ttl_days,
            "stash_semantic_top_k": settings.stash_semantic_top_k,
            "stash_rerank_min_score": settings.stash_rerank_min_score,
            "stash_rerank_enabled": settings.stash_rerank_enabled,
            "batch_max_per_person": settings.batch_max_per_person,
            "embedding_dim": settings.embedding_dim,
        },
        "embedder": {
            "model": settings.embedder_model,
            "api_key": settings.effective_embedder_api_key_value(),
            "api_base": settings.effective_embedder_api_base,
        },
    }


def format_reset_summary(summary: DemoStateResetSummary) -> list[str]:
    lines = [
        "Reset demo state and seeded blacklist Milvus:",
        f"  Neo4j ({summary.neo4j_database}): deleted {summary.deleted_neo4j_nodes} graph nodes",
        (
            f"  Seeded {summary.person_count} persons, "
            f"{summary.keyword_count} keywords, {summary.event_count} events"
        ),
    ]
    for collection_name, dropped in summary.dropped_milvus_collections.items():
        milvus_status = "dropped" if dropped else "not found"
        lines.append(f"  Milvus collection {collection_name}: {milvus_status}")
    return lines


def print_reset_summary(summary: DemoStateResetSummary) -> None:
    for line in format_reset_summary(summary):
        print(line)


async def reset_and_seed_demo_state() -> DemoStateResetSummary:
    settings = get_settings()
    config = _build_store_config(settings)

    deleted_neo4j_nodes = await reset_neo4j_graph(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.require_neo4j_password(),
        database=settings.neo4j_database,
    )
    dropped_milvus_collections = {
        collection_name: reset_milvus_collection(
            uri=settings.milvus_uri,
            token=settings.optional_milvus_token() or "",
            collection_name=collection_name,
        )
        for collection_name in milvus_collection_names(config)
    }
    bundle = create_store_bundle(config)

    try:
        person_count = await bundle.persons.append_persons(PERSON_SEEDS)
        keyword_count = await bundle.keywords.append_keywords(KEYWORD_SEEDS)
        event_count = await bundle.event_samples.append_events(EVENT_SEEDS)
        return DemoStateResetSummary(
            neo4j_database=settings.neo4j_database,
            deleted_neo4j_nodes=deleted_neo4j_nodes,
            dropped_milvus_collections=dropped_milvus_collections,
            person_count=person_count,
            keyword_count=keyword_count,
            event_count=event_count,
        )
    finally:
        aclose = getattr(bundle, "aclose", None)
        if aclose is not None:
            await aclose()
        else:
            bundle.close()


async def main() -> None:
    summary = await reset_and_seed_demo_state()
    print_reset_summary(summary)


def main_sync() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
