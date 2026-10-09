import { AppRouteRecord } from '@/types/router'

export const settingsRoutes: AppRouteRecord = {
  path: '/settings',
  name: 'Settings',
  component: '/settings/runtime/index',
  meta: {
    title: '设置',
    icon: 'ri:settings-3-line',
    roles: ['R_SUPER', 'R_ADMIN'],
    keepAlive: false
  }
}
