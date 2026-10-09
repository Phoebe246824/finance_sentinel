<template>
  <div class="about-page">
    <ElCard shadow="never" class="hero-card">
      <div class="hero-content">
        <div class="hero-copy">
          <p class="eyebrow">Sentinel Control Surface</p>
          <h1>关于 Sentinel WebUI</h1>
          <p class="subtitle">
            一个把风险分析、事件回看、图谱线索和运行时配置放进同一工作台的操作界面。
          </p>
          <p class="description">
            当前 WebUI
            面向分析员和管理员，支持提交实时分析任务、查看持久化结果、追踪知识图谱入口，并在本地环境里调整模型供应商、依赖服务和运行时参数。
          </p>
        </div>
        <div class="hero-stats">
          <div class="stat-card">
            <strong>4</strong>
            <span>核心工作区</span>
          </div>
          <div class="stat-card">
            <strong>FastAPI</strong>
            <span>后端接口</span>
          </div>
          <div class="stat-card">
            <strong>ArtD</strong>
            <span>前端基底</span>
          </div>
        </div>
      </div>
    </ElCard>

    <ElRow :gutter="16">
      <ElCol :xs="24" :lg="12">
        <ElCard shadow="never">
          <template #header>
            <span>快速链接</span>
          </template>
          <div class="link-list">
            <button
              v-for="link in links"
              :key="link.label"
              class="link-item"
              @click="openLink(link.url)"
            >
              <span>
                <strong>{{ link.label }}</strong>
                <small>{{ link.hint }}</small>
              </span>
              <ArtSvgIcon icon="ri:arrow-right-up-line" class="link-icon" />
            </button>
          </div>
        </ElCard>
      </ElCol>

      <ElCol :xs="24" :lg="12">
        <ElCard shadow="never">
          <template #header>
            <span>页面说明</span>
          </template>
          <div class="guide-list">
            <div v-for="item in guides" :key="item.title" class="guide-item">
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
            </div>
          </div>
        </ElCard>
      </ElCol>
    </ElRow>

    <ElCard shadow="never">
      <template #header>
        <span>技术栈</span>
      </template>
      <div class="stack-grid">
        <div class="stack-item">
          <strong>前端</strong>
          <p>Vue 3、TypeScript、Vite、Element Plus、Art Design Pro</p>
        </div>
        <div class="stack-item">
          <strong>后端</strong>
          <p>FastAPI、Sentinel Pipeline、Milvus、Neo4j、CrewAI Flow</p>
        </div>
      </div>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
  import { SENTINEL_LINKS } from '@/utils/constants'

  defineOptions({ name: 'SentinelAboutPage' })

  const links = [
    { label: '项目仓库', hint: '查看源码与提交历史', url: SENTINEL_LINKS.REPOSITORY },
    { label: '开发文档', hint: '了解开发准则和模块边界', url: SENTINEL_LINKS.DEVELOPMENT_DOCS },
    { label: '命令说明', hint: '启动、测试与构建入口', url: SENTINEL_LINKS.COMMANDS_DOCS },
    { label: '环境变量', hint: '核对配置来源和覆盖优先级', url: SENTINEL_LINKS.ENV_VARS_DOCS }
  ]

  const guides = [
    { title: '总览', description: '查看近期事件、风险分布和来源分布，快速判断当前运行态势。' },
    {
      title: '风险分析',
      description: '提交待分析文本，观察任务进度，并在任务完成后查看结构化结果。'
    },
    {
      title: '事件库',
      description: '检索和回看已经持久化的分析结果，支持按来源、风险和关键词筛选。'
    },
    { title: '图谱查询', description: '进入人员图谱入口，后续可继续延伸更多知识图谱可视化能力。' },
    { title: '设置', description: '修改模型、依赖服务和运行时参数；保存后仅影响后续新任务。' }
  ]

  const openLink = (url: string) => {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
</script>

<style scoped>
  .about-page {
    display: grid;
    gap: 16px;
  }

  .hero-card :deep(.el-card__body) {
    padding: 28px;
  }

  .hero-content {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
    gap: 20px;
  }

  .eyebrow {
    margin: 0;
    color: var(--el-color-primary);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .hero-copy h1 {
    margin: 10px 0 0;
    font-size: 34px;
    font-weight: 700;
  }

  .subtitle {
    margin: 14px 0 0;
    color: var(--el-text-color-primary);
    font-size: 16px;
    line-height: 1.8;
  }

  .description {
    margin: 12px 0 0;
    color: var(--el-text-color-regular);
    line-height: 1.8;
  }

  .hero-stats {
    display: grid;
    gap: 12px;
  }

  .stat-card {
    display: grid;
    gap: 6px;
    padding: 16px;
    border: 1px solid var(--art-card-border);
    border-radius: 16px;
    background: linear-gradient(
      135deg,
      color-mix(in srgb, var(--el-color-primary) 7%, var(--default-box-color)) 0%,
      var(--default-box-color) 100%
    );
  }

  .stat-card strong {
    color: var(--el-text-color-primary);
    font-size: 24px;
    font-weight: 700;
  }

  .stat-card span {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .link-list,
  .guide-list {
    display: grid;
    gap: 12px;
  }

  .link-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 14px 16px;
    border: 1px solid var(--el-border-color);
    border-radius: 14px;
    background: var(--el-fill-color-extra-light);
    cursor: pointer;
    text-align: left;
  }

  .link-item span,
  .guide-item {
    display: grid;
    gap: 4px;
  }

  .link-item small,
  .guide-item p {
    color: var(--el-text-color-secondary);
    line-height: 1.7;
  }

  .link-item strong,
  .guide-item strong {
    font-size: 15px;
  }

  .link-icon {
    font-size: 18px;
    color: var(--el-text-color-secondary);
  }

  .guide-item {
    padding: 14px 16px;
    border-radius: 14px;
    background: var(--el-fill-color-extra-light);
  }

  .guide-item p,
  .stack-item p {
    margin: 0;
  }

  .stack-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
  }

  .stack-item {
    display: grid;
    gap: 8px;
    padding: 16px;
    border: 1px solid var(--el-border-color);
    border-radius: 14px;
  }

  .stack-item p {
    color: var(--el-text-color-secondary);
    line-height: 1.8;
  }

  @media (max-width: 960px) {
    .hero-content,
    .stack-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
