import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, extractDispositionFilename, formatApiErrorMessage, tokenStore } from './client'
import { consumeSseStream, openSseFetch, type SseEvent } from './sse'

function streamFromChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk)
      }
      controller.close()
    },
  })
}

describe('SSE & download helpers', () => {
  afterEach(() => {
    sessionStorage.clear()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('parses chunked UTF-8 Chinese text and CRLF split across frames', async () => {
    const encoder = new TextEncoder()
    const payload = encoder.encode(': keepalive\r\nid: 101\r\nevent: delta\r\ndata: {"text":"政务"}\r\n\r\nevent: message\ndata: line1\ndata: line2')
    // Split mid-UTF-8 byte and mid-CRLF
    const chunks = [
      payload.slice(0, 12),
      payload.slice(12, 34),
      payload.slice(34, 48),
      payload.slice(48),
    ]
    const events: SseEvent[] = []
    await consumeSseStream(streamFromChunks(chunks), ev => events.push(ev))

    expect(events).toEqual([
      { id: '101', event: 'delta', data: '{"text":"政务"}' },
      { event: 'message', data: 'line1\nline2' },
    ])
  })

  it('openSseFetch injects bearer token and dispatches unauthorized on 401', async () => {
    tokenStore.set('secret-jwt')
    const onUnauthorized = vi.fn()
    window.addEventListener('tingting:unauthorized', onUnauthorized)

    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: 'AUTH_EXPIRED', message: '登录已过期' } }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(openSseFetch('/api/v1/notifications/stream', { clearAuthOn401: true }))
      .rejects.toMatchObject({ status: 401, code: 'AUTH_EXPIRED', message: '登录已过期' })

    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer secret-jwt')
    expect(headers.get('Accept')).toBe('text/event-stream')
    expect(headers.get('X-Request-ID')).toBeTruthy()
    expect(tokenStore.get()).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)

    window.removeEventListener('tingting:unauthorized', onUnauthorized)
  })

  it('extractDispositionFilename handles RFC 5987 (with or without language tag) and quoted filenames', () => {
    expect(extractDispositionFilename("attachment; filename*=UTF-8''%E5%B7%A5%E5%8D%95.csv", 'fallback.csv')).toBe('工单.csv')
    expect(extractDispositionFilename("attachment; filename*=UTF-8'zh-CN'%E6%B5%8B%E8%AF%95.csv; filename=\"fallback.csv\"", 'fallback.csv')).toBe('测试.csv')
    expect(extractDispositionFilename('attachment; filename="tickets-export-20261126.csv"', 'fallback.csv')).toBe('tickets-export-20261126.csv')
    expect(extractDispositionFilename(undefined, 'fallback.csv')).toBe('fallback.csv')
  })

  it('aborts consumeSseStream promptly while reader.read() is pending', async () => {
    let cancelCalled = false
    const pendingStream = new ReadableStream<Uint8Array>({
      pull() {
        return new Promise(() => {})
      },
      cancel() {
        cancelCalled = true
      },
    })
    const controller = new AbortController()
    const events: SseEvent[] = []
    const consumePromise = consumeSseStream(pendingStream, ev => events.push(ev), controller.signal)

    setTimeout(() => controller.abort(), 20)
    await expect(
      Promise.race([
        consumePromise.then(() => 'resolved'),
        new Promise<string>(resolve => setTimeout(() => resolve('timed_out'), 500)),
      ]),
    ).resolves.toBe('resolved')

    expect(cancelCalled).toBe(true)
    expect(events).toEqual([])
  })

  it('formatApiErrorMessage surfaces EXPORT_RATE_LIMITED retry_after', () => {
    const err = new ApiError(429, 'EXPORT_RATE_LIMITED', '导出请求过于频繁，请稍后重试', { retry_after: 42 })
    expect(formatApiErrorMessage(err, '导出失败')).toBe('导出请求过于频繁，请稍后重试（约 42 秒后可重试）')
  })
})
