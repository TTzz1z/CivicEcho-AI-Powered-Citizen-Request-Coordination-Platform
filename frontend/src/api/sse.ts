import { ApiError, createRequestId, tokenStore } from './client'
import type { ApiErrorBody } from '../types'

export interface SseEvent {
  id?: string
  event: string
  data: string
}

export interface OpenSseFetchInit extends RequestInit {
  clearAuthOn401?: boolean
}

function parseSseBlock(rawBlock: string): SseEvent | null {
  const lines = rawBlock.split('\n')
  let eventName = 'message'
  let id: string | undefined
  const dataLines: string[] = []
  let hasField = false

  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') {
      eventName = value || 'message'
      hasField = true
    } else if (field === 'id') {
      if (!value.includes('\0')) {
        id = value
        hasField = true
      }
    } else if (field === 'data') {
      dataLines.push(value)
      hasField = true
    }
  }

  if (!hasField) return null
  return {
    ...(id !== undefined ? { id } : {}),
    event: eventName,
    data: dataLines.join('\n'),
  }
}

export async function consumeSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const normalizeChunkBuffer = (flushTrailingCr: boolean) => {
    let normalized = buffer.replace(/\r\n/g, '\n')
    if (!flushTrailingCr && normalized.endsWith('\r')) {
      const head = normalized.slice(0, -1).replace(/\r/g, '\n')
      buffer = `${head}\r`
      return
    }
    buffer = normalized.replace(/\r/g, '\n')
  }

  const drainCompleteBlocks = () => {
    let sepIndex = buffer.indexOf('\n\n')
    while (sepIndex !== -1) {
      const block = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      const parsed = parseSseBlock(block)
      if (parsed) onEvent(parsed)
      sepIndex = buffer.indexOf('\n\n')
    }
  }

  const onAbort = () => {
    try {
      void reader.cancel().catch(() => undefined)
    } catch {
      // Ignore synchronous cancellation errors.
    }
  }
  if (signal) {
    if (signal.aborted) {
      onAbort()
    } else {
      signal.addEventListener('abort', onAbort, { once: true })
    }
  }

  try {
    while (true) {
      if (signal?.aborted) break
      const { value, done } = await reader.read()
      if (done) break
      if (value) {
        buffer += decoder.decode(value, { stream: true })
        normalizeChunkBuffer(false)
        drainCompleteBlocks()
      }
    }

    if (!signal?.aborted) {
      buffer += decoder.decode()
      normalizeChunkBuffer(true)
      drainCompleteBlocks()
      const trailing = buffer.trimEnd()
      if (trailing) {
        const parsed = parseSseBlock(trailing)
        if (parsed) onEvent(parsed)
      }
    }
  } finally {
    signal?.removeEventListener('abort', onAbort)
    try {
      await reader.cancel()
    } catch {
      // Ignore stream cancellation errors during cleanup.
    }
    reader.releaseLock()
  }
}

export async function openSseFetch(url: string, init: OpenSseFetchInit = {}): Promise<Response> {
  const { clearAuthOn401 = false, headers: initHeaders, ...rest } = init
  const headers = new Headers(initHeaders)
  if (!headers.has('Accept')) headers.set('Accept', 'text/event-stream')
  if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', createRequestId())
  const token = tokenStore.get()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, {
    ...rest,
    headers,
  })

  if (!response.ok) {
    let body: ApiErrorBody | undefined
    try {
      const text = await response.text()
      if (text) {
        const parsed = JSON.parse(text) as { error?: ApiErrorBody }
        body = parsed?.error
      }
    } catch {
      body = undefined
    }
    if (response.status === 401 && clearAuthOn401) {
      tokenStore.clear()
      window.dispatchEvent(new Event('tingting:unauthorized'))
    }
    const fallbackMessage = response.status === 429
      ? '请求过于频繁，请稍后重试'
      : response.status >= 500
        ? '服务暂时不可用，请稍后重试'
        : '请求未能完成'
    throw new ApiError(
      response.status,
      body?.code || (response.status === 429 ? 'RATE_LIMITED' : 'NETWORK_ERROR'),
      body?.message || fallbackMessage,
      body?.details,
    )
  }

  return response
}
