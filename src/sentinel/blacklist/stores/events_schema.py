"""事件 store 的 Milvus collection schema 定义。"""

from pymilvus import DataType

from sentinel.blacklist.stores.base import FieldSpec

EVENTS_COLLECTION: str = "input_events"
EVENTS_PRIMARY_FIELD: str = "event_id"
EVENTS_VECTOR_FIELD: str = "embedding"


def events_fields(embedding_dim: int = 1024) -> list[FieldSpec]:
    """Return the Milvus schema fields for the input events collection."""
    return [
        FieldSpec(
            EVENTS_PRIMARY_FIELD, DataType.VARCHAR, is_primary=True, max_length=64
        ),
        FieldSpec(
            "person_ids",
            DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=32,
            max_length=32,
        ),
        FieldSpec("raw_content", DataType.VARCHAR, max_length=8192),
        FieldSpec("created_at", DataType.VARCHAR, max_length=64),
        FieldSpec("expire_at", DataType.VARCHAR, max_length=64),
        FieldSpec("is_graph_built", DataType.BOOL),
        FieldSpec("analysis_status", DataType.VARCHAR, max_length=32),
        FieldSpec("analyzed_at", DataType.VARCHAR, max_length=64),
        FieldSpec("source", DataType.VARCHAR, max_length=32),
        FieldSpec("event_type", DataType.VARCHAR, max_length=128),
        FieldSpec("risk_level", DataType.VARCHAR, max_length=16),
        FieldSpec("risk_score", DataType.DOUBLE),
        FieldSpec("summary", DataType.VARCHAR, max_length=4096),
        FieldSpec("reasoning", DataType.VARCHAR, max_length=8192),
        FieldSpec("title", DataType.VARCHAR, max_length=512),
        FieldSpec("event_timestamp", DataType.VARCHAR, max_length=64),
        FieldSpec("key_entities_json", DataType.VARCHAR, max_length=8192),
        FieldSpec("dimension_scores_json", DataType.VARCHAR, max_length=4096),
        FieldSpec("trend_report_json", DataType.VARCHAR, max_length=16384),
        FieldSpec("graph_summary_json", DataType.VARCHAR, max_length=8192),
        FieldSpec("pipeline_message", DataType.VARCHAR, max_length=512),
        FieldSpec(EVENTS_VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=embedding_dim),
    ]
