import request from '@/utils/http'
import type { AnalysisTask, SentinelEvent } from './types'
import { fetchEventDetail } from './events'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''
const STREAM_RECONNECT_TIMEOUT_MS = 30_000

interface TaskStreamToken {
  token: string
  expires_in_seconds: number
}

interface AnalysisTaskWatcher {
  close: () => void
}

export function buildSentinelApiUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const normalizedBase = API_BASE_URL.replace(/\/+$/, '')
  if (!normalizedBase) return normalizedPath
  return `${normalizedBase}${normalizedPath}`
}

export function createAnalysisTask(text: string, signal?: AbortSignal) {
  return request.post<AnalysisTask>({
    url: '/api/tasks/analyze',
    data: { text },
    signal,
    showErrorMessage: false
  })
}

export function createAnalysisTaskStreamToken(taskId: string) {
  return request.post<TaskStreamToken>({
    url: `/api/tasks/${taskId}/stream-token`,
    showErrorMessage: false
  })
}

export async function watchAnalysisTask(
  taskId: string,
  onUpdate: (task: AnalysisTask) => void,
  onError?: (error: Error) => void
): Promise<AnalysisTaskWatcher> {
  const { token } = await createAnalysisTaskStreamToken(taskId)
  const query = `?token=${encodeURIComponent(token)}`
  const source = new EventSource(buildSentinelApiUrl(`/api/tasks/${taskId}/stream${query}`))
  let closedByClient = false
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = undefined
    }
  }

  const close = () => {
    closedByClient = true
    clearReconnectTimer()
    source.close()
  }

  source.addEventListener('open', clearReconnectTimer)
  source.addEventListener('update', (event) => {
    clearReconnectTimer()
    onUpdate(JSON.parse(event.data) as AnalysisTask)
  })
  source.onerror = () => {
    if (closedByClient) return
    if (source.readyState === EventSource.CLOSED) {
      close()
      onError?.(new Error('分析任务连接已关闭，请重试'))
      return
    }
    reconnectTimer ??= setTimeout(() => {
      if (closedByClient) return
      close()
      onError?.(new Error('分析任务连接中断，请重试'))
    }, STREAM_RECONNECT_TIMEOUT_MS)
  }
  return {
    close
  }
}

export async function analyzeText(
  text: string,
  onUpdate: (task: AnalysisTask) => void,
  signal?: AbortSignal
): Promise<SentinelEvent> {
  if (signal?.aborted) throw new Error('分析任务已取消')
  const task = await createAnalysisTask(text, signal)
  if (signal?.aborted) throw new Error('分析任务已取消')
  onUpdate(task)

  return new Promise((resolve, reject) => {
    let settled = false
    let watcher: AnalysisTaskWatcher | undefined

    function cleanup() {
      signal?.removeEventListener('abort', abort)
      watcher?.close()
    }

    function rejectOnce(error: Error) {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }

    function abort() {
      rejectOnce(new Error('分析任务已取消'))
    }

    signal?.addEventListener('abort', abort, { once: true })

    watchAnalysisTask(
      task.task_id,
      (current) => {
        onUpdate(current)
        if (current.status === 'failed') {
          rejectOnce(new Error(current.error_message || '分析任务失败'))
          return
        }
        if (current.status === 'cancelled') {
          rejectOnce(new Error('分析任务已取消'))
          return
        }
        if (current.status === 'success') {
          settled = true
          cleanup()
          if (!current.event_id) {
            reject(new Error('分析完成但未返回事件 ID'))
            return
          }
          fetchEventDetail(current.event_id, false).then(resolve).catch(reject)
        }
      },
      rejectOnce
    )
      .then((nextWatcher) => {
        watcher = nextWatcher
        if (settled || signal?.aborted) watcher.close()
      })
      .catch(rejectOnce)
  })
}
