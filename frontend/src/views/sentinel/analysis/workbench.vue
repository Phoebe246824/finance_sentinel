<template>
  <div class="analysis-page">
    <ElRow :gutter="16">
      <ElCol :xs="24" :lg="10">
        <ElCard shadow="never">
          <template #header>
            <span>事件输入</span>
          </template>
          <ElInput
            v-model="text"
            type="textarea"
            :rows="12"
            maxlength="2000"
            show-word-limit
            resize="none"
            placeholder="粘贴待分析的舆情、交易、行为或告警文本，例如：某主体疑似通过多账户拆分转账，金额接近人工复核阈值。"
          />
          <div class="actions">
            <ElButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
              开始分析
            </ElButton>
          </div>
        </ElCard>

        <PipelineProgressCard :task="task" class="progress-card" />
      </ElCol>

      <ElCol :xs="24" :lg="14">
        <ElEmpty v-if="!event" description="暂无分析结果" />
        <ElCard v-else shadow="never" class="result-card">
          <template #header>
            <div class="result-head">
              <span>{{ event.event_id }}</span>
              <RiskBadge :level="event.risk_level" />
            </div>
          </template>

          <ElDescriptions :column="2" border>
            <ElDescriptionsItem label="事件类型">{{ event.event_type }}</ElDescriptionsItem>
            <ElDescriptionsItem label="风险得分">
              {{ event.risk_level === 'unassessed' ? '-' : Math.round(event.risk_score * 100) }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="来源">{{ event.source }}</ElDescriptionsItem>
            <ElDescriptionsItem label="时间">{{ formatDate(event.timestamp) }}</ElDescriptionsItem>
          </ElDescriptions>

          <section class="result-section">
            <h3>摘要</h3>
            <p>{{ event.summary }}</p>
          </section>

          <section class="result-section">
            <h3>判定依据</h3>
            <p>{{ event.reasoning }}</p>
          </section>

          <section class="result-section">
            <h3>维度评分</h3>
            <div class="score-list">
              <div v-for="item in dimensionScores" :key="item.name" class="score-row">
                <span class="score-name" :title="item.name">{{ item.name }}</span>
                <ElProgress
                  class="score-progress"
                  :percentage="item.value"
                  :stroke-width="8"
                  :show-text="false"
                />
                <span class="score-value">{{ item.value }}%</span>
              </div>
            </div>
          </section>

          <section class="result-section">
            <div class="section-head">
              <h3>图谱构建</h3>
              <span v-if="eventGraph" class="section-meta">
                {{ eventGraph.nodes.length }} 个节点 / {{ eventGraph.edges.length }} 条边
              </span>
            </div>

            <ElSkeleton v-if="graphLoading" :rows="4" animated />
            <template v-else>
              <ElAlert
                v-if="graphErrorMessage"
                :title="graphErrorMessage"
                type="error"
                :closable="false"
                show-icon
              />
              <SentinelGraphViewer
                v-else-if="eventGraph && eventGraph.nodes.length > 0"
                :graph="eventGraph"
                class="analysis-graph"
              />
              <ElEmpty v-else description="暂无事件图谱数据" />

              <div v-if="hasGraphSummary" class="graph-metrics">
                <div v-for="item in graphMetrics" :key="item.label" class="graph-metric">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </template>
          </section>

          <section class="result-section">
            <h3>趋势预测</h3>
            <ElAlert
              :title="event.trend_report.severity_name"
              :description="event.trend_report.trend_prediction"
              type="warning"
              :closable="false"
              show-icon
            />
            <p class="intent">{{ event.trend_report.intent_analysis }}</p>
          </section>
        </ElCard>
      </ElCol>
    </ElRow>
  </div>
</template>

<script setup lang="ts">
  import { fetchEventGraph } from '@/api/sentinel/graph'
  import { analyzeText } from '@/api/sentinel/tasks'
  import type { AnalysisTask, PersonGraph, SentinelEvent } from '@/api/sentinel/types'

  defineOptions({ name: 'SentinelAnalysisWorkbench' })

  const text = ref('')
  const task = ref<AnalysisTask | null>(null)
  const event = ref<SentinelEvent | null>(null)
  const eventGraph = ref<PersonGraph | null>(null)
  const graphLoading = ref(false)
  const graphErrorMessage = ref('')
  const submitting = ref(false)
  let runVersion = 0
  let activeController: AbortController | null = null

  const canSubmit = computed(() => text.value.trim().length > 0 && !submitting.value)

  const formatDate = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }

  const dimensionScores = computed(() =>
    Object.entries(event.value?.dimension_scores || {}).map(([name, score]) => ({
      name,
      value: Math.round(score * 100)
    }))
  )

  const graphSummary = computed(() => event.value?.graph_summary)

  const graphMetrics = computed(() => {
    const summary = graphSummary.value
    return [
      { label: '实体节点', value: summary?.entities_extracted ?? 0 },
      { label: '关系边', value: summary?.relations_created ?? 0 },
      { label: '回捞候选', value: summary?.fetched_count ?? 0 },
      { label: '批量补图', value: summary?.batched_count ?? 0 }
    ]
  })

  const hasGraphSummary = computed(() => graphMetrics.value.some((item) => item.value > 0))

  const loadEventGraph = async (eventId: string, version: number, signal: AbortSignal) => {
    graphLoading.value = true
    graphErrorMessage.value = ''
    try {
      const graph = await fetchEventGraph(eventId, signal)
      if (version === runVersion && !signal.aborted) {
        eventGraph.value = graph
      }
    } catch (error) {
      if (version === runVersion && !signal.aborted) {
        eventGraph.value = null
        graphErrorMessage.value =
          error instanceof Error ? error.message : '事件图谱加载失败，请稍后重试'
      }
    } finally {
      if (version === runVersion) {
        graphLoading.value = false
      }
    }
  }

  const submit = async () => {
    if (!canSubmit.value) return
    const currentVersion = ++runVersion
    activeController?.abort()
    const controller = new AbortController()
    activeController = controller
    submitting.value = true
    task.value = null
    event.value = null
    eventGraph.value = null
    graphErrorMessage.value = ''
    graphLoading.value = false
    try {
      const nextEvent = await analyzeText(
        text.value.trim(),
        (current) => {
          if (currentVersion === runVersion && !controller.signal.aborted) {
            task.value = current
          }
        },
        controller.signal
      )
      if (currentVersion === runVersion && !controller.signal.aborted) {
        event.value = nextEvent
        await loadEventGraph(nextEvent.event_id, currentVersion, controller.signal)
      }
    } catch (error) {
      if (currentVersion === runVersion && !controller.signal.aborted) {
        ElMessage.error(error instanceof Error ? error.message : '分析任务失败')
      }
    } finally {
      if (currentVersion === runVersion) {
        submitting.value = false
        activeController = null
      }
    }
  }

  onBeforeUnmount(() => {
    runVersion += 1
    activeController?.abort()
    activeController = null
  })
