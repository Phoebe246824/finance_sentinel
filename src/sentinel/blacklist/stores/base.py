"""黑名单 Milvus store 的共享基类与协议。"""

import hashlib
import inspect
import json
import math
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Final

from pymilvus import DataType, MilvusClient
from pymilvus.exceptions import ErrorCode, MilvusException

from sentinel.utils.logging import get_logger

EmbeddingFn = Callable[[str], list[float] | Awaitable[list[float]]]
INTERNAL_VECTOR_FIELD: Final = "_storage_vector"
INTERNAL_VECTOR_DIM: Final = 2
INTERNAL_VECTOR_VALUE: Final = (0.0, 0.0)

logger = get_logger(__name__)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    dtype: DataType
    is_primary: bool = False
    max_length: int | None = None
    max_capacity: int | None = None
    element_type: DataType | None = None
    dim: int | None = None
    default_value: Any | None = None


class MilvusBaseStore(ABC):
    collection_name: ClassVar[str]
    primary_field: ClassVar[str]
    vector_field: ClassVar[str] = ""

    def __init__(self, client: MilvusClient, *, embedding_dim: int = 1024) -> None:
        self._client = client
        self._embedding_dim = embedding_dim
        self._collection_ready = False

    @abstractmethod
    def fields(self) -> list[FieldSpec]: ...

    def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if self._client.has_collection(self.collection_name):
            self._collection_ready = True
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        for field in self._schema_fields():
            kwargs: dict[str, Any] = {
                "field_name": field.name,
                "datatype": field.dtype,
                "is_primary": field.is_primary,
            }
            if field.max_length is not None:
                kwargs["max_length"] = field.max_length
            if field.max_capacity is not None:
                kwargs["max_capacity"] = field.max_capacity
            if field.element_type is not None:
                kwargs["element_type"] = field.element_type
            if field.dim is not None:
                kwargs["dim"] = field.dim
            if field.default_value is not None:
                kwargs["default_value"] = field.default_value
            schema.add_field(**kwargs)

        index_params = None
        index_field = self._index_vector_field()
        if index_field:
            index_params = MilvusClient.prepare_index_params()
            index_params.add_index(
                field_name=index_field,
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )

        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )
        load_collection = getattr(self._client, "load_collection", None)
        if load_collection is not None:
            load_collection(collection_name=self.collection_name)
        self._collection_ready = True

    def upsert_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.ensure_collection()
        storage_rows = self._storage_rows(rows)
        try:
            result = self._client.upsert(
                collection_name=self.collection_name,
                data=storage_rows,
            )
        except MilvusException as error:
            if not self._is_collection_not_found(error):
                raise
            self._recreate_collection()
            result = self._client.upsert(
                collection_name=self.collection_name,
                data=storage_rows,
            )
        self.flush()
        return int(result.get("upsert_count", len(rows)))

    def query_rows(
        self,
        filter_expr: str,
        output_fields: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not filter_expr.strip():
            raise ValueError("Milvus query filter must be non-empty")
        self.ensure_collection()
        try:
            return self._client.query(
                collection_name=self.collection_name,
                filter=filter_expr,
                output_fields=output_fields,
                limit=limit,
            )
        except MilvusException as error:
            if not self._is_collection_not_found(error):
                raise
            self._recreate_collection()
            return self._client.query(
                collection_name=self.collection_name,
                filter=filter_expr,
                output_fields=output_fields,
                limit=limit,
            )

    def delete_rows(self, filter_expr: str) -> int:
        if not filter_expr.strip():
            raise ValueError("Milvus delete filter must be non-empty")
        self.ensure_collection()
        try:
            result = self._client.delete(
                collection_name=self.collection_name,
                filter=filter_expr,
            )
        except MilvusException as error:
            if not self._is_collection_not_found(error):
                raise
            self._recreate_collection()
            result = self._client.delete(
                collection_name=self.collection_name,
                filter=filter_expr,
            )
        self.flush()
        return int(result.get("delete_count", 0))

    def close_client(self) -> None:
        self._client.close()

    def flush(self) -> None:
        flush = getattr(self._client, "flush", None)
        if flush is not None:
            flush(collection_name=self.collection_name)

    def _recreate_collection(self) -> None:
        logger.warning(
            "recreating Milvus collection %s after COLLECTION_NOT_FOUND",
            self.collection_name,
        )
        self._collection_ready = False
        self.ensure_collection()

    @staticmethod
    def _is_collection_not_found(error: MilvusException) -> bool:
        return error.code == ErrorCode.COLLECTION_NOT_FOUND

    def _schema_fields(self) -> list[FieldSpec]:
        fields = self.fields()
        if self.vector_field:
            return fields
        return [
            *fields,
            FieldSpec(
                INTERNAL_VECTOR_FIELD,
                DataType.FLOAT_VECTOR,
                dim=INTERNAL_VECTOR_DIM,
            ),
        ]

    def _index_vector_field(self) -> str:
        return self.vector_field or INTERNAL_VECTOR_FIELD

    def _storage_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.vector_field:
            return rows
        return [
            {**row, INTERNAL_VECTOR_FIELD: list(INTERNAL_VECTOR_VALUE)} for row in rows
        ]

    @staticmethod
    async def resolve_embedding(embedding_fn: EmbeddingFn, text: str) -> list[float]:
        embedding = embedding_fn(text)
        if inspect.isawaitable(embedding):
            embedding = await embedding
        return [float(value) for value in embedding]

    @staticmethod
    async def resolve_embeddings(
        embedding_fn: EmbeddingFn,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []
        embeddings = embedding_fn(texts)  # type: ignore[arg-type]
        if inspect.isawaitable(embeddings):
            embeddings = await embeddings
        if embeddings and isinstance(embeddings[0], list):
            return [[float(value) for value in embedding] for embedding in embeddings]
        return [
            await MilvusBaseStore.resolve_embedding(embedding_fn, text)
            for text in texts
        ]

    @staticmethod
    def fallback_embedding(text: str, embedding_dim: int) -> list[float]:
        if embedding_dim <= 0:
            return []

        normalized = "".join(str(text).lower().split())
        if not normalized:
            return [0.0] * embedding_dim

        grams = (
            [normalized[i : i + 2] for i in range(len(normalized) - 1)]
            if len(normalized) > 1
            else [normalized]
        )
        vector = [0.0] * embedding_dim
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % embedding_dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def now_iso() -> str:
        return datetime.now().isoformat(timespec="microseconds")

    @staticmethod
    def quote(value: str) -> str:
        return json.dumps(value)

    @staticmethod
    def id_filter(field_name: str, values: list[str]) -> str:
        quoted = ", ".join(json.dumps(value) for value in values)
        return f"{field_name} in [{quoted}]"

    @staticmethod
    def like_filter(field_names: list[str], keyword: str) -> str:
        normalized = keyword.strip()
        if not normalized:
            return ""
        pattern = MilvusBaseStore.quote(f"%{normalized}%")
        clauses = [f"{field_name} like {pattern}" for field_name in field_names]
        return "(" + " or ".join(clauses) + ")"
