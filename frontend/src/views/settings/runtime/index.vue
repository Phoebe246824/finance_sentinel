<template>
  <div class="runtime-settings-page">
    <ElAlert
      title="保存后新的分析任务会使用最新配置，正在运行的任务会继续使用原有配置快照。"
      type="info"
      :closable="false"
      show-icon
    />

    <ElSkeleton v-if="loading" :rows="10" animated />

    <ElCard v-else-if="!hasLoaded" shadow="never">
      <div class="empty-state">
        <ElAlert
          :title="loadError || '运行时配置加载失败'"
          type="error"
          :closable="false"
          show-icon
        />
        <ElButton type="primary" @click="load">重试加载</ElButton>
      </div>
    </ElCard>

    <template v-else>
      <ElCard shadow="never">
        <template #header>
          <div class="card-header">
            <span>运行时设置</span>
            <small>最近加载时间：{{ form.meta.updated_at || '-' }}</small>
          </div>
        </template>

        <ElAlert
          v-if="loadError"
          :title="loadError"
          type="warning"
          :closable="false"
          show-icon
          class="section-alert"
        />

        <ElAlert
          v-if="validationErrors.length > 0"
          :title="validationErrors[0]"
          type="warning"
          :closable="false"
          show-icon
          class="section-alert"
        />

        <div class="page-sections">
          <ElCard shadow="never" class="section-card">
            <template #header>
              <div class="section-header">
                <span>模型供应商配置</span>
                <ElButton
                  size="small"
                  :loading="checkingModels"
                  :disabled="saving"
                  @click="runModelChecks"
                >
                  检测模型可用性
                </ElButton>
              </div>
            </template>

            <div class="check-note">检测当前已生效配置；模型检测会发起极小真实请求。</div>
            <div v-if="modelCheckResult" class="check-results">
              <div class="check-results__meta">
                <span>最近检测：{{ modelCheckResult.checked_at }}</span>
              </div>
              <ElDescriptions
                v-for="result in modelCheckResult.results"
                :key="`${result.kind}-${result.name}`"
                :column="2"
                border
                class="check-result"
              >
                <ElDescriptionsItem label="目标">
                  <div class="check-target">
                    <ElTag :type="result.ok ? 'success' : 'danger'" effect="light">
                      {{ result.ok ? '可用' : '不可用' }}
                    </ElTag>
                    <span>{{ result.name }}</span>
                  </div>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="耗时">{{ result.duration_ms }} ms</ElDescriptionsItem>
                <ElDescriptionsItem label="配置目标" :span="2">
                  <span class="check-text">{{ result.target || '-' }}</span>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="详情" :span="2">
                  <span class="check-text">{{ result.detail || '-' }}</span>
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="result.error" label="错误" :span="2">
                  <span class="check-error">{{ result.error }}</span>
                </ElDescriptionsItem>
              </ElDescriptions>
            </div>

            <div class="field-grid">
              <div class="field-item">
                <label>LLM Provider</label>
                <ElInput v-model="form.models.llm.provider" placeholder="openai" />
              </div>
              <div class="field-item">
                <label>LLM Model</label>
                <ElInput v-model="form.models.llm.model" placeholder="gpt-4o" />
              </div>
              <div class="field-item">
                <label>LLM Base URL</label>
                <ElInput
                  v-model="form.models.llm.base_url"
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              <div class="field-item">
                <label>LLM API Key</label>
                <ElInput
                  v-model="form.models.llm.api_key"
                  type="password"
                  show-password
                  :placeholder="secretPlaceholder(form.secrets.llm_api_key)"
                />
              </div>

              <div class="field-item">
                <label>Embedder Model</label>
                <ElInput v-model="form.models.embedder.model" placeholder="BAAI/bge-m3" />
              </div>
              <div class="field-item">
                <label>Embedder API Base</label>
                <ElInput
                  v-model="form.models.embedder.api_base"
                  placeholder="https://api.siliconflow.cn/v1"
                />
              </div>
              <div class="field-item">
                <label>Embedding Dimension</label>
                <ElInputNumber v-model="form.models.embedder.embedding_dim" :min="1" :max="65535" />
              </div>
              <div class="field-item">
                <label>Embedder API Key</label>
                <ElInput
                  v-model="form.models.embedder.api_key"
                  type="password"
                  show-password
                  :placeholder="secretPlaceholder(form.secrets.embedder_api_key)"
                />
              </div>

              <div class="field-item">
                <label>Reranker Model</label>
                <ElInput
                  v-model="form.models.reranker.model"
                  placeholder="BAAI/bge-reranker-v2-m3"
                />
              </div>
              <div class="field-item">
                <label>Reranker Base URL</label>
                <ElInput
                  v-model="form.models.reranker.base_url"
                  placeholder="https://api.siliconflow.cn/v1"
                />
              </div>
              <div class="field-item field-item--full">
                <label>Reranker API Key</label>
                <ElInput
                  v-model="form.models.reranker.api_key"
                  type="password"
                  show-password
                  :placeholder="secretPlaceholder(form.secrets.reranker_api_key)"
                />
              </div>
            </div>
          </ElCard>

          <ElCard shadow="never" class="section-card">
            <template #header>
              <div class="section-header">
                <span>依赖服务配置</span>
                <ElButton
                  size="small"
                  :loading="checkingServices"
                  :disabled="saving"
                  @click="runServiceChecks"
                >
                  检测服务可用性
                </ElButton>
              </div>
            </template>

            <div class="check-note">检测当前已生效配置；服务检测只执行只读连接探测。</div>
            <div v-if="serviceCheckResult" class="check-results">
              <div class="check-results__meta">
                <span>最近检测：{{ serviceCheckResult.checked_at }}</span>
              </div>
              <ElDescriptions
                v-for="result in serviceCheckResult.results"
                :key="`${result.kind}-${result.name}`"
                :column="2"
                border
                class="check-result"
              >
                <ElDescriptionsItem label="目标">
                  <div class="check-target">
                    <ElTag :type="result.ok ? 'success' : 'danger'" effect="light">
                      {{ result.ok ? '可用' : '不可用' }}
                    </ElTag>
                    <span>{{ result.name }}</span>
                  </div>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="耗时">{{ result.duration_ms }} ms</ElDescriptionsItem>
                <ElDescriptionsItem label="配置目标" :span="2">
                  <span class="check-text">{{ result.target || '-' }}</span>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="详情" :span="2">
                  <span class="check-text">{{ result.detail || '-' }}</span>
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="result.error" label="错误" :span="2">
                  <span class="check-error">{{ result.error }}</span>
                </ElDescriptionsItem>
              </ElDescriptions>
            </div>

            <div class="field-grid">
              <div class="field-item">
                <label>Neo4j URI</label>
                <ElInput v-model="form.services.neo4j.uri" placeholder="bolt://localhost:7687" />
              </div>
              <div class="field-item">
                <label>Neo4j User</label>
                <ElInput v-model="form.services.neo4j.user" placeholder="neo4j" />
              </div>
              <div class="field-item">
                <label>Neo4j Database</label>
                <ElInput v-model="form.services.neo4j.database" placeholder="neo4j" />
              </div>
              <div class="field-item">
                <label>Neo4j Password</label>
                <ElInput
                  v-model="form.services.neo4j.password"
                  type="password"
                  show-password
                  :placeholder="secretPlaceholder(form.secrets.neo4j_password)"
                />
              </div>

              <div class="field-item">
                <label>Milvus URI</label>
                <ElInput v-model="form.services.milvus.uri" placeholder="http://localhost:19530" />
              </div>
              <div class="field-item">
                <label>Milvus Collection</label>
                <ElInput
                  v-model="form.services.milvus.input_events_collection"
                  placeholder="input_events"
                />
              </div>
              <div class="field-item">
                <label>Milvus Token</label>
                <ElInput
                  v-model="form.services.milvus.token"
                  type="password"
                  show-password
                  :placeholder="secretPlaceholder(form.secrets.milvus_token)"
                />
              </div>
              <div class="field-item field-item--switch">
                <label>Graphiti Dry Run</label>
                <ElSwitch v-model="form.services.graphiti.dry_run" />
              </div>
            </div>
          </ElCard>

          <ElCard shadow="never" class="section-card">
            <template #header>
              <span>运行时参数</span>
            </template>

            <div class="field-grid field-grid--four">
              <div class="field-item">
                <label>搜索返回数</label>
                <ElInputNumber v-model="form.runtime.search.num_results" :min="1" :max="500" />
              </div>
              <div class="field-item">
                <label>风险搜索返回数</label>
                <ElInputNumber v-model="form.runtime.search.risk_num_results" :min="1" :max="500" />
              </div>
              <div class="field-item">
                <label>搜索最低分</label>
                <ElInputNumber
                  v-model="form.runtime.search.min_score"
                  :min="0"
                  :max="1"
                  :step="0.01"
                />
              </div>
              <div class="field-item">
                <label>风险阈值</label>
                <ElInputNumber
                  v-model="form.runtime.risk.threshold"
                  :min="0"
                  :max="1"
                  :step="0.01"
                />
              </div>
              <div class="field-item">
                <label>KV TTL 天数</label>
                <ElInputNumber v-model="form.runtime.stash.kv_ttl_days" :min="1" :max="3650" />
              </div>
              <div class="field-item">
                <label>语义召回 Top K</label>
                <ElInputNumber v-model="form.runtime.stash.semantic_top_k" :min="1" :max="500" />
              </div>
              <div class="field-item">
                <label>Rerank 最低分</label>
                <ElInputNumber
                  v-model="form.runtime.stash.rerank_min_score"
                  :min="0"
                  :max="1"
                  :step="0.01"
                />
              </div>
              <div class="field-item field-item--switch">
                <label>启用回捞 Rerank</label>
                <ElSwitch v-model="form.runtime.stash.rerank_enabled" />
              </div>
              <div class="field-item">
                <label>批量构图每人上限</label>
                <ElInputNumber v-model="form.runtime.batch.max_per_person" :min="1" :max="500" />
              </div>
              <div class="field-item">
                <label>事件相似度阈值</label>
                <ElInputNumber
                  v-model="form.runtime.blacklist.event_similarity_threshold"
                  :min="0"
                  :max="1"
                  :step="0.01"
                />
              </div>
              <div class="field-item">
                <label>人员命中次数阈值</label>
                <ElInputNumber
                  v-model="form.runtime.blacklist.person_min_hits"
                  :min="1"
                  :max="100"
                />
              </div>
            </div>
          </ElCard>
        </div>

        <div class="actions">
          <ElButton @click="resetForm">重置未保存改动</ElButton>
          <ElButton type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
            保存并应用
          </ElButton>
        </div>
      </ElCard>
    </template>
  </div>