</script>

<style scoped>
  .analysis-page {
    display: grid;
    gap: 16px;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 16px;
  }

  .progress-card {
    margin-top: 16px;
  }

  .result-card {
    min-height: 100%;
  }

  .result-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .result-section {
    margin-top: 20px;
  }

  .result-section h3 {
    margin: 0 0 10px;
    font-size: 15px;
    font-weight: 600;
  }

  .section-head {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }

  .section-head h3 {
    margin-bottom: 0;
  }

  .section-meta {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    white-space: nowrap;
  }

  .result-section p {
    margin: 0;
    color: var(--el-text-color-regular);
    line-height: 1.7;
  }

  .score-list {
    display: grid;
    gap: 12px;
  }

  .score-row {
    display: grid;
    grid-template-columns: minmax(138px, 0.44fr) minmax(120px, 1fr) 42px;
    align-items: center;
    gap: 10px;
  }

  .score-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--el-text-color-regular);
  }

  .score-progress {
    min-width: 0;
  }

  .score-value {
    justify-self: end;
    color: var(--el-text-color-secondary);
    font-variant-numeric: tabular-nums;
  }

  .analysis-graph {
    min-height: 560px;
  }

  .graph-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-top: 12px;
  }

  .graph-metric {
    display: grid;
    gap: 4px;
    padding: 10px;
    background: var(--el-fill-color-lighter);
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
  }

  .graph-metric span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  .graph-metric strong {
    font-size: 18px;
  }

  .intent {
    margin-top: 12px !important;
  }

  @media (max-width: 768px) {
    .graph-metrics {
      grid-template-columns: 1fr;
    }
  }
</style>
