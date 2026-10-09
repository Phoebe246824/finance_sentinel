<template>
  <div class="person-graph-page">
    <ElCard shadow="never">
      <div class="query-bar">
        <ElInput
          v-model="personId"
          placeholder="输入人员 ID"
          clearable
          @clear="clearGraphQuery"
          @keyup.enter="loadGraph"
        />
        <ElButton type="primary" :loading="loading" @click="loadGraph">查询</ElButton>
      </div>
    </ElCard>

    <ElCard shadow="never">
      <template #header>
        <div class="graph-head">
          <span>人物关系图谱</span>
          <small v-if="graph">
            {{ graph.nodes.length }} 个节点 / {{ graph.edges.length }} 条边
          </small>
        </div>
      </template>
      <ElSkeleton v-if="loading" :rows="6" animated />
      <ElAlert
        v-else-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />
      <SentinelGraphViewer v-else-if="graph && graph.nodes.length > 0" :graph="graph" />
      <ElEmpty v-else-if="queried" description="该人员暂无图谱关系" />
      <ElEmpty v-else description="请输入人员 ID 查询图谱" />
    </ElCard>
  </div>
</template>

<script setup lang="ts">
  import { fetchPersonGraph } from '@/api/sentinel/graph'
  import type { PersonGraph } from '@/api/sentinel/types'

  defineOptions({ name: 'SentinelPersonGraph' })

  const personId = ref('')
  const loading = ref(false)
  const queried = ref(false)
  const graph = ref<PersonGraph>()
  const errorMessage = ref('')
  let requestVersion = 0

  const clearGraphQuery = () => {
    requestVersion += 1
    graph.value = undefined
    queried.value = false
    loading.value = false
    errorMessage.value = ''
  }

  const loadGraph = async () => {
    const id = personId.value.trim()
    const currentVersion = ++requestVersion
    if (!id) {
      clearGraphQuery()
      return
    }
    loading.value = true
    queried.value = true
    errorMessage.value = ''
    try {
      const nextGraph = await fetchPersonGraph(id)
      if (currentVersion === requestVersion) {
        graph.value = nextGraph
      }
    } catch (error) {
      if (currentVersion === requestVersion) {
        graph.value = undefined
        errorMessage.value = error instanceof Error ? error.message : '图谱查询失败'
        ElMessage.error(errorMessage.value)
      }
    } finally {
      if (currentVersion === requestVersion) {
        loading.value = false
      }
    }
  }

  watch(personId, () => {
    clearGraphQuery()
  })
</script>

<style scoped>
  .person-graph-page {
    display: grid;
    gap: 16px;
  }

  .query-bar {
    display: grid;
    grid-template-columns: minmax(220px, 360px) auto;
    gap: 12px;
    justify-content: start;
  }

  .graph-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .graph-head small {
    color: var(--el-text-color-secondary);
  }

  @media (max-width: 640px) {
    .query-bar {
      grid-template-columns: 1fr;
    }
  }
</style>