</template>

<script setup lang="ts">
  import {
    checkRuntimeModels,
    checkRuntimeServices,
    fetchRuntimeSettings,
    saveRuntimeSettings
  } from '@/api/sentinel/settings'
  import type {
    RuntimeAvailabilityCheckResponse,
    RuntimeSettingsResponse,
    RuntimeSettingsUpdatePayload,
    SecretFieldState
  } from '@/api/sentinel/types'

  defineOptions({ name: 'RuntimeSettingsPage' })

  type RuntimeSettingsForm = RuntimeSettingsResponse & RuntimeSettingsUpdatePayload

  const loading = ref(false)
  const saving = ref(false)
  const checkingServices = ref(false)
  const checkingModels = ref(false)
  const loadError = ref('')
  const original = ref<RuntimeSettingsResponse | null>(null)
  const serviceCheckResult = ref<RuntimeAvailabilityCheckResponse | null>(null)
  const modelCheckResult = ref<RuntimeAvailabilityCheckResponse | null>(null)

  const createEmptyForm = (): RuntimeSettingsForm => ({
    models: {
      llm: { provider: '', model: '', base_url: '', api_key: '' },
      embedder: { model: '', api_base: '', api_key: '', embedding_dim: 1024 },
      reranker: { model: '', base_url: '', api_key: '' }
    },
    services: {
      neo4j: { uri: '', user: '', database: '', password: '' },
      milvus: { uri: '', input_events_collection: '', token: '' },
      graphiti: { dry_run: false }
    },
    runtime: {
      search: { num_results: 10, risk_num_results: 20, min_score: 0 },
      risk: { threshold: 0.7 },
      stash: { kv_ttl_days: 90, semantic_top_k: 10, rerank_min_score: 0.7, rerank_enabled: true },
      batch: { max_per_person: 20 },
      blacklist: { event_similarity_threshold: 0.5, person_min_hits: 1 }
    },
    secrets: {
      neo4j_password: { configured: false, masked_hint: null },
      llm_api_key: { configured: false, masked_hint: null },
      embedder_api_key: { configured: false, masked_hint: null },
      reranker_api_key: { configured: false, masked_hint: null },
      milvus_token: { configured: false, masked_hint: null }
    },
    meta: { updated_at: '' }
  })

  const form = reactive(createEmptyForm())

  const applyResponse = (payload: RuntimeSettingsResponse) => {
    original.value = JSON.parse(JSON.stringify(payload)) as RuntimeSettingsResponse
    Object.assign(form, {
      models: {
        llm: { ...payload.models.llm, api_key: '' },
        embedder: { ...payload.models.embedder, api_key: '' },
        reranker: { ...payload.models.reranker, api_key: '' }
      },
      services: {
        neo4j: { ...payload.services.neo4j, password: '' },
        milvus: { ...payload.services.milvus, token: '' },
        graphiti: { ...payload.services.graphiti }
      },
      runtime: JSON.parse(JSON.stringify(payload.runtime)),
      secrets: payload.secrets,
      meta: payload.meta
    })
  }

  const clearCheckResults = () => {
    serviceCheckResult.value = null
    modelCheckResult.value = null
  }

  const load = async () => {
    loading.value = true
    try {
      loadError.value = ''
      applyResponse(await fetchRuntimeSettings())
      clearCheckResults()
    } catch (error) {
      loadError.value = error instanceof Error ? error.message : '运行时配置加载失败'
    } finally {
      loading.value = false
    }
  }

  const hasLoaded = computed(() => original.value !== null)

  const secretPlaceholder = (state: SecretFieldState) => {
    if (!state.configured) {
      return '未配置，输入后保存'
    }
    return `已配置 ${state.masked_hint || ''}，留空表示保持原值`
  }

  const buildPayload = (): RuntimeSettingsUpdatePayload => ({
    models: {
      llm: {
        provider: form.models.llm.provider.trim(),
        model: form.models.llm.model.trim(),
        base_url: form.models.llm.base_url.trim(),
        api_key: form.models.llm.api_key
      },
      embedder: {
        model: form.models.embedder.model.trim(),
        api_base: form.models.embedder.api_base.trim(),
        api_key: form.models.embedder.api_key,
        embedding_dim: form.models.embedder.embedding_dim
      },
      reranker: {
        model: form.models.reranker.model.trim(),
        base_url: form.models.reranker.base_url.trim(),
        api_key: form.models.reranker.api_key
      }
    },
    services: {
      neo4j: {
        uri: form.services.neo4j.uri.trim(),
        user: form.services.neo4j.user.trim(),
        password: form.services.neo4j.password,
        database: form.services.neo4j.database.trim()
      },
      milvus: {
        uri: form.services.milvus.uri.trim(),
        input_events_collection: form.services.milvus.input_events_collection.trim(),
        token: form.services.milvus.token
      },
      graphiti: { ...form.services.graphiti }
    },
    runtime: JSON.parse(JSON.stringify(form.runtime))
  })

  const isHttpUrl = (value: string) => /^https?:\/\/.+/.test(value.trim())
  const isNeo4jUri = (value: string) => /^(bolt|neo4j)(\+s|\+ssc)?:\/\/.+/.test(value.trim())
  const isMilvusCollection = (value: string) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(value.trim())

  const validationErrors = computed(() => {
    const errors: string[] = []
    const requiredFields: Array<[string, string]> = [
      ['LLM Provider', form.models.llm.provider],
      ['LLM Model', form.models.llm.model],
      ['LLM Base URL', form.models.llm.base_url],
      ['Embedder Model', form.models.embedder.model],
      ['Embedder API Base', form.models.embedder.api_base],
      ['Reranker Model', form.models.reranker.model],
      ['Reranker Base URL', form.models.reranker.base_url],
      ['Neo4j URI', form.services.neo4j.uri],
      ['Neo4j User', form.services.neo4j.user],
      ['Neo4j Database', form.services.neo4j.database],
      ['Milvus URI', form.services.milvus.uri],
      ['Milvus Collection', form.services.milvus.input_events_collection]
    ]

    for (const [label, value] of requiredFields) {
      if (!value.trim()) {
        errors.push(`${label} 不能为空`)
      }
    }

    const httpUrlFields: Array<[string, string]> = [
      ['LLM Base URL', form.models.llm.base_url],
      ['Embedder API Base', form.models.embedder.api_base],
      ['Reranker Base URL', form.models.reranker.base_url]
    ]

    for (const [label, value] of httpUrlFields) {
      if (value.trim() && !isHttpUrl(value)) {
        errors.push(`${label} 必须以 http:// 或 https:// 开头`)
      }
    }

    if (form.services.neo4j.uri.trim() && !isNeo4jUri(form.services.neo4j.uri)) {
      errors.push('Neo4j URI 必须以 bolt:// 或 neo4j:// 开头')
    }

    if (
      form.services.milvus.input_events_collection.trim() &&
      !isMilvusCollection(form.services.milvus.input_events_collection)
    ) {
      errors.push('Milvus Collection 只能包含字母、数字、下划线，且必须以字母或下划线开头')
    }

    const numericFields: Array<[string, number | null | undefined]> = [
      ['Embedding Dimension', form.models.embedder.embedding_dim],
      ['搜索返回数', form.runtime.search.num_results],
      ['风险搜索返回数', form.runtime.search.risk_num_results],
      ['搜索最低分', form.runtime.search.min_score],
      ['风险阈值', form.runtime.risk.threshold],
      ['KV TTL 天数', form.runtime.stash.kv_ttl_days],
      ['语义召回 Top K', form.runtime.stash.semantic_top_k],
      ['Rerank 最低分', form.runtime.stash.rerank_min_score],
      ['批量构图每人上限', form.runtime.batch.max_per_person],
      ['事件相似度阈值', form.runtime.blacklist.event_similarity_threshold],
      ['人员命中次数阈值', form.runtime.blacklist.person_min_hits]
    ]

    for (const [label, value] of numericFields) {
      if (value === null || value === undefined || Number.isNaN(value)) {
        errors.push(`${label} 不能为空`)
      }
    }

    return errors
  })

  const canSubmit = computed(
    () => hasLoaded.value && !saving.value && validationErrors.value.length === 0
  )

  const resetForm = () => {
    if (!original.value) return
    loadError.value = ''
    applyResponse(original.value)
    clearCheckResults()
  }

  const runServiceChecks = async () => {
    checkingServices.value = true
    try {
      serviceCheckResult.value = await checkRuntimeServices()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '服务可用性检测失败')
    } finally {
      checkingServices.value = false
    }
  }

  const runModelChecks = async () => {
    checkingModels.value = true
    try {
      modelCheckResult.value = await checkRuntimeModels()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '模型可用性检测失败')
    } finally {
      checkingModels.value = false
    }
  }

  const submit = async () => {
    if (!canSubmit.value) {
      if (validationErrors.value.length > 0) {
        ElMessage.error(validationErrors.value[0])
      }
      return
    }
    saving.value = true
    try {
      const response = await saveRuntimeSettings(buildPayload())
      loadError.value = ''
      applyResponse(response)
      clearCheckResults()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      saving.value = false
    }
  }

  onMounted(load)
</script>

<style scoped>
  .runtime-settings-page {
    display: grid;
    gap: 16px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .card-header small {
    color: var(--el-text-color-secondary);
  }

  .page-sections {
    display: grid;
    gap: 16px;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .section-alert {
    margin-bottom: 16px;
  }

  .empty-state {
    display: grid;
    gap: 16px;
    justify-items: start;
  }

  .field-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
  }

  .check-note {
    margin-bottom: 12px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.5;
  }

  .check-results {
    display: grid;
    gap: 10px;
    margin-bottom: 16px;
  }

  .check-results__meta {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .check-result {
    width: 100%;
  }

  .check-target {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .check-text,
  .check-error {
    overflow-wrap: anywhere;
  }

  .check-error {
    color: var(--el-color-danger);
  }

  .field-grid--four {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .field-item {
    display: grid;
    gap: 8px;
  }

  .field-item label {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .field-item--full {
    grid-column: 1 / -1;
  }

  .field-item--switch {
    align-content: end;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 20px;
  }

  @media (max-width: 1080px) {
    .field-grid,
    .field-grid--four {
      grid-template-columns: 1fr;
    }

    .section-header {
      align-items: flex-start;
      flex-direction: column;
    }
  }
</style>
