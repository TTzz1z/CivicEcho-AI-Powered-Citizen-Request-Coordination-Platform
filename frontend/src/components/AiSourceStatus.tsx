import { Space, Tag, Typography } from 'antd'

const reasonLabels: Record<string, string> = {
  no_evidence: '未找到可靠依据', llm_unavailable: '模型暂不可用', llm_call_failed: '模型调用失败',
  TimeoutError: '模型响应超时', URLError: '模型连接失败', http_429: '模型请求限流', http_500: '模型服务异常',
  kb_unavailable: '知识库暂不可用', schema_validation_failed: '模型输出格式未通过校验',
  citation_validation_failed: '引用未通过校验', budget_exceeded: '达到模型调用额度',
}

export function AiSourceStatus({ provider, model, degraded, reason, noEvidence, latencyMs }: {
  provider?: string | null
  model?: string | null
  degraded?: boolean
  reason?: string | null
  noEvidence?: boolean
  latencyMs?: number | null
}) {
  const rules = provider === 'rules'
  const unknown = !provider || provider === 'unknown'
  const label = noEvidence ? '无可用证据' : rules ? degraded ? '规则降级' : '规则辅助' : unknown ? '来源未知' : '模型生成'
  return <Space className="ai-source-status" size={[8, 4]} wrap aria-label="建议来源">
    <Tag color={noEvidence || degraded ? 'warning' : rules || unknown ? 'default' : 'processing'}>{label}</Tag>
    {!rules && !unknown && <Typography.Text type="secondary">{[provider, model].filter(Boolean).join(' · ')}</Typography.Text>}
    {reason && reason !== 'no_evidence' && <Typography.Text type="secondary">{reasonLabels[reason] ?? '已切换到可用路径'}</Typography.Text>}
    {latencyMs != null && latencyMs >= 0 && <Typography.Text type="secondary">{latencyMs} ms</Typography.Text>}
  </Space>
}
