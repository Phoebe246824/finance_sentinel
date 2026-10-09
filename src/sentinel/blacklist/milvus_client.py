"""黑名单侧 Milvus 连接客户端的构建与共享工具。"""

import os
from dataclasses import dataclass
from typing import Any

from pymilvus import MilvusClient


@dataclass(frozen=True)
class MilvusConfig:
    uri: str = "http://localhost:19530"
    token: str = ""


def milvus_config_from_app(config: dict[str, Any]) -> MilvusConfig:
    milvus_config = config.get("milvus", {}) if isinstance(config, dict) else {}
    return MilvusConfig(
        uri=str(
            milvus_config.get("uri")
            or os.getenv("MILVUS_URI")
            or "http://localhost:19530"
        ),
        token=str(milvus_config.get("token") or os.getenv("MILVUS_TOKEN") or ""),
    )


def create_milvus_client(config: MilvusConfig) -> MilvusClient:
    kwargs = {"uri": config.uri}
    if config.token:
        kwargs["token"] = config.token
    return MilvusClient(**kwargs)
