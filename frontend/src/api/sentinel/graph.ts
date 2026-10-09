import request from '@/utils/http'
import type { PersonGraph } from './types'

export function fetchPersonGraph(personId: string) {
  return request.get<PersonGraph>({
    url: '/api/graph/person',
    params: { person_id: personId },
    showErrorMessage: false
  })
}

export function fetchEventGraph(eventId: string, signal?: AbortSignal) {
  return request.get<PersonGraph>({
    url: `/api/graph/events/${encodeURIComponent(eventId)}`,
    signal,
    showErrorMessage: false
  })
}
