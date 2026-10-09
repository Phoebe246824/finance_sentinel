<template>
  <ElCard shadow="never">
    <div class="progress-head">
      <strong>{{ task?.stage_label || '等待分析' }}</strong>
      <span>{{ progressText }}</span>
    </div>
    <ElProgress :percentage="percentage" :status="progressStatus" />
    <p class="progress-detail">{{ task?.stage_detail || '输入事件文本后开始分析。' }}</p>
  </ElCard>
</template>

<script setup lang="ts">
  import { computed } from 'vue'
  import type { AnalysisTask } from '@/api/sentinel/types'

  const props = defineProps<{ task?: AnalysisTask | null }>()

  const percentage = computed(() => {
    const index = props.task?.stage_index || 0
    const total = props.task?.stage_total || 4
    return Math.min(100, Math.round((index / total) * 100))
  })

  const progressStatus = computed(() => {
    if (props.task?.status === 'failed') return 'exception'
    if (props.task?.status === 'success') return 'success'
    return undefined
  })

  const progressText = computed(
    () => `${props.task?.stage_index || 0}/${props.task?.stage_total || 4}`
  )
</script>

<style scoped>
  .progress-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }

  .progress-detail {
    margin: 10px 0 0;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
</style>
