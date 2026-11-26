import { ApiError, api } from './client'
import { consumeSseStream, openSseFetch } from './sse'

export interface OrchestratorPayload {
  message: string
  route_hint?: string
  // Round 2 r2-5: per-session identifier — callers should generate a fresh
  // id per conversation (e.g. uuid v4) so turn counters / guard buckets /
  // ai_usage_logs are isolated per session, never shared via "user:default".
  session_id?: string
}

export interface OrchestratorResult {
  primary_intent: string
  route: string
  confidence: number
  in_domain: boolean
  requires_llm: boolean
  model_tier: string
  estimated_cost_level: string
  rejection_reason: string
  urgency: string
  sensitive_flags: string[]
  routing_reason: string
  should_create_ticket: boolean
  should_clarify: boolean
  clarify_question?: string | null
  message: string
  payload: Record<string, unknown>
  cache_hit: boolean
  degraded: boolean
  degrade_reason: string
  rate_limited: boolean
  budget_exceeded: boolean
}

export interface OrchestratorStreamMeta {
  primary_intent: string
  route: string
  confidence: number
  in_domain: boolean
  requires_llm: boolean
  model_tier: string
  estimated_cost_level: string
  rejection_reason: string
  urgency: string
  sensitive_flags: string[]
  routing_reason: string
  should_create_ticket: boolean
  should_clarify: boolean
  clarify_question?: string | null
  payload: Record<string, unknown>
  session_id?: string
  advisory_only?: boolean
}

export interface OrchestratorStreamDone extends OrchestratorResult {
  session_id?: string
  latency_ms?: number
  advisory_only?: boolean
}

export interface OrchestratorStreamHandlers {
  onMeta?: (meta: OrchestratorStreamMeta) => void
  onDelta?: (text: string) => void
  onDone?: (done: OrchestratorStreamDone) => void
  onError?: (err: { code: string; message: string }) => void
}

export async function sendOrchestrator(payload: OrchestratorPayload, signal?: AbortSignal) {
  return (await api.post<{ data: OrchestratorResult }>('/orchestrator/chat', payload, { signal })).data.data
}

export async function streamOrchestratorChat(
  payload: OrchestratorPayload,
  handlers: OrchestratorStreamHandlers = {},
  signal?: AbortSignal,
): Promise<OrchestratorStreamDone> {
  const response = await openSseFetch('/api/v1/orchestrator/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    clearAuthOn401: false,
  })
  if (!response.body) {
    throw new ApiError(0, 'STREAM_INCOMPLETE', '流式响应不可用，请重试')
  }

  const state: { done: OrchestratorStreamDone | null; err: ApiError | null } = {
    done: null,
    err: null,
  }

  await consumeSseStream(
    response.body,
    ev => {
      if (!ev.data) return
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(ev.data) as Record<string, unknown>
      } catch {
        return
      }
      if (ev.event === 'meta') {
        handlers.onMeta?.(parsed as unknown as OrchestratorStreamMeta)
      } else if (ev.event === 'delta') {
        if (typeof parsed.text === 'string') handlers.onDelta?.(parsed.text)
      } else if (ev.event === 'done') {
        const done = parsed as unknown as OrchestratorStreamDone
        state.done = done
        handlers.onDone?.(done)
      } else if (ev.event === 'error') {
        const code = typeof parsed.code === 'string' ? parsed.code : 'STREAM_ERROR'
        const message = typeof parsed.message === 'string' ? parsed.message : '智能对话流式输出暂时不可用，请重试。'
        handlers.onError?.({ code, message })
        state.err = new ApiError(500, code, message)
      }
    },
    signal,
  )

  if (state.err) throw state.err
  if (!state.done) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    throw new ApiError(0, 'STREAM_INCOMPLETE', '流式响应意外中断，请重试')
  }
  return state.done
}
