<template>
  <div class="sentinel-page">
    <ElSkeleton v-if="loading" :rows="8" animated />
    <ElAlert
      v-else-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
    />
    <template v-else>
      <ElAlert
        v-if="overview?.truncated"
        title="数据超过当前查询上限，当前列表和统计为截断结果"
        type="warning"
        show-icon
        :closable="false"
      />
      <section class="metrics-grid">
        <ElCard v-for="item in metricCards" :key="item.label" shadow="never" class="metric-card">
          <span class="metric-label">{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.hint }}</small>
        </ElCard>
      </section>

      <ElRow :gutter="16">
        <ElCol :xs="24" :lg="12">
          <ElCard shadow="never" class="chart-panel">
            <template #header>
              <span>风险分布</span>
            </template>
            <div class="distribution-list">
              <div v-for="item in riskItems" :key="item.level" class="distribution-row">
                <RiskBadge :level="item.level" />
                <ElProgress
                  :percentage="item.percentage"
                  :stroke-width="10"
                  :show-text="false"
                  :color="item.color"
                />
                <strong>{{ item.count }}</strong>
              </div>
            </div>
          </ElCard>
        </ElCol>
        <ElCol :xs="24" :lg="12">
          <ElCard shadow="never" class="chart-panel">
            <template #header>
              <span>来源分布</span>
            </template>
            <div class="source-grid">
              <div v-for="item in sourceItems" :key="item.source" class="source-item">
                <span>{{ sourceLabel(item.source) }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
          </ElCard>
        </ElCol>
      </ElRow>

      <ElCard shadow="never" class="recent-card">
        <template #header>
          <div class="card-head">
            <span>最近事件</span>
            <small>更新于 {{ formatDate(overview?.updated_at) }}</small>
          </div>
        </template>
        <ArtTable
          :data="overview?.recent_events || []"
          :columns="columns"
          :show-table-header="false"
        />
      </ElCard>
    </template>
  </div>
</template>

<script setup lang="ts">
  import { ElButton } from 'element-plus'
  import { useRouter } from 'vue-router'
  import { fetchDashboardOverview } from '@/api/sentinel/dashboard'
  import type { DashboardOverview, RiskLevel, SentinelEvent } from '@/api/sentinel/types'
  import type { ColumnOption } from '@/types/component'
  import RiskBadge from '@/components/sentinel/RiskBadge.vue'

  defineOptions({ name: 'SentinelDashboardOverview' })

  const router = useRouter()
  const loading = ref(false)
  const overview = ref<DashboardOverview>()
  const errorMessage = ref('')

  type AssessedRiskLevel = Exclude<RiskLevel, 'unassessed'>

  const riskOrder: AssessedRiskLevel[] = ['high', 'medium', 'low']
  const riskColors: Record<AssessedRiskLevel, string> = {
    high: 'var(--el-color-danger)',
    medium: 'var(--el-color-warning)',
    low: 'var(--el-color-success)'
  }

  const sourceNames: Record<string, string> = {
    transaction: '交易监测',
    behavior: '行为画像',
    news: '公开舆情'
  }

  const formatDate = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }

  const sourceLabel = (value: string) => sourceNames[value] || value

  const formatNumber = (value?: number | null, digits = 0) => {
    if (value === undefined || value === null) return '-'
    return Number(value).toFixed(digits)
  }

  const formatLatency = (value?: number | null) => {
    if (value === undefined || value === null) return '-'
    return `${formatNumber(value)} ms`
  }

  const formatGraphSize = (nodes?: number | null, edges?: number | null, available = true) => {
    if (
      !available ||
      nodes === undefined ||
      nodes === null ||
      edges === undefined ||
      edges === null
    ) {
      return '-'
    }
    return `${formatNumber(nodes)} / ${formatNumber(edges)}`
  }

  const metricCards = computed(() => {
    const stats = overview.value?.stats
    const runtimeMetricsAvailable = stats?.runtime_metrics_available ?? true
    const graphMetricsAvailable = stats?.graph_metrics_available ?? true
    const unassessedCount = stats?.unassessed_count ?? 0
    return [
      {
        label: '事件总量',
        value: formatNumber(stats?.total_events),
        hint:
          unassessedCount > 0
            ? `未评估 ${formatNumber(unassessedCount)} 件`
            : runtimeMetricsAvailable
              ? `${formatNumber(stats?.events_per_minute, 1)} 件/分钟`
              : '速率不可用'
      },
      {
        label: '高风险事件',
        value: formatNumber(stats?.high_risk_count),
        hint: '需优先复核'
      },
      {
        label: '平均处理耗时',
        value: formatLatency(stats?.avg_processing_latency_ms),
        hint: runtimeMetricsAvailable
          ? `已运行 ${formatNumber(stats?.uptime_hours, 1)} 小时`
          : '运行指标不可用'
      },
      {
        label: '图谱规模',
        value: formatGraphSize(
          stats?.graph_node_count,
          stats?.graph_edge_count,
          graphMetricsAvailable
        ),
        hint: graphMetricsAvailable ? '节点 / 边' : '图谱指标不可用'
      }
    ]
  })

  const riskItems = computed(() => {
    const distribution = overview.value?.risk_distribution || { high: 0, medium: 0, low: 0 }
    const total = Math.max(
      1,
      riskOrder.reduce((sum, level) => sum + (distribution[level] ?? 0), 0)
    )
    const countFor = (level: AssessedRiskLevel) => distribution[level] ?? 0
    return riskOrder.map((level) => ({
      level,
      count: countFor(level),
      color: riskColors[level],
      percentage: Math.round((countFor(level) / total) * 100)
    }))
  })

  const sourceItems = computed(() =>
    Object.entries(overview.value?.source_distribution || {}).map(([source, count]) => ({
      source,
      count
    }))
  )

  const columns: ColumnOption<SentinelEvent>[] = [
    { prop: 'event_id', label: '事件 ID', minWidth: 140 },
    { prop: 'summary', label: '摘要', minWidth: 320 },
    {
      prop: 'risk_level',
      label: '风险',
      width: 110,
      formatter: (row) => h(RiskBadge, { level: row.risk_level })
    },
    {
      prop: 'source',
      label: '来源',
      width: 120,
      formatter: (row) => sourceLabel(row.source)
    },
    {
      prop: 'timestamp',
      label: '时间',
      width: 190,
      formatter: (row) => formatDate(row.timestamp)
    },
    {
      prop: 'operation',
      label: '操作',
      width: 100,
      fixed: 'right',
      formatter: (row) =>
        h(
          ElButton,
          {
            link: true,
            type: 'primary',
            onClick: () =>
              router.push({ name: 'SentinelEventDetail', params: { eventId: row.event_id } })
          },
          () => '详情'
        )
    }
  ]

  const loadOverview = async () => {
    loading.value = true
    errorMessage.value = ''
    try {
      overview.value = await fetchDashboardOverview()
    } catch (error) {
      overview.value = undefined
      errorMessage.value = error instanceof Error ? error.message : '看板数据加载失败'
    } finally {
      loading.value = false
    }
  }

  onMounted(loadOverview)
</script>

<style scoped>
  .sentinel-page {
    display: grid;
    gap: 16px;
  }

  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }

  .metric-card :deep(.el-card__body) {
    display: grid;
    gap: 8px;
  }

  .metric-label,
  .card-head small,
  .metric-card small {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .metric-card strong {
    color: var(--el-text-color-primary);
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
  }

  .chart-panel {
    height: 100%;
    margin-bottom: 16px;
  }

  .distribution-list {
    display: grid;
    gap: 18px;
    padding: 4px 0;
  }

  .distribution-row {
    display: grid;
    grid-template-columns: 88px minmax(0, 1fr) 42px;
    align-items: center;
    gap: 12px;
  }

  .source-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .source-item {
    display: grid;
    gap: 8px;
    padding: 14px;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
  }

  .source-item span {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .source-item strong {
    font-size: 22px;
  }

  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  @media (max-width: 1200px) {
    .metrics-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 768px) {
    .metrics-grid,
    .source-grid {
      grid-template-columns: 1fr;
    }

    .distribution-row {
      grid-template-columns: 78px minmax(0, 1fr) 34px;
    }
  }
</style>
