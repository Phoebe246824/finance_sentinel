<template>
  <div ref="screenShellRef" class="sentinel-screen-shell">
    <div class="screen-grid-overlay" aria-hidden="true"></div>

    <div class="screen-scale-stage" :style="screenScaleStyle">
      <div class="sentinel-screen">
        <header class="screen-cockpit-header">
          <button class="header-action" type="button" @click="goOverview">
            <span>总览</span>
          </button>

          <div class="header-title-frame">
            <div class="header-title-wing" aria-hidden="true"></div>
            <div class="header-title">
              <span>Sentinel 风险态势大屏</span>
              <small>{{ statusLine }}</small>
            </div>
            <div class="header-title-wing" aria-hidden="true"></div>
          </div>

          <div class="header-clock">
            <span>{{ currentTime }}</span>
            <small>数据更新 {{ formatDate(overview?.updated_at) }}</small>
          </div>
        </header>

        <main class="screen-main">
          <section class="screen-column left-column">
            <ScreenPanel title="风险总览">
              <div class="kpi-grid">
                <div v-for="item in primaryKpis" :key="item.label" class="kpi-tile">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                  <small>{{ item.hint }}</small>
                </div>
              </div>
            </ScreenPanel>

            <ScreenPanel title="风险分布">
              <div ref="riskChartRef" class="chart-box"></div>
            </ScreenPanel>

            <ScreenPanel title="近期待势走势">
              <div ref="trendChartRef" class="chart-box"></div>
            </ScreenPanel>
          </section>

          <section class="center-column">
            <div class="center-stage">
              <div class="stage-header">
                <span>综合态势指数</span>
                <strong>{{ postureScore }}</strong>
                <small>{{ postureLevel }}</small>
              </div>

              <div class="threat-orbit" aria-hidden="true">
                <span class="orbit-ring orbit-ring-outer"></span>
                <span class="orbit-ring orbit-ring-middle"></span>
                <span class="orbit-ring orbit-ring-inner"></span>
              </div>

              <div class="posture-core">
                <span>RISK</span>
                <strong>{{ postureScore }}</strong>
                <small>{{ postureLevel }}</small>
              </div>

              <div class="risk-pulse-list">
                <div
                  v-for="item in riskPulseItems"
                  :key="item.level"
                  class="risk-pulse"
                  :class="`risk-pulse-${item.level}`"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                  <i :style="{ width: item.percent }"></i>
                </div>
              </div>

              <div class="posture-stats">
                <span>图节点 {{ formatNumber(stats?.graph_node_count) }}</span>
                <span>图关系 {{ formatNumber(stats?.graph_edge_count) }}</span>
                <span>平均处理 {{ formatLatency(stats?.avg_processing_latency_ms) }}</span>
              </div>
            </div>

            <ScreenPanel title="近期高风险事件">
              <div v-if="highRiskEvents.length > 0" class="event-stream">
                <div v-for="event in highRiskEvents" :key="event.event_id" class="event-row">
                  <span>{{ formatDate(event.timestamp) }}</span>
                  <strong>{{ event.summary || event.event_id }}</strong>
                  <small>{{ event.event_type || sourceLabel(event.source) }}</small>
                </div>
              </div>
              <div v-else class="empty-state">暂无高风险事件</div>
            </ScreenPanel>
          </section>

          <section class="screen-column right-column">
            <ScreenPanel title="运行态势">
              <div class="health-grid">
                <div v-for="item in healthItems" :key="item.label" class="health-item">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </ScreenPanel>

            <ScreenPanel title="来源分布">
              <div ref="sourceChartRef" class="chart-box"></div>
            </ScreenPanel>

            <ScreenPanel title="风险事件排行">
              <div v-if="rankedEvents.length > 0" class="ranking-list">
                <div
                  v-for="(event, index) in rankedEvents"
                  :key="event.event_id"
                  class="ranking-row"
                >
                  <span>{{ index + 1 }}</span>
                  <strong>{{ event.summary || event.event_id }}</strong>
                  <small>{{ formatRiskScore(event.risk_score) }}</small>
                </div>
              </div>
              <div v-else class="empty-state">暂无事件数据</div>
            </ScreenPanel>

            <ScreenPanel title="实体热点">
              <div v-if="entityHotspots.length > 0" class="entity-list">
                <div v-for="entity in entityHotspots" :key="entity.key" class="entity-row">
                  <span>{{ entity.type }}</span>
                  <strong>{{ entity.name }}</strong>
                  <small>{{ entity.count }}</small>
                </div>
              </div>
              <div v-else class="empty-state">暂无实体数据</div>
            </ScreenPanel>
          </section>
        </main>

        <footer class="screen-footer">
          <div v-if="trendSnippets.length > 0" class="trend-marquee">
            <div v-for="item in trendSnippets" :key="item.id" class="trend-item">
              <span>{{ item.label }}</span>
              <p>{{ item.text }}</p>
            </div>
          </div>
          <div v-else class="empty-state footer-empty">暂无趋势研判</div>
        </footer>

        <div v-if="loading" class="screen-mask">加载态势数据...</div>
        <div v-else-if="errorMessage" class="screen-mask error">
          <span>{{ errorMessage }}</span>
          <button type="button" @click="loadOverview">重试</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
  import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
  import { useRouter } from 'vue-router'
  import { fetchDashboardOverview } from '@/api/sentinel/dashboard'
  import type { DashboardOverview, RiskLevel, SentinelEvent } from '@/api/sentinel/types'
  import { echarts, type EChartsOption } from '@/plugins/echarts'
  import type { ECharts } from 'echarts/core'

  defineOptions({ name: 'SentinelDataScreen' })

  const ScreenPanel = defineComponent({
    name: 'ScreenPanel',
    props: {
      title: {
        type: String,
        required: true
      }
    },
    setup(props, { slots }) {
      return () =>
        h('section', { class: 'screen-panel' }, [
          h('div', { class: 'panel-title' }, props.title),
          h('div', { class: 'panel-body' }, slots.default?.())
        ])
    }
  })

  type AssessedRiskLevel = Exclude<RiskLevel, 'unassessed'>

  interface DailyTrendPoint {
    date: string
    count: number
    highCount: number
    avgRisk: number
  }

  interface EntityHotspot {
    key: string
    name: string
    type: string
    count: number
  }

  const router = useRouter()
  const screenShellRef = ref<HTMLElement>()
  const riskChartRef = ref<HTMLElement>()
  const sourceChartRef = ref<HTMLElement>()
  const trendChartRef = ref<HTMLElement>()
  const overview = ref<DashboardOverview>()
  const loading = ref(false)
  const errorMessage = ref('')
  const currentTime = ref('')
  const screenScale = ref(1)

  let riskChart: ECharts | null = null
  let sourceChart: ECharts | null = null
  let trendChart: ECharts | null = null
  let clockTimer: number | undefined
  let shellResizeObserver: ResizeObserver | undefined

  const riskOrder: AssessedRiskLevel[] = ['high', 'medium', 'low']
  const riskNames: Record<RiskLevel, string> = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
    unassessed: '未评估'
  }
  const riskColors: Record<AssessedRiskLevel, string> = {
    high: '#ff5b6e',
    medium: '#ffbc58',
    low: '#2fe6bd'
  }
  const riskWeight: Record<RiskLevel, number> = {
    high: 1,
    medium: 0.55,
    low: 0.2,
    unassessed: 0
  }
  const sourceNames: Record<string, string> = {
    transaction: '交易监测',
    behavior: '行为画像',
    news: '公开舆情'
  }

  const stats = computed(() => overview.value?.stats)
  const recentEvents = computed(() => overview.value?.recent_events || [])
  const screenScaleStyle = computed(() => ({ '--screen-scale': String(screenScale.value) }))

  const assessedCount = computed(() => {
    const current = stats.value
    if (!current) return 0
    return current.high_risk_count + current.medium_risk_count + current.low_risk_count
  })

  const statusLine = computed(() => {
    const current = overview.value
    if (!current) return '等待真实数据接入'
    if (current.truncated || current.stats.data_truncated) return '当前统计基于截断数据'
    const high = current.stats.high_risk_count
    return high > 0 ? `高风险事件 ${formatNumber(high)} 件，建议优先复核` : '当前无高风险积压'
  })

  const primaryKpis = computed(() => [
    {
      label: '事件总量',
      value: formatNumber(stats.value?.total_events),
      hint: `${formatNumber(assessedCount.value)} 条已评估`
    },
    {
      label: '高风险',
      value: formatNumber(stats.value?.high_risk_count),
      hint: '优先处置'
    },
    {
      label: '中风险',
      value: formatNumber(stats.value?.medium_risk_count),
      hint: '重点关注'
    },
    {
      label: '低风险',
      value: formatNumber(stats.value?.low_risk_count),
      hint: '持续跟踪'
    }
  ])

  const healthItems = computed(() => [
    {
      label: '运行时长',
      value: stats.value?.runtime_metrics_available
        ? `${formatNumber(stats.value.uptime_hours, 1)} h`
        : '--'
    },
    {
      label: '事件速率',
      value: stats.value?.runtime_metrics_available
        ? `${formatNumber(stats.value.events_per_minute, 1)} / min`
        : '--'
    },
    {
      label: '平均耗时',
      value: formatLatency(stats.value?.avg_processing_latency_ms)
    },
    {
      label: '数据范围',
      value: stats.value?.data_truncated ? '已截断' : '完整'
    }
  ])

  const postureScore = computed(() => {
    const current = stats.value
    if (!current || current.total_events <= 0) return '--'
    const distributionScore =
      ((current.high_risk_count * riskWeight.high +
        current.medium_risk_count * riskWeight.medium +
        current.low_risk_count * riskWeight.low) /
        current.total_events) *
      100
    const recentScores = recentEvents.value
      .map((event) => eventRiskValue(event))
      .filter((score) => score > 0)
    const recentScore =
      recentScores.length > 0
        ? (recentScores.reduce((sum, score) => sum + score, 0) / recentScores.length) * 100
        : distributionScore
    return String(Math.min(100, Math.round(distributionScore * 0.7 + recentScore * 0.3)))
  })

  const postureLevel = computed(() => {
    const value = Number(postureScore.value)
    if (Number.isNaN(value)) return '等待评估'
    if (value >= 70) return '高压态势'
    if (value >= 40) return '关注态势'
    return '平稳态势'
  })

  const riskPulseItems = computed(() => {
    const current = stats.value
    const total = Math.max(1, current?.total_events || 0)
    return [
      {
        level: 'high',
        label: '高风险',
        value: formatNumber(current?.high_risk_count),
        percent: formatPercent(ratio(current?.high_risk_count || 0, total))
      },
      {
        level: 'medium',
        label: '中风险',
        value: formatNumber(current?.medium_risk_count),
        percent: formatPercent(ratio(current?.medium_risk_count || 0, total))
      },
      {
        level: 'low',
        label: '低风险',
        value: formatNumber(current?.low_risk_count),
        percent: formatPercent(ratio(current?.low_risk_count || 0, total))
      },
      {
        level: 'unassessed',
        label: '未评估',
        value: formatNumber(current?.unassessed_count),
        percent: formatPercent(ratio(current?.unassessed_count || 0, total))
      }
    ]
  })

  const highRiskEvents = computed(() =>
    recentEvents.value.filter((event) => event.risk_level === 'high').slice(0, 5)
  )

  const rankedEvents = computed(() =>
    [...recentEvents.value]
      .sort((left, right) => eventRiskValue(right) - eventRiskValue(left))
      .slice(0, 6)
  )

  const trendSnippets = computed(() =>
    recentEvents.value
      .filter(
        (event) => event.trend_report?.trend_prediction || event.trend_report?.intent_analysis
      )
      .slice(0, 5)
      .map((event) => ({
        id: event.event_id,
        label: event.trend_report?.severity_name || event.event_type || '趋势研判',
        text:
          event.trend_report?.trend_prediction ||
          event.trend_report?.intent_analysis ||
          event.summary ||
          event.event_id
      }))
  )

  const entityHotspots = computed<EntityHotspot[]>(() => {
    const buckets = new Map<string, EntityHotspot>()
    for (const event of recentEvents.value) {
      for (const entity of event.key_entities || []) {
        if (!entity.name) continue
        const type = entity.type || 'ENTITY'
        const key = `${type}:${entity.name}`
        const current = buckets.get(key)
        if (current) {
          current.count += 1
        } else {
          buckets.set(key, {
            key,
            name: entity.name,
            type,
            count: 1
          })
        }
      }
    }
    return [...buckets.values()].sort((left, right) => right.count - left.count).slice(0, 5)
  })

  const dailyTrendPoints = computed<DailyTrendPoint[]>(() => {
    const buckets = new Map<string, { count: number; highCount: number; riskSum: number }>()
    for (const event of recentEvents.value) {
      const key = eventDateKey(event.timestamp)
      if (!key) continue
      const current = buckets.get(key) || { count: 0, highCount: 0, riskSum: 0 }
      current.count += 1
      current.highCount += event.risk_level === 'high' ? 1 : 0
      current.riskSum += eventRiskValue(event)
      buckets.set(key, current)
    }
    return [...buckets.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .slice(-7)
      .map(([date, item]) => ({
        date,
        count: item.count,
        highCount: item.highCount,
        avgRisk: item.count > 0 ? item.riskSum / item.count : 0
      }))
  })

  const sourceLabel = (value: string) => sourceNames[value] || value || '未知来源'

  const eventDateKey = (value?: string) => {
    if (!value) return ''
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  const eventRiskValue = (event: SentinelEvent) => {
    const score = Number(event.risk_score)
    if (Number.isFinite(score) && score > 0) return Math.max(0, Math.min(1, score))
    return riskWeight[event.risk_level] || 0
  }

  const formatDate = (value?: string) => {
    if (!value) return '--'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    return date.toLocaleString('zh-CN', { hour12: false })
  }

  const formatNumber = (value?: number | null, digits = 0) => {
    if (value === undefined || value === null || Number.isNaN(Number(value))) return '--'
    return new Intl.NumberFormat('zh-CN', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }).format(Number(value))
  }

  const formatPercent = (value: number) => `${Math.round(value * 100)}%`

  const formatLatency = (value?: number | null) => {
    if (value === undefined || value === null) return '--'
    return `${formatNumber(value)} ms`
  }

  const formatRiskScore = (value?: number | null) => {
    if (value === undefined || value === null) return '--'
    return `${Math.round(Math.max(0, Math.min(1, Number(value))) * 100)}`
  }

  const ratio = (part?: number | null, total?: number | null) => {
    const denominator = Number(total || 0)
    if (denominator <= 0) return 0
    return Math.max(0, Math.min(1, Number(part || 0) / denominator))
  }

  const formatRiskDistributionLabel = (params: unknown) => {
    if (!params || typeof params !== 'object') return ''
    const item = params as { name?: unknown; value?: unknown }
    return [String(item.name || ''), String(item.value ?? '')].join('\n')
  }

  const buildRiskOptions = (): EChartsOption => {
    const distribution = overview.value?.risk_distribution || {}
    const total = riskOrder.reduce((sum, level) => sum + (distribution[level] || 0), 0)
    if (total === 0) return buildEmptyChartOptions('暂无已评估风险分布')
    return {
      color: riskOrder.map((level) => riskColors[level]),
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(5, 22, 37, 0.92)',
        borderColor: 'rgba(78, 220, 255, 0.42)',
        textStyle: { color: '#dff8ff' }
      },
      legend: {
        bottom: 0,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#9edcff' }
      },
      series: [
        {
          type: 'pie',
          radius: ['52%', '74%'],
          center: ['50%', '43%'],
          avoidLabelOverlap: true,
          label: { color: '#dff8ff', formatter: formatRiskDistributionLabel },
          labelLine: { lineStyle: { color: 'rgba(181, 239, 255, 0.58)' } },
          data: riskOrder.map((level) => ({
            name: riskNames[level],
            value: distribution[level] || 0
          }))
        }
      ]
    }
  }

  const buildSourceOptions = (): EChartsOption => {
    const entries = Object.entries(overview.value?.source_distribution || {})
    if (entries.length === 0) return buildEmptyChartOptions('暂无来源分布')
    return {
      color: ['#36d4ff'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(5, 22, 37, 0.92)',
        borderColor: 'rgba(78, 220, 255, 0.42)',
        textStyle: { color: '#dff8ff' }
      },
      grid: { top: 18, right: 16, bottom: 36, left: 38 },
      xAxis: {
        type: 'category',
        data: entries.map(([source]) => sourceLabel(source)),
        axisLabel: { color: '#9edcff' },
        axisLine: { lineStyle: { color: '#236286' } },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#9edcff' },
        splitLine: { lineStyle: { color: 'rgba(77, 184, 255, 0.16)' } }
      },
      series: [
        {
          type: 'bar',
          barWidth: 18,
          data: entries.map(([, count]) => count),
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: '#55f0ff' },
                { offset: 1, color: '#147ca5' }
              ]
            }
          }
        }
      ]
    }
  }

  const buildTrendOptions = (): EChartsOption => {
    const points = dailyTrendPoints.value
    if (points.length === 0) return buildEmptyChartOptions('暂无近期事件走势')
    return {
      color: ['#2be4b8', '#ff5b6e', '#ffbc58'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(5, 22, 37, 0.92)',
        borderColor: 'rgba(78, 220, 255, 0.42)',
        textStyle: { color: '#dff8ff' }
      },
      legend: {
        top: 0,
        right: 0,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#9edcff' }
      },
      grid: { top: 38, right: 18, bottom: 28, left: 34 },
      xAxis: {
        type: 'category',
        boundaryGap: true,
        data: points.map((item) => item.date.slice(5)),
        axisLabel: { color: '#9edcff' },
        axisLine: { lineStyle: { color: '#236286' } },
        axisTick: { show: false }
      },
      yAxis: [
        {
          type: 'value',
          axisLabel: { color: '#9edcff' },
          splitLine: { lineStyle: { color: 'rgba(77, 184, 255, 0.16)' } }
        },
        {
          type: 'value',
          min: 0,
          max: 100,
          axisLabel: { color: '#9edcff', formatter: '{value}%' },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          name: '事件数',
          type: 'bar',
          barWidth: 14,
          data: points.map((item) => item.count),
          itemStyle: { borderRadius: [4, 4, 0, 0] }
        },
        {
          name: '高风险',
          type: 'bar',
          barWidth: 14,
          data: points.map((item) => item.highCount),
          itemStyle: { borderRadius: [4, 4, 0, 0] }
        },
        {
          name: '平均风险',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 6,
          data: points.map((item) => Math.round(item.avgRisk * 100))
        }
      ]
    }
  }

  const buildEmptyChartOptions = (message: string): EChartsOption => ({
    title: {
      text: message,
      left: 'center',
      top: 'middle',
      textStyle: {
        color: '#8cb9cf',
        fontSize: 14,
        fontWeight: 'normal'
      }
    },
    xAxis: { show: false },
    yAxis: { show: false },
    series: []
  })

  const renderCharts = () => {
    if (!riskChartRef.value || !sourceChartRef.value || !trendChartRef.value) return
    riskChart ||= echarts.init(riskChartRef.value)
    sourceChart ||= echarts.init(sourceChartRef.value)
    trendChart ||= echarts.init(trendChartRef.value)
    riskChart.setOption(buildRiskOptions(), true)
    sourceChart.setOption(buildSourceOptions(), true)
    trendChart.setOption(buildTrendOptions(), true)
  }

  const resizeCharts = () => {
    riskChart?.resize()
    sourceChart?.resize()
    trendChart?.resize()
  }

  const updateScreenScale = () => {
    const shell = screenShellRef.value
    const rect = shell?.getBoundingClientRect()
    const availableWidth = rect?.width || window.innerWidth
    const availableHeight = rect
      ? Math.max(320, window.innerHeight - Math.max(rect.top, 0))
      : window.innerHeight
    const nextScale = Math.min(1, availableWidth / 1920, availableHeight / 1080)
    screenScale.value = Number(Math.max(0.18, nextScale).toFixed(4))
    window.requestAnimationFrame(resizeCharts)
  }

  const handleViewportResize = () => {
    updateScreenScale()
  }

  const loadOverview = async () => {
    loading.value = true
    errorMessage.value = ''
    try {
      overview.value = await fetchDashboardOverview()
      await nextTick()
      updateScreenScale()
      renderCharts()
    } catch (error) {
      overview.value = undefined
      errorMessage.value = error instanceof Error ? error.message : '态势数据加载失败'
    } finally {
      loading.value = false
    }
  }

  const updateClock = () => {
    currentTime.value = new Date().toLocaleString('zh-CN', { hour12: false })
  }

  const goOverview = () => {
    router.push({ name: 'SentinelDashboard' })
  }

  onMounted(() => {
    updateClock()
    updateScreenScale()
    clockTimer = window.setInterval(updateClock, 1000)
    window.addEventListener('resize', handleViewportResize)
    if (typeof ResizeObserver !== 'undefined' && screenShellRef.value) {
      shellResizeObserver = new ResizeObserver(updateScreenScale)
      shellResizeObserver.observe(screenShellRef.value)
    }
    loadOverview()
  })

  onBeforeUnmount(() => {
    if (clockTimer) window.clearInterval(clockTimer)
    window.removeEventListener('resize', handleViewportResize)
    shellResizeObserver?.disconnect()
    riskChart?.dispose()
    sourceChart?.dispose()
    trendChart?.dispose()
  })
