<template>
  <div class="event-detail-page">
    <ElSkeleton v-if="loading" :rows="8" animated />
    <ElAlert
      v-else-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
    />
    <ElEmpty v-else-if="!event" description="事件不存在" />
    <template v-else>
      <ElCard shadow="never">
        <template #header>
          <div class="detail-head">
            <div>
              <h2>{{ event.event_id }}</h2>
              <span>{{ event.summary }}</span>
            </div>
            <RiskBadge :level="event.risk_level" />
          </div>
        </template>

        <ElDescriptions :column="3" border>
          <ElDescriptionsItem label="来源">{{ event.source }}</ElDescriptionsItem>
          <ElDescriptionsItem label="类型">{{ event.event_type }}</ElDescriptionsItem>
          <ElDescriptionsItem label="风险得分">
            {{ event.risk_level === 'unassessed' ? '-' : Math.round(event.risk_score * 100) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="事件时间">{{
            formatDate(event.timestamp)
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="分类">
            {{ event.trend_report.category_name }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="严重度">
            {{ event.trend_report.severity_name }}
          </ElDescriptionsItem>
        </ElDescriptions>
      </ElCard>

      <ElRow :gutter="16">
        <ElCol :xs="24" :lg="14">
          <ElCard shadow="never">
            <template #header>
              <span>原始内容与证据</span>
            </template>
            <section class="detail-section">
              <h3>原始内容</h3>
              <p>{{ event.raw_content }}</p>
            </section>
            <section class="detail-section">
              <h3>判定依据</h3>
              <p>{{ event.reasoning }}</p>
            </section>
            <section class="detail-section">
              <h3>关键实体</h3>
              <ElSpace wrap>
                <ElTag v-for="entity in event.key_entities" :key="`${entity.type}-${entity.name}`">
                  {{ entity.name }} · {{ entity.type }}
                </ElTag>
              </ElSpace>
            </section>
          </ElCard>
        </ElCol>

        <ElCol :xs="24" :lg="10">
          <ElCard shadow="never">
            <template #header>
              <span>维度评分</span>
            </template>
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
          </ElCard>
        </ElCol>
      </ElRow>

      <ElCard shadow="never">
        <template #header>
          <span>趋势报告</span>
        </template>
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="分类置信度">
            {{ percent(event.trend_report.category_confidence) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="严重度置信度">
            {{ percent(event.trend_report.severity_confidence) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="意图分析" :span="2">
            {{ event.trend_report.intent_analysis }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="趋势预测" :span="2">
            {{ event.trend_report.trend_prediction }}
          </ElDescriptionsItem>
        </ElDescriptions>
      </ElCard>
    </template>
  </div>
</template>

<script setup lang="ts">
  import { useRoute } from 'vue-router'
  import { fetchEventDetail } from '@/api/sentinel/events'
  import type { SentinelEvent } from '@/api/sentinel/types'

  defineOptions({ name: 'SentinelEventDetail' })

  const route = useRoute()
  const loading = ref(false)
  const event = ref<SentinelEvent>()
  const errorMessage = ref('')
  let loadVersion = 0

  const eventId = computed(() => String(route.params.eventId || ''))

  const formatDate = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }

  const percent = (value: number) => `${Math.round(value * 100)}%`

  const dimensionScores = computed(() =>
    Object.entries(event.value?.dimension_scores || {}).map(([name, score]) => ({
      name,
      value: Math.round(score * 100)
    }))
  )

  const loadEvent = async () => {
    const requestedEventId = eventId.value
    const currentVersion = ++loadVersion
    event.value = undefined
    errorMessage.value = ''
    if (!requestedEventId) {
      loading.value = false
      return
    }
    loading.value = true
    try {
      const nextEvent = await fetchEventDetail(requestedEventId, false)
      if (currentVersion !== loadVersion || eventId.value !== requestedEventId) return
      event.value = nextEvent
    } catch (error) {
      if (currentVersion !== loadVersion || eventId.value !== requestedEventId) return
      errorMessage.value = error instanceof Error ? error.message : '事件详情加载失败'
    } finally {
      if (currentVersion === loadVersion && eventId.value === requestedEventId) {
        loading.value = false
      }
    }
  }

  watch(eventId, loadEvent, { immediate: true })
</script>

<style scoped>
  .event-detail-page {
    display: grid;
    gap: 16px;
  }

  .detail-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  .detail-head h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }

  .detail-head span {
    color: var(--el-text-color-secondary);
  }

  .detail-section {
    margin-bottom: 22px;
  }

  .detail-section:last-child {
    margin-bottom: 0;
  }

  .detail-section h3 {
    margin: 0 0 10px;
    font-size: 15px;
    font-weight: 600;
  }

  .detail-section p {
    margin: 0;
    color: var(--el-text-color-regular);
    line-height: 1.7;
  }

  .score-list {
    display: grid;
    gap: 14px;
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
</style>
