import request from '@/utils/http'
import type { DashboardOverview } from './types'

export function fetchDashboardOverview() {
  return request.get<DashboardOverview>({ url: '/api/dashboard/overview' })
}
