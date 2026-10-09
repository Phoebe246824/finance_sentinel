<template>
  <div class="events-page art-full-height">
    <ArtSearchBar
      v-model="searchForm"
      :items="searchItems"
      :default-expanded="true"
      :show-expand="false"
      @search="handleSearch"
      @reset="handleReset"
    />

    <ElCard class="art-table-card" shadow="never">
      <ArtTableHeader v-model:columns="columnChecks" :loading="loading" @refresh="refreshData" />
      <ElAlert
        v-if="error"
        class="events-error"
        :title="error.message || '事件列表加载失败'"
        type="error"
        show-icon
        :closable="false"
      />
      <ElAlert
        v-if="resultsTruncated && !error"
        class="events-warning"
        title="事件结果超过当前查询上限，当前列表和总数为截断结果"
        type="warning"
        show-icon
        :closable="false"
      />
      <ArtTable
        row-key="event_id"
        :loading="loading"
        :data="data"
        :columns="columns"
        :pagination="pagination"
        :empty-text="error ? '事件列表加载失败' : '暂无事件数据'"
        @pagination:size-change="handleSizeChange"
        @pagination:current-change="handleCurrentChange"
      />
    </ElCard>
  </div>
</template>

<script setup lang="ts">
  import { ElButton } from 'element-plus'
  import { useRouter } from 'vue-router'
  import { useTable } from '@/hooks/core/useTable'
  import { fetchEvents, type EventSearchParams } from '@/api/sentinel/events'
  import type { SentinelEvent } from '@/api/sentinel/types'
  import type { SearchFormItem } from '@/components/core/forms/art-search-bar/index.vue'
  import type { ColumnOption } from '@/types/component'
  import RiskBadge from '@/components/sentinel/RiskBadge.vue'

  defineOptions({ name: 'SentinelEvents' })

  const router = useRouter()
  const resultsTruncated = ref(false)

  type EventTableResponse = Api.Common.PaginatedResponse<SentinelEvent> & {
    truncated: boolean
  }

  const fetchEventTable = async (params: EventSearchParams): Promise<EventTableResponse> => {
    const response = await fetchEvents(params)
    return {
      records: response.items,
      total: response.total,
      current: response.current,
      size: response.size,
      truncated: response.truncated
    }
  }

  const preserveEventTableMetadata = (response: EventTableResponse) => ({
    records: response.records,
    total: response.total,
    current: response.current,
    size: response.size,
    truncated: response.truncated
  })

  const sourceOptions = [
    { label: '交易监测', value: 'transaction' },
    { label: '行为画像', value: 'behavior' },
    { label: '公开舆情', value: 'news' }
  ]

  const riskOptions = [
    { label: '高风险', value: 'high' },
    { label: '中风险', value: 'medium' },
    { label: '低风险', value: 'low' },
    { label: '未评估', value: 'unassessed' }
  ]

  const searchForm = ref<EventSearchParams>({
    keyword: undefined,
    source: undefined,
    risk_level: undefined,
    event_type: undefined
  })

  const searchItems: SearchFormItem[] = [
    {
      key: 'keyword',
      label: '关键词',
      type: 'input',
      props: { placeholder: '事件 ID / 摘要 / 原文', clearable: true }
    },
    {
      key: 'source',
      label: '来源',
      type: 'select',
      props: { placeholder: '全部来源', clearable: true, options: sourceOptions }
    },
    {
      key: 'risk_level',
      label: '风险',
      type: 'select',
      props: { placeholder: '全部风险', clearable: true, options: riskOptions }
    },
    {
      key: 'event_type',
      label: '类型',
      type: 'input',
      props: { placeholder: '事件类型', clearable: true }
    }
  ]

  const formatDate = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  }

  const sourceLabel = (value: string) =>
    sourceOptions.find((item) => item.value === value)?.label || value

  const columnsFactory = (): ColumnOption<SentinelEvent>[] => [
    { type: 'index', width: 60, label: '序号' },
    { prop: 'event_id', label: '事件 ID', minWidth: 140 },
    { prop: 'summary', label: '摘要', minWidth: 320, showOverflowTooltip: true },
    {
      prop: 'risk_level',
      label: '风险',
      width: 110,
      formatter: (row) => h(RiskBadge, { level: row.risk_level })
    },
    {
      prop: 'risk_score',
      label: '得分',
      width: 90,
      sortable: true,
      formatter: (row) => (row.risk_level === 'unassessed' ? '-' : Math.round(row.risk_score * 100))
    },
    {
      prop: 'source',
      label: '来源',
      width: 120,
      formatter: (row) => sourceLabel(row.source)
    },
    { prop: 'event_type', label: '类型', width: 120 },
    {
      prop: 'timestamp',
      label: '时间',
      minWidth: 180,
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

  const {
    columns,
    columnChecks,
    data,
    loading,
    error,
    pagination,
    getData,
    replaceSearchParams,
    resetSearchParams,
    handleSizeChange,
    handleCurrentChange,
    refreshData
  } = useTable({
    core: {
      apiFn: fetchEventTable,
      apiParams: {
        current: 1,
        size: 20,
        ...searchForm.value
      },
      columnsFactory
    },
    transform: {
      responseAdapter: preserveEventTableMetadata
    },
    hooks: {
      onSuccess: (_items, response) => {
        resultsTruncated.value = Boolean(response.truncated)
      },
      onError: () => {
        resultsTruncated.value = false
      }
    }
  })

  const handleSearch = (params: EventSearchParams) => {
    replaceSearchParams(params)
    getData()
  }

  const handleReset = async () => {
    searchForm.value = {
      keyword: undefined,
      source: undefined,
      risk_level: undefined,
      event_type: undefined
    }
    await resetSearchParams()
  }
</script>

<style scoped>
  .events-error {
    margin-bottom: 16px;
  }

  .events-warning {
    margin-bottom: 16px;
  }
</style>
