export type RiskLevel = 'high' | 'medium' | 'low' | 'unassessed'

export interface KeyEntity {
  name: string
  type: string
}

export interface TrendReport {
  category_name: string
  category_confidence: number
  severity_name: string
  severity_confidence: number
  intent_analysis: string
  trend_prediction: string
}

export interface GraphSummary {
  success: boolean | null
  entities_extracted: number
  relations_created: number
  group_id: string
  fetched_count: number
  eligible_count: number
  batched_count: number
  skipped_irrelevant_count: number
  skipped_existing_count: number
  raw: Record<string, unknown>
}

export interface SentinelEvent {
  event_id: string
  analysis_status: string
  source: string
  event_type: string
  risk_level: RiskLevel
  risk_score: number
  summary: string
  raw_content: string
  timestamp: string
  key_entities: KeyEntity[]
  reasoning: string
  dimension_scores: Record<string, number>
  trend_report: TrendReport
  graph_summary: GraphSummary
}

export interface PaginatedEvents {
  items: SentinelEvent[]
  total: number
  page: number
  page_size: number
  current: number
  size: number
  truncated: boolean
}

export interface DashboardOverview {
  stats: {
    total_events: number
    high_risk_count: number
    medium_risk_count: number
    low_risk_count: number
    unassessed_count: number
    avg_processing_latency_ms: number | null
    events_per_minute: number | null
    graph_node_count: number | null
    graph_edge_count: number | null
    uptime_hours: number | null
    runtime_metrics_available: boolean
    graph_metrics_available: boolean
    data_truncated: boolean
  }
  risk_distribution: Partial<Record<RiskLevel, number>>
  source_distribution: Record<string, number>
  recent_events: SentinelEvent[]
  updated_at: string
  truncated: boolean
}

export interface AnalysisTask {
  task_id: string
  event_id?: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
  error_message?: string
  stage_key?: string
  stage_label?: string
  stage_index?: number
  stage_total?: number
  stage_detail?: string
  stage_updated_at?: string
}

export interface GraphNode {
  id: string
  label: string
  type: string
  risk_level?: RiskLevel
  labels?: string[]
  properties?: Record<string, unknown>
}

export interface GraphEdge {
  id?: string
  source: string
  target: string
  label?: string
  type?: string
  properties?: Record<string, unknown>
}

export interface PersonGraph {
  center_person_id: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  source?: string
}

export interface SecretFieldState {
  configured: boolean
  masked_hint: string | null
}

export interface RuntimeAvailabilityCheckResult {
  name: string
  kind: 'service' | 'model'
  ok: boolean
  target: string
  detail: string
  error: string | null
  duration_ms: number
}

export interface RuntimeAvailabilityCheckResponse {
  checked_at: string
  results: RuntimeAvailabilityCheckResult[]
}

export interface RuntimeSettingsResponse {
  models: {
    llm: {
      provider: string
      model: string
      base_url: string
    }
    embedder: {
      model: string
      api_base: string
      embedding_dim: number
    }
    reranker: {
      model: string
      base_url: string
    }
  }
  services: {
    neo4j: {
      uri: string
      user: string
      database: string
    }
    milvus: {
      uri: string
      input_events_collection: string
    }
    graphiti: {
      dry_run: boolean
    }
  }
  runtime: {
    search: {
      num_results: number
      risk_num_results: number
      min_score: number
    }
    risk: {
      threshold: number
    }
    stash: {
      kv_ttl_days: number
      semantic_top_k: number
      rerank_min_score: number
      rerank_enabled: boolean
    }
    batch: {
      max_per_person: number
    }
    blacklist: {
      event_similarity_threshold: number
      person_min_hits: number
    }
  }
  secrets: {
    neo4j_password: SecretFieldState
    llm_api_key: SecretFieldState
    embedder_api_key: SecretFieldState
    reranker_api_key: SecretFieldState
    milvus_token: SecretFieldState
  }
  meta: {
    updated_at: string
  }
}

export interface RuntimeSettingsUpdatePayload {
  models: {
    llm: {
      provider: string
      model: string
      base_url: string
      api_key: string
    }
    embedder: {
      model: string
      api_base: string
      api_key: string
      embedding_dim: number
    }
    reranker: {
      model: string
      base_url: string
      api_key: string
    }
  }
  services: {
    neo4j: {
      uri: string
      user: string
      password: string
      database: string
    }
    milvus: {
      uri: string
      token: string
      input_events_collection: string
    }
    graphiti: {
      dry_run: boolean
    }
  }
  runtime: {
    search: {
      num_results: number
      risk_num_results: number
      min_score: number
    }
    risk: {
      threshold: number
    }
    stash: {
      kv_ttl_days: number
      semantic_top_k: number
      rerank_min_score: number
      rerank_enabled: boolean
    }
    batch: {
      max_per_person: number
    }
    blacklist: {
      event_similarity_threshold: number
      person_min_hits: number
    }
  }
}

export interface BlacklistPersonItem {
  person_id: string
  summary: string
  description: string
  hit_count: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface BlacklistKeywordItem {
  keyword_id: string
  keyword: string
  summary: string
  description: string
  hit_count: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface BlacklistEventSampleItem {
  sample_id: string
  summary: string
  description: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface PaginatedBlacklist<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  current: number
  size: number
}

export interface BlacklistSearchParams {
  current?: number
  size?: number
  page?: number
  page_size?: number
  keyword?: string
  enabled?: boolean
}

export interface BlacklistBatchDeleteItem {
  key: string
  expected_updated_at: string
}

export interface BlacklistPersonBatchCreateItem {
  person_id: string
  summary: string
  description: string
  enabled: boolean
}

export interface BlacklistPersonBatchUpdateItem extends BlacklistPersonBatchCreateItem {
  old_key: string
  expected_updated_at: string
}

export interface BlacklistKeywordBatchCreateItem {
  keyword: string
  summary: string
  description: string
  enabled: boolean
}

export interface BlacklistKeywordBatchUpdateItem extends BlacklistKeywordBatchCreateItem {
  old_key: string
  expected_updated_at: string
}

export interface BlacklistBatchPayload<TCreate, TUpdate> {
  created: TCreate[]
  updated: TUpdate[]
  deleted: BlacklistBatchDeleteItem[]
}

export type BlacklistPersonBatchPayload = BlacklistBatchPayload<
  BlacklistPersonBatchCreateItem,
  BlacklistPersonBatchUpdateItem
>

export type BlacklistKeywordBatchPayload = BlacklistBatchPayload<
  BlacklistKeywordBatchCreateItem,
  BlacklistKeywordBatchUpdateItem
>

export interface BlacklistEventSavePayload {
  sample_id: string
  summary: string
  description: string
  enabled: boolean
  expected_updated_at?: string
}

export interface BlacklistEventDeletePayload {
  expected_updated_at: string
}

export interface BlacklistEventMutationResult {
  item: BlacklistEventSampleItem
  embedding_status: 'computed' | 'reused' | 'fallback'
}
