"""Optional RAGFlow integration for external knowledge retrieval."""

from sentinel.ragflow.client import (
    RagflowApiError,
    RagflowClient,
    RagflowConfig,
    RagflowConfigurationError,
    RagflowRetrievalError,
)
from sentinel.ragflow.context import (
    append_knowledge_context,
    build_event_query,
    format_knowledge_for_prompt,
    knowledge_section_for_prompt,
    ragflow_config_from_settings,
    retrieve_event_knowledge,
)

__all__ = [
    "RagflowApiError",
    "RagflowClient",
    "RagflowConfig",
    "RagflowConfigurationError",
    "RagflowRetrievalError",
    "append_knowledge_context",
    "build_event_query",
    "format_knowledge_for_prompt",
    "knowledge_section_for_prompt",
    "ragflow_config_from_settings",
    "retrieve_event_knowledge",
]
