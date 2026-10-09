<template>
  <ElTag :type="tagType" effect="light" round>
    {{ label }}
  </ElTag>
</template>

<script setup lang="ts">
  import { computed } from 'vue'
  import type { RiskLevel } from '@/api/sentinel/types'

  const props = defineProps<{ level?: RiskLevel | string }>()

  const label = computed(() => {
    if (props.level === 'high') return '高风险'
    if (props.level === 'medium') return '中风险'
    if (props.level === 'low') return '低风险'
    if (props.level === 'unassessed') return '未评估'
    return '未知'
  })

  const tagType = computed(() => {
    if (props.level === 'high') return 'danger'
    if (props.level === 'medium') return 'warning'
    if (props.level === 'low') return 'success'
    return 'info'
  })
</script>
