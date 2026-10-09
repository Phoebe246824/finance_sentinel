import request from '@/utils/http'
import type {
  RuntimeAvailabilityCheckResponse,
  RuntimeSettingsResponse,
  RuntimeSettingsUpdatePayload
} from './types'

const SERVICE_CHECK_TIMEOUT_MS = 30000
const MODEL_CHECK_TIMEOUT_MS = 60000

export function fetchRuntimeSettings() {
  return request.get<RuntimeSettingsResponse>({ url: '/api/settings/runtime' })
}

export function saveRuntimeSettings(data: RuntimeSettingsUpdatePayload) {
  return request.put<RuntimeSettingsResponse>({
    url: '/api/settings/runtime',
    data,
    showSuccessMessage: true
  })
}

export function checkRuntimeServices() {
  return request.post<RuntimeAvailabilityCheckResponse>({
    url: '/api/settings/runtime/checks/services',
    timeout: SERVICE_CHECK_TIMEOUT_MS,
    showErrorMessage: false
  })
}

export function checkRuntimeModels() {
  return request.post<RuntimeAvailabilityCheckResponse>({
    url: '/api/settings/runtime/checks/models',
    timeout: MODEL_CHECK_TIMEOUT_MS,
    showErrorMessage: false
  })
}
