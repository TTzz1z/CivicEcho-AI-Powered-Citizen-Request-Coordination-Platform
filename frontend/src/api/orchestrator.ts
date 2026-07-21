import { api } from './client'

export interface OrchestratorPayload {
  message: string
  route_hint?: string
  session_context?: Record<string, unknown>
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

export async function sendOrchestrator(payload: OrchestratorPayload) {
  return (await api.post<{ data: OrchestratorResult }>('/orchestrator/chat', payload)).data.data
}
