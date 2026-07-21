import { api } from './client'

export interface AiUsageStats {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost_rmb: number
  cache_hit_count: number
  cache_hit_rate: number
  rate_limited_count: number
  degraded_count: number
  failed_count: number
  out_of_scope_blocked_count: number
  usage_unavailable_count: number
  avg_latency_ms: number
  by_route: { route: string; calls: number; tokens: number; cost: number }[]
  by_role: { role: string; calls: number; tokens: number; cost: number }[]
  by_tier: { tier: string; calls: number; tokens: number; cost: number }[]
  by_capability: { capability: string; calls: number; tokens: number; cost: number }[]
  by_provider: { provider: string; calls: number; tokens: number; cost: number }[]
  by_model: { model: string; calls: number; tokens: number; cost: number }[]
  by_degrade_reason: { reason: string; count: number }[]
  timeseries: {
    date: string
    calls: number
    tokens: number
    cost: number
    cache_hits: number
    degraded: number
    rate_limited: number
  }[]
}

export interface AiUsageLogItem {
  id: number
  request_id: string
  user_id: number | null
  role: string | null
  route: string | null
  model_name: string
  model_tier: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  latency_ms: number
  cache_hit: boolean
  rate_limited: boolean
  degraded: boolean
  estimated_cost_rmb: number
  success: boolean
  error: string | null
  created_at: string
  // Round 2 fields
  session_id: string | null
  capability: string | null
  provider: string | null
  usage_unavailable: boolean
  degrade_reason: string | null
  budget_exceeded: boolean
  error_code: string | null
  text_count: number | null
  text_chars: number | null
}

export interface AiUsageLogsPage {
  items: AiUsageLogItem[]
  total: number
  page: number
  page_size: number
}

export async function getAiUsageStats(days = 7): Promise<AiUsageStats> {
  return (await api.get<{ data: AiUsageStats }>('/admin/ai-usage/stats', { params: { days } })).data.data
}

export async function getAiUsageLogs(params: {
  page?: number
  page_size?: number
  route?: string
  model_tier?: string
  role?: string
  capability?: string
  provider?: string
  session_id?: string
  success?: boolean
  degraded?: boolean
} = {}): Promise<AiUsageLogsPage> {
  return (await api.get<{ data: AiUsageLogsPage }>('/admin/ai-usage/logs', { params })).data.data
}
