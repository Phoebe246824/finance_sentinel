import { AppRouteRecord } from '@/types/router'

export const aboutRoutes: AppRouteRecord = {
  path: '/about',
  name: 'About',
  component: '/about/index',
  meta: {
    title: '关于',
    icon: 'ri:information-line',
    roles: ['R_SUPER', 'R_ADMIN', 'R_ANALYST'],
    keepAlive: false
  }
}
