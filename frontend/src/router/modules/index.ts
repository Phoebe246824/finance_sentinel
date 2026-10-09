import { AppRouteRecord } from '@/types/router'
import { aboutRoutes } from './about'
import { sentinelRoutes } from './sentinel'
import { settingsRoutes } from './settings'

/**
 * 导出所有模块化路由
 */
export const routeModules: AppRouteRecord[] = [sentinelRoutes, settingsRoutes, aboutRoutes]
