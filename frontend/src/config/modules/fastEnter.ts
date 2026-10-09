/**
 * 快速入口配置
 * 包含：应用列表、快速链接等配置
 */
import type { FastEnterConfig } from '@/types/config'

const fastEnterConfig: FastEnterConfig = {
  // 显示条件（屏幕宽度）
  minWidth: 1200,
  // 应用列表
  applications: [
    {
      name: 'Sentinel 总览',
      description: '舆情态势与风险分布',
      icon: 'ri:dashboard-3-line',
      iconColor: '#377dff',
      enabled: true,
      order: 1,
      routeName: 'SentinelDashboard'
    },
    {
      name: '风险分析',
      description: '提交文本并跟踪分析流水线',
      icon: 'ri:pulse-line',
      iconColor: '#ff3b30',
      enabled: true,
      order: 2,
      routeName: 'SentinelAnalysis'
    },
    {
      name: '事件库',
      description: '检索和查看事件详情',
      icon: 'ri:file-list-3-line',
      iconColor: '#7A7FFF',
      enabled: true,
      order: 3,
      routeName: 'SentinelEvents'
    },
    {
      name: '图谱查询',
      description: '查看人物关联知识图谱',
      icon: 'ri:node-tree',
      iconColor: '#13DEB9',
      enabled: true,
      order: 4,
      routeName: 'SentinelPersonGraph'
    }
  ],
  // 快速链接
  quickLinks: [
    {
      name: '登录',
      enabled: true,
      order: 1,
      routeName: 'Login'
    },
    {
      name: 'Sentinel 总览',
      enabled: true,
      order: 2,
      routeName: 'SentinelDashboard'
    },
    {
      name: '风险分析',
      enabled: true,
      order: 3,
      routeName: 'SentinelAnalysis'
    }
  ]
}

export default Object.freeze(fastEnterConfig)
