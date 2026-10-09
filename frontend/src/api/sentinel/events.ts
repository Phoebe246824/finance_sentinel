import request from '@/utils/http'
import type { PaginatedEvents, SentinelEvent } from './types'

export interface EventSearchParams {
  current?: number
  size?: number
  page?: number
  page_size?: number
  source?: string
  risk_level?: string
  event_type?: string
  keyword?: string
}

export function fetchEvents(params: EventSearchParams) {
  return request.get<PaginatedEvents>({ url: '/api/events', params })
}

export function fetchEventDetail(eventId: string, showErrorMessage = true) {
  return request.get<SentinelEvent>({
    url: `/api/events/${eventId}`,
    showErrorMessage
  })
}
