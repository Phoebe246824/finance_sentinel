import request from '@/utils/http'
import type {
  BlacklistEventDeletePayload,
  BlacklistEventMutationResult,
  BlacklistEventSavePayload,
  BlacklistEventSampleItem,
  BlacklistKeywordBatchPayload,
  BlacklistKeywordItem,
  BlacklistPersonBatchPayload,
  BlacklistPersonItem,
  BlacklistSearchParams,
  PaginatedBlacklist
} from './types'

interface BlacklistBatchResult {
  created: number
  updated: number
  deleted: number
}

export function fetchBlacklistPersons(params: BlacklistSearchParams) {
  return request.get<PaginatedBlacklist<BlacklistPersonItem>>({
    url: '/api/blacklist/persons',
    params
  })
}

export function saveBlacklistPersons(payload: BlacklistPersonBatchPayload) {
  return request.post<BlacklistBatchResult>({
    url: '/api/blacklist/persons:batch',
    data: payload,
    showErrorMessage: false
  })
}

export function fetchBlacklistKeywords(params: BlacklistSearchParams) {
  return request.get<PaginatedBlacklist<BlacklistKeywordItem>>({
    url: '/api/blacklist/keywords',
    params
  })
}

export function saveBlacklistKeywords(payload: BlacklistKeywordBatchPayload) {
  return request.post<BlacklistBatchResult>({
    url: '/api/blacklist/keywords:batch',
    data: payload,
    showErrorMessage: false
  })
}

export function fetchBlacklistEvents(params: BlacklistSearchParams) {
  return request.get<PaginatedBlacklist<BlacklistEventSampleItem>>({
    url: '/api/blacklist/events',
    params
  })
}

export function createBlacklistEvent(payload: BlacklistEventSavePayload) {
  return request.post<BlacklistEventMutationResult>({
    url: '/api/blacklist/events',
    data: payload,
    showErrorMessage: false
  })
}

export function updateBlacklistEvent(sampleId: string, payload: BlacklistEventSavePayload) {
  return request.put<BlacklistEventMutationResult>({
    url: `/api/blacklist/events/${encodeURIComponent(sampleId)}`,
    data: payload,
    showErrorMessage: false
  })
}

export function setBlacklistEventEnabled(
  sampleId: string,
  enabled: boolean,
  expectedUpdatedAt: string
) {
  return request.request<BlacklistEventMutationResult>({
    url: `/api/blacklist/events/${encodeURIComponent(sampleId)}/enabled`,
    method: 'PATCH',
    data: { enabled, expected_updated_at: expectedUpdatedAt },
    showErrorMessage: false
  })
}

export function deleteBlacklistEvent(sampleId: string, payload: BlacklistEventDeletePayload) {
  return request.del<{ deleted: number }>({
    url: `/api/blacklist/events/${encodeURIComponent(sampleId)}`,
    params: payload,
    showErrorMessage: false
  })
}
