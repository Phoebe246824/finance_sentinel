import { AppRouteRecord } from '@/types/router'

export const sentinelRoutes: AppRouteRecord = {
  name: 'Sentinel',
  path: '/sentinel',
  component: '/index/index',
  meta: {
    title: 'Sentinel',
    icon: 'ri:shield-check-line',
    roles: ['R_SUPER', 'R_ADMIN', 'R_ANALYST']
  },
  children: [
    {
      path: 'dashboard',
      name: 'SentinelDashboard',
      component: '/sentinel/dashboard/overview',
      meta: {
        title: '总览',
        icon: 'ri:dashboard-3-line',
        keepAlive: false,
        fixedTab: true
      }
    },
    {
      path: 'data-screen',
      name: 'SentinelDataScreen',
      component: '/sentinel/dashboard/data-screen',
      meta: {
        title: '态势大屏',
        icon: 'ri:dashboard-horizontal-line',
        keepAlive: false
      }
    },
    {
      path: 'analysis',
      name: 'SentinelAnalysis',
      component: '/sentinel/analysis/workbench',
      meta: {
        title: '风险分析',
        icon: 'ri:pulse-line',
        keepAlive: false
      }
    },
    {
      path: 'blacklist',
      name: 'SentinelBlacklist',
      component: '/sentinel/blacklist/index',
      meta: {
        title: '黑名单管理',
        icon: 'ri:list-check-3',
        keepAlive: true,
        roles: ['R_SUPER', 'R_ADMIN']
      }
    },
    {
      path: 'events',
      name: 'SentinelEvents',
      component: '/sentinel/events/index',
      meta: {
        title: '事件库',
        icon: 'ri:file-list-3-line',
        keepAlive: true
      }
    },
    {
      path: 'events/:eventId',
      name: 'SentinelEventDetail',
      component: '/sentinel/events/detail',
      meta: {
        title: '事件详情',
        isHide: true,
        keepAlive: false
      }
    },
    {
      path: 'graph/person',
      name: 'SentinelPersonGraph',
      component: '/sentinel/graph/person',
      meta: {
        title: '图谱查询',
        icon: 'ri:node-tree',
        keepAlive: false
      }
    }
  ]
}