</script>

<style scoped>
  .sentinel-screen-shell {
    --screen-scale: 1;
    position: relative;
    min-height: calc(100vh - 96px);
    margin: -20px;
    overflow: auto;
    background:
      linear-gradient(
        115deg,
        rgba(6, 18, 32, 0.98),
        rgba(9, 42, 56, 0.96) 42%,
        rgba(5, 13, 25, 0.99)
      ),
      repeating-linear-gradient(90deg, rgba(80, 221, 255, 0.05) 0 1px, transparent 1px 120px),
      repeating-linear-gradient(0deg, rgba(80, 221, 255, 0.04) 0 1px, transparent 1px 92px);
  }

  .screen-grid-overlay {
    position: fixed;
    inset: 0;
    pointer-events: none;
    background:
      linear-gradient(
        180deg,
        rgba(48, 207, 255, 0.09),
        transparent 18%,
        transparent 82%,
        rgba(48, 207, 255, 0.06)
      ),
      repeating-linear-gradient(0deg, transparent 0 7px, rgba(80, 221, 255, 0.035) 8px 9px);
    mask-image: linear-gradient(180deg, transparent, #000 14%, #000 86%, transparent);
  }

  .screen-scale-stage {
    position: relative;
    width: calc(1920px * var(--screen-scale));
    height: calc(1080px * var(--screen-scale));
    margin: 0 auto;
    overflow: hidden;
  }

  .sentinel-screen {
    position: relative;
    display: grid;
    grid-template-rows: 104px minmax(0, 1fr) 126px;
    gap: 18px;
    width: 1920px;
    height: 1080px;
    box-sizing: border-box;
    padding: 18px 28px 24px;
    color: #dff8ff;
    transform: scale(var(--screen-scale));
    transform-origin: top left;
  }

  .screen-cockpit-header {
    display: grid;
    grid-template-columns: 320px minmax(0, 1fr) 320px;
    gap: 24px;
    align-items: start;
  }

  .header-action,
  .screen-mask button {
    position: relative;
    height: 38px;
    padding: 0 26px;
    overflow: hidden;
    color: #99f8ff;
    cursor: pointer;
    background: linear-gradient(90deg, rgba(7, 54, 77, 0.82), rgba(12, 83, 104, 0.56));
    border: 1px solid rgba(91, 231, 255, 0.62);
    box-shadow: inset 0 0 18px rgba(60, 213, 255, 0.16);
  }

  .header-action::before,
  .header-action::after {
    position: absolute;
    top: -1px;
    width: 16px;
    height: 40px;
    content: '';
    border-color: rgba(91, 231, 255, 0.85);
    border-style: solid;
  }

  .header-action::before {
    left: -1px;
    border-width: 1px 0 1px 1px;
  }

  .header-action::after {
    right: -1px;
    border-width: 1px 1px 1px 0;
  }

  .header-title-frame {
    display: grid;
    grid-template-columns: minmax(80px, 1fr) minmax(360px, 660px) minmax(80px, 1fr);
    align-items: start;
  }

  .header-title-wing {
    height: 38px;
    margin-top: 6px;
    border-top: 1px solid rgba(91, 231, 255, 0.48);
    border-bottom: 1px solid rgba(91, 231, 255, 0.12);
  }

  .header-title-wing:first-child {
    background: linear-gradient(90deg, transparent, rgba(58, 212, 255, 0.18));
    clip-path: polygon(0 0, 100% 0, 86% 100%, 0 100%);
  }

  .header-title-wing:last-child {
    background: linear-gradient(90deg, rgba(58, 212, 255, 0.18), transparent);
    clip-path: polygon(14% 100%, 0 0, 100% 0, 100% 100%);
  }

  .header-title {
    display: grid;
    gap: 6px;
    justify-items: center;
    min-width: 0;
    padding: 8px 26px 14px;
    text-align: center;
    background: linear-gradient(180deg, rgba(11, 76, 93, 0.8), rgba(8, 39, 62, 0.66));
    border: 1px solid rgba(91, 231, 255, 0.58);
    clip-path: polygon(8% 0, 92% 0, 100% 58%, 86% 100%, 14% 100%, 0 58%);
    box-shadow:
      0 0 28px rgba(39, 216, 255, 0.18),
      inset 0 0 24px rgba(61, 221, 255, 0.14);
  }

  .header-title span {
    font-size: 32px;
    font-weight: 800;
    line-height: 1.18;
    color: #f2feff;
    letter-spacing: 0;
    text-shadow: 0 0 18px rgba(88, 232, 255, 0.45);
  }

  .header-title small,
  .header-clock small,
  .kpi-tile small,
  .event-row small,
  .ranking-row small,
  .health-item span,
  .trend-item span,
  .entity-row span,
  .entity-row small {
    color: #8cb9cf;
  }

  .header-clock {
    display: grid;
    gap: 6px;
    justify-items: end;
    font-size: 16px;
  }

  .header-clock span {
    color: #f2feff;
  }

  .screen-main {
    display: grid;
    grid-template-columns: 430px minmax(0, 1fr) 430px;
    gap: 24px;
    min-height: 0;
  }

  .screen-column,
  .center-column {
    display: grid;
    gap: 16px;
    min-height: 0;
  }

  .left-column {
    grid-template-rows: minmax(268px, 0.82fr) minmax(0, 1fr) minmax(0, 1fr);
  }

  .right-column {
    grid-template-rows:
      minmax(236px, 0.72fr) minmax(176px, 0.88fr) minmax(0, 1fr)
      minmax(0, 0.82fr);
  }

  .center-column {
    grid-template-rows: minmax(0, 1fr) 250px;
  }

  :deep(.screen-panel) {
    position: relative;
    min-height: 0;
    padding: 48px 18px 18px;
    overflow: hidden;
    background:
      linear-gradient(180deg, rgba(9, 40, 58, 0.94), rgba(6, 24, 42, 0.9)),
      linear-gradient(
        90deg,
        rgba(75, 215, 255, 0.08),
        transparent 20%,
        transparent 80%,
        rgba(75, 215, 255, 0.08)
      );
    border: 1px solid rgba(72, 191, 255, 0.4);
    box-shadow:
      inset 0 0 26px rgba(37, 169, 232, 0.14),
      0 0 18px rgba(0, 158, 216, 0.08);
  }

  :deep(.screen-panel)::before,
  :deep(.screen-panel)::after {
    position: absolute;
    width: 34px;
    height: 34px;
    content: '';
    border-color: #4fd9ff;
    border-style: solid;
  }

  :deep(.screen-panel)::before {
    top: 0;
    left: 0;
    border-width: 2px 0 0 2px;
  }

  :deep(.screen-panel)::after {
    right: 0;
    bottom: 0;
    border-width: 0 2px 2px 0;
  }

  :deep(.panel-title) {
    position: absolute;
    top: 14px;
    left: 18px;
    display: inline-flex;
    gap: 8px;
    align-items: center;
    font-size: 16px;
    font-weight: 700;
    color: #f3fbff;
  }

  :deep(.panel-title)::before {
    width: 8px;
    height: 8px;
    content: '';
    background: #6ff7ff;
    box-shadow: 0 0 14px rgba(111, 247, 255, 0.72);
    transform: rotate(45deg);
  }

  :deep(.panel-body) {
    height: 100%;
    min-height: 0;
  }

  .kpi-grid,
  .health-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    height: 100%;
  }

  .kpi-grid {
    min-height: 188px;
  }

  .health-grid {
    min-height: 166px;
  }

  .kpi-tile,
  .health-item {
    position: relative;
    display: grid;
    gap: 4px;
    align-content: center;
    min-width: 0;
    padding: 8px 14px;
    overflow: visible;
    background: rgba(9, 52, 74, 0.74);
    border: 1px solid rgba(75, 187, 236, 0.24);
  }

  .kpi-tile {
    min-height: 88px;
  }

  .health-item {
    min-height: 77px;
  }

  .kpi-tile::after,
  .health-item::after {
    position: absolute;
    top: 0;
    right: 0;
    width: 44px;
    height: 2px;
    content: '';
    background: #62ecff;
  }

  .kpi-tile span,
  .health-item span {
    font-size: 13px;
  }

  .kpi-tile strong {
    display: block;
    overflow: visible;
    padding-bottom: 3px;
    font-size: 28px;
    font-variant-numeric: tabular-nums;
    line-height: 1.24;
    color: #ffffff;
    text-overflow: clip;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .health-item strong {
    overflow: hidden;
    font-size: 20px;
    line-height: 1.2;
    color: #ffffff;
    text-overflow: ellipsis;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .chart-box {
    width: 100%;
    height: 100%;
    min-height: 176px;
  }

  .center-stage {
    position: relative;
    display: grid;
    place-items: center;
    min-height: 0;
    overflow: hidden;
    background:
      linear-gradient(rgba(62, 188, 255, 0.08) 1px, transparent 1px),
      linear-gradient(90deg, rgba(62, 188, 255, 0.08) 1px, transparent 1px),
      linear-gradient(180deg, rgba(8, 38, 58, 0.84), rgba(4, 17, 31, 0.9));
    background-size:
      38px 38px,
      38px 38px,
      auto;
    border: 1px solid rgba(72, 191, 255, 0.34);
    box-shadow: inset 0 0 80px rgba(36, 173, 232, 0.08);
  }

  .center-stage::before,
  .center-stage::after {
    position: absolute;
    inset: 24px;
    pointer-events: none;
    content: '';
    border: 1px solid rgba(96, 232, 255, 0.18);
  }

  .center-stage::after {
    inset: 52px;
    border-style: dashed;
  }

  .stage-header {
    position: absolute;
    top: 28px;
    display: grid;
    gap: 4px;
    justify-items: center;
  }

  .stage-header span {
    color: #9edcff;
  }

  .stage-header strong {
    font-size: 44px;
    line-height: 1;
    color: #7df6ff;
  }

  .stage-header small {
    color: #f7cf75;
  }

  .threat-orbit {
    position: relative;
    width: 420px;
    height: 420px;
  }

  .orbit-ring {
    position: absolute;
    inset: 0;
    border: 1px solid rgba(95, 234, 255, 0.34);
    border-radius: 50%;
    box-shadow: 0 0 32px rgba(50, 220, 255, 0.14);
  }

  .orbit-ring::before,
  .orbit-ring::after {
    position: absolute;
    width: 10px;
    height: 10px;
    content: '';
    background: #7df6ff;
    border-radius: 50%;
    box-shadow: 0 0 18px rgba(125, 246, 255, 0.76);
  }

  .orbit-ring::before {
    top: 16%;
    left: 12%;
  }

  .orbit-ring::after {
    right: 18%;
    bottom: 10%;
    background: #ffbc58;
  }

  .orbit-ring-middle {
    inset: 48px;
    border-style: dashed;
  }

  .orbit-ring-inner {
    inset: 102px;
  }

  .posture-core {
    position: absolute;
    display: grid;
    place-items: center;
    width: 230px;
    height: 230px;
    color: #dff8ff;
    background: rgba(3, 22, 36, 0.7);
    border: 2px solid rgba(91, 231, 255, 0.58);
    border-radius: 50%;
    box-shadow:
      0 0 42px rgba(69, 206, 255, 0.22),
      inset 0 0 50px rgba(25, 124, 186, 0.34);
  }

  .posture-core span {
    align-self: end;
    color: #9edcff;
  }

  .posture-core strong {
    font-size: 74px;
    line-height: 0.92;
    color: #ffffff;
  }

  .posture-core small {
    align-self: start;
    color: #f7cf75;
  }

  .risk-pulse-list {
    position: absolute;
    right: 28px;
    bottom: 84px;
    display: grid;
    gap: 10px;
    width: min(220px, 30%);
  }

  .risk-pulse {
    display: grid;
    grid-template-columns: 68px 1fr;
    gap: 8px;
    align-items: center;
    color: #dff8ff;
  }

  .risk-pulse span {
    color: #9edcff;
  }

  .risk-pulse strong {
    justify-self: end;
  }

  .risk-pulse i {
    grid-column: 1 / -1;
    height: 3px;
    background: #48dfff;
    box-shadow: 0 0 12px rgba(72, 223, 255, 0.6);
  }

  .risk-pulse-high i {
    background: #ff5b6e;
  }

  .risk-pulse-medium i {
    background: #ffbc58;
  }

  .risk-pulse-low i {
    background: #2fe6bd;
  }

  .risk-pulse-unassessed i {
    background: #8cb9cf;
  }

  .posture-stats {
    position: absolute;
    bottom: 28px;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    justify-content: center;
    max-width: calc(100% - 56px);
  }

  .posture-stats span {
    padding: 8px 14px;
    color: #b9ebff;
    background: rgba(9, 42, 64, 0.82);
    border: 1px solid rgba(91, 231, 255, 0.26);
  }

  .event-stream,
  .ranking-list,
  .entity-list,
  .trend-marquee {
    display: grid;
    gap: 10px;
    max-height: 100%;
    overflow: auto;
  }

  .event-row,
  .ranking-row,
  .entity-row,
  .trend-item {
    display: grid;
    gap: 4px;
    min-width: 0;
    padding: 10px 12px;
    background: rgba(10, 40, 62, 0.62);
    border-left: 3px solid #39d7ff;
  }

  .event-row strong,
  .ranking-row strong,
  .entity-row strong,
  .trend-item p {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ranking-row,
  .entity-row {
    grid-template-columns: 28px minmax(0, 1fr) 46px;
    align-items: center;
  }

  .ranking-row span {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    color: #06101c;
    background: #6fefff;
  }

  .entity-row small {
    justify-self: end;
  }

  .screen-footer {
    min-height: 0;
    padding: 16px 18px;
    background: linear-gradient(
      90deg,
      rgba(8, 35, 54, 0.8),
      rgba(9, 56, 70, 0.74),
      rgba(8, 35, 54, 0.8)
    );
    border: 1px solid rgba(72, 191, 255, 0.34);
  }

  .trend-marquee {
    grid-template-columns: repeat(5, minmax(0, 1fr));
    height: 100%;
  }

  .trend-item {
    border-left-color: #ffbc58;
  }

  .empty-state {
    display: grid;
    place-items: center;
    height: 100%;
    min-height: 96px;
    color: #8cb9cf;
  }

  .footer-empty {
    min-height: 80px;
  }

  .screen-mask {
    position: absolute;
    inset: 122px 28px 24px;
    z-index: 5;
    display: grid;
    place-items: center;
    color: #dff8ff;
    background: rgba(5, 15, 28, 0.76);
    backdrop-filter: blur(3px);
  }

  .screen-mask.error {
    gap: 16px;
  }

  @media (max-width: 1320px) {
    .sentinel-screen-shell {
      margin: -12px;
    }

    .screen-scale-stage {
      width: 100%;
      height: auto;
      min-height: 100%;
      overflow: visible;
    }

    .sentinel-screen {
      grid-template-rows: auto auto auto;
      width: 100%;
      height: auto;
      min-height: calc(100vh - 24px);
      padding: 16px;
      transform: none;
    }

    .screen-cockpit-header,
    .screen-main {
      grid-template-columns: 1fr;
    }

    .header-title-frame {
      order: -1;
      grid-template-columns: 1fr;
    }

    .header-title-wing {
      display: none;
    }

    .header-clock,
    .header-title {
      justify-items: start;
      text-align: left;
    }

    .header-title {
      clip-path: none;
    }

    .header-title span {
      font-size: 28px;
    }

    .left-column,
    .right-column,
    .center-column {
      grid-template-rows: none;
    }

    :deep(.screen-panel),
    .center-stage {
      min-height: 270px;
    }

    .center-stage {
      min-height: 560px;
    }

    .kpi-grid,
    .health-grid,
    .trend-marquee {
      grid-template-columns: 1fr;
    }

    .threat-orbit {
      width: 300px;
      height: 300px;
    }

    .posture-core {
      width: 190px;
      height: 190px;
    }

    .posture-core strong {
      font-size: 56px;
    }

    .risk-pulse-list {
      position: static;
      width: min(100%, 320px);
      margin-top: -24px;
    }

    .posture-stats {
      position: static;
      margin-top: 12px;
    }

    .screen-mask {
      inset: 0;
      min-height: 320px;
    }
  }

  @media (max-width: 720px) {
    .header-title span {
      font-size: 24px;
    }
  }
</style>
