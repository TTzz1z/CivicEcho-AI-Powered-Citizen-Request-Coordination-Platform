import axios, { AxiosError } from 'axios'
import type { ApiErrorBody } from '../types'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: ApiErrorBody['details']) { super(message); this.name = 'ApiError' }
}

export const tokenStore = {
  get: () => sessionStorage.getItem('tingting_access_token'),
  set: (token: string) => sessionStorage.setItem('tingting_access_token', token),
  clear: () => sessionStorage.removeItem('tingting_access_token'),
}

export const api = axios.create({ baseURL: '/api/v1', timeout: 12_000 })
export function createRequestId(){return crypto.randomUUID().replaceAll('-','')}
api.interceptors.request.use(config => {
  const token = tokenStore.get()
  if (token && !config.headers.has('Authorization')) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Request-ID'] = createRequestId()
  return config
})

async function extractErrorPayload(data: unknown): Promise<ApiErrorBody | undefined> {
  if (!data) return undefined
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    try {
      const text = typeof data.text === 'function' ? await data.text() : await new Response(data).text()
      const parsed = JSON.parse(text) as { error?: ApiErrorBody }
      return parsed?.error
    } catch {
      return undefined
    }
  }
  if (typeof data === 'object' && 'error' in data) {
    return (data as { error?: ApiErrorBody }).error
  }
  return undefined
}

export function extractDispositionFilename(disposition: string | undefined, fallback: string): string {
  const encoded = disposition?.match(/filename\*=UTF-8'[^']*'([^;]+)/i)?.[1]
  if (encoded) {
    try {
      const decoded = decodeURIComponent(encoded).trim()
      if (decoded) return decoded
    } catch {
      // Fall through to plain filename match.
    }
  }
  const plain = disposition?.match(/filename="?([^";]+)"?/i)?.[1]?.trim()
  return plain || fallback
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function formatApiErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback
  if (
    error.code === 'EXPORT_RATE_LIMITED'
    && error.details
    && !Array.isArray(error.details)
    && typeof error.details.retry_after === 'number'
  ) {
    return `${error.message}（约 ${error.details.retry_after} 秒后可重试）`
  }
  return error.message || fallback
}

api.interceptors.response.use(r => r, async (error: AxiosError<{error?: ApiErrorBody} | Blob>) => {
  const status = error.response?.status ?? 0
  const body = await extractErrorPayload(error.response?.data)
  const token = tokenStore.get()
  if (status === 401 && token && error.config?.headers.get('Authorization') === `Bearer ${token}`) {
    tokenStore.clear()
    window.dispatchEvent(new Event('tingting:unauthorized'))
  }
  const message = body?.message || (status === 429 ? '请求过于频繁，请稍后重试' : status >= 500 ? '服务暂时不可用，请稍后重试' : status === 0 ? '网络连接失败，请检查服务状态' : '请求未能完成')
  return Promise.reject(new ApiError(status, body?.code || (status === 429 ? 'RATE_LIMITED' : 'NETWORK_ERROR'), message, body?.details))
})
