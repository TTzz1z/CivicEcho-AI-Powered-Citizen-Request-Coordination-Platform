import { useMemo, useState } from 'react'
import { Card, Col, Empty, Input, Row, Select, Spin, Statistic, Table, Tabs, Tag, Typography } from 'antd'
import {
  ApiOutlined, CheckCircleOutlined, ClockCircleOutlined, DollarOutlined,
  FireOutlined, SafetyOutlined, StopOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { getAiUsageLogs, getAiUsageStats, type AiUsageLogItem, type AiUsageStats } from '../api/aiUsage'
import { ChartPanel } from '../components/ChartPanel'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'

const ROUTE_LABELS: Record<string, string> = {
  policy_rag: '政策咨询', service_guide: '办事指南', ticket_intake: '投诉/报修',
  suggestion_intake: '意见建议', ticket_progress: '工单查询',
  department_navigation: '部门导航', emergency_route: '紧急事项',
  general_chat: '日常对话', human_handoff: '人工服务', clarify: '信息确认',
  out_of_scope: '范围外拦截',
  citizen_query: '市民咨询', ticket_advice: '办件助手', ai_analyze: 'AI 分析',
  triage_assistant: '智能分诊', handling_assistant: '办件文书',
  pre_review: '预审', kb_index: '知识库索引', rag_query: 'RAG 检索',
  semantic_cache_lookup: '语义缓存',
}
const TIER_LABELS: Record<string, string> = {
  rules: '规则层', embedding: '向量层', llm_lite: 'LLM 轻量', llm_full: 'LLM 全量',
}
const TIER_COLORS: Record<string, string> = {
  rules: 'default',
  embedding: 'cyan',
  llm_lite: 'blue',
  llm_full: 'geekblue',
}
const ROLE_LABELS: Record<string, string> = {
  anonymous: '访客', citizen: '市民', agent: '坐席',
  department_staff: '部门人员', admin: '管理员', service: '服务调用',
}
const CAPABILITY_LABELS: Record<string, string> = {
  orchestrator_classify: '意图分类',
  ticket_draft: '工单草稿',
  policy_rag: '政策 RAG',
  service_guide: '办事指南',
  ticket_advice: '办件助手(旧)',
  triage_assistant: '智能分诊',
  handling_assistant: '办件文书',
  ai_analyze: 'AI 分析',
  pre_review: 'AI 预审',
  embedding_index: '索引向量',
  embedding_query: '检索向量',
  semantic_cache: '语义缓存',
}
const PROVIDER_LABELS: Record<string, string> = {
  deepseek: 'DeepSeek',
  silicon_flow: 'SiliconFlow',
  openai: 'OpenAI',
  volcengine: '火山引擎',
  rules: '规则',
  fallback: '降级伪向量',
  unknown: '未知',
}

export function AdminAiUsagePage() {
  const [days, setDays] = useState(7)
  const stats = useQuery({
    queryKey: ['admin', 'ai-usage', 'stats', days],
    queryFn: () => getAiUsageStats(days),
    refetchInterval: 30_000,
  })

  return (
    <>
      <PageHeader
        eyebrow="AI USAGE & SAFETY"
        title="AI 用量与安全"
        description="所有指标均来自 ai_usage_logs 表的实时聚合，无静态假数据。每次模型调用、限流、缓存与降级均有完整审计记录。"
        extra={
          <Select
            value={days}
            onChange={setDays}
            style={{ width: 160 }}
            options={[
              { value: 1, label: '最近 1 天' },
              { value: 7, label: '最近 7 天' },
              { value: 14, label: '最近 14 天' },
              { value: 30, label: '最近 30 天' },
              { value: 90, label: '最近 90 天' },
            ]}
          />
        }
      />
      {stats.isError ? (
        <ErrorState error={stats.error} retry={() => stats.refetch()} />
      ) : (
        <Tabs
          defaultActiveKey="overview"
          items={[
            { key: 'overview', label: '用量概览', children: <OverviewTab data={stats.data} loading={stats.isLoading} /> },
            { key: 'timeseries', label: '每日趋势', children: <TimeseriesTab data={stats.data} loading={stats.isLoading} /> },
            { key: 'breakdown', label: '场景与角色', children: <BreakdownTab data={stats.data} loading={stats.isLoading} /> },
            { key: 'safety', label: '安全与降级', children: <SafetyTab data={stats.data} loading={stats.isLoading} /> },
            { key: 'logs', label: '调用明细', children: <LogsTab /> },
          ]}
        />
      )}
    </>
  )
}

// ========== Overview Tab ==========

function OverviewTab({ data, loading }: { data?: AiUsageStats; loading: boolean }) {
  if (loading && !data) return <Card className="surface"><Spin tip="加载中" /></Card>
  if (!data) return <Empty description="暂无数据" />

  return (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="调用总次数" value={data.total_calls} prefix={<ApiOutlined />} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="Token 消耗" value={data.total_tokens} prefix={<ThunderboltOutlined />} suffix={<small style={{ fontSize: 12 }}> 入 {data.total_input_tokens} / 出 {data.total_output_tokens}</small>} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="估算成本 (RMB)" value={data.total_cost_rmb} precision={4} prefix={<DollarOutlined />} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="平均耗时" value={data.avg_latency_ms} suffix="ms" prefix={<ClockCircleOutlined />} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="缓存命中率" value={(data.cache_hit_rate * 100).toFixed(1)} suffix="%" prefix={<CheckCircleOutlined />} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="无关问题拦截" value={data.out_of_scope_blocked_count} prefix={<SafetyOutlined />} valueStyle={{ color: '#7e67b4' }} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="限流次数" value={data.rate_limited_count} prefix={<StopOutlined />} valueStyle={{ color: '#cf1322' }} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="降级次数" value={data.degraded_count} prefix={<FireOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="模型失败次数" value={data.failed_count} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#cf1322' }} /></Card>
        </Col>
        <Col xs={12} md={8} xl={6}>
          <Card className="surface"><Statistic title="Token 缺失行数" value={data.usage_unavailable_count} prefix={<ThunderboltOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
      </Row>
      <Card title="按能力 (capability) 统计" className="surface" style={{ marginTop: 16 }} styles={{ body: { padding: 0 } }}>
        <Table
          rowKey="capability"
          size="small"
          pagination={false}
          dataSource={data.by_capability}
          columns={[
            { title: '能力', dataIndex: 'capability', render: (v: string) => <Tag color="blue">{CAPABILITY_LABELS[v] || v || '未知'}</Tag> },
            { title: '调用次数', dataIndex: 'calls' },
            { title: 'Token 消耗', dataIndex: 'tokens' },
            { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
          ]}
        />
      </Card>
      <Card title="按模型分层统计" className="surface" style={{ marginTop: 16 }} styles={{ body: { padding: 0 } }}>
        <Table
          rowKey="tier"
          size="small"
          pagination={false}
          dataSource={data.by_tier}
          columns={[
            { title: '模型分层', dataIndex: 'tier', render: (v: string) => <Tag color={TIER_COLORS[v] || 'default'}>{TIER_LABELS[v] || v}</Tag> },
            { title: '调用次数', dataIndex: 'calls' },
            { title: 'Token 消耗', dataIndex: 'tokens' },
            { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
          ]}
        />
      </Card>
    </>
  )
}

// ========== Timeseries Tab ==========

function TimeseriesTab({ data, loading }: { data?: AiUsageStats; loading: boolean }) {
  const option = useMemo<EChartsOption>(() => {
    const rows = [...(data?.timeseries || [])].reverse()  // chronological
    return {
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, data: ['调用次数', 'Token 消耗', '缓存命中', '降级', '限流'] },
      grid: { left: 50, right: 20, top: 25, bottom: 50 },
      xAxis: { type: 'category', data: rows.map(r => r.date) },
      yAxis: [
        { type: 'value', name: '次数', minInterval: 1 },
        { type: 'value', name: 'Token', minInterval: 1 },
      ],
      series: [
        { name: '调用次数', type: 'bar', data: rows.map(r => r.calls), itemStyle: { color: '#167c72' } },
        { name: 'Token 消耗', type: 'line', yAxisIndex: 1, data: rows.map(r => r.tokens), smooth: true, itemStyle: { color: '#4776bd' } },
        { name: '缓存命中', type: 'line', data: rows.map(r => r.cache_hits), smooth: true, itemStyle: { color: '#52c41a' } },
        { name: '降级', type: 'line', data: rows.map(r => r.degraded), smooth: true, itemStyle: { color: '#fa8c16' } },
        { name: '限流', type: 'line', data: rows.map(r => r.rate_limited), smooth: true, itemStyle: { color: '#cf1322' } },
      ],
    }
  }, [data])

  if (loading && !data) return <Card className="surface"><Spin tip="加载中" /></Card>
  const empty = !data?.timeseries.length
  return (
    <Card title="每日 AI 调用趋势" className="surface">
      <ChartPanel label="每日 AI 调用趋势图" option={option} empty={empty} />
    </Card>
  )
}

// ========== Breakdown Tab ==========

function BreakdownTab({ data, loading }: { data?: AiUsageStats; loading: boolean }) {
  if (loading && !data) return <Card className="surface"><Spin tip="加载中" /></Card>
  if (!data) return <Empty description="暂无数据" />
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card title="按业务场景" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="route"
            size="small"
            pagination={false}
            dataSource={data.by_route}
            columns={[
              { title: '场景', dataIndex: 'route', render: (v: string) => ROUTE_LABELS[v] || v || '未知' },
              { title: '调用次数', dataIndex: 'calls' },
              { title: 'Token 消耗', dataIndex: 'tokens' },
              { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
            ]}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="按能力 (capability)" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="capability"
            size="small"
            pagination={false}
            dataSource={data.by_capability}
            columns={[
              { title: '能力', dataIndex: 'capability', render: (v: string) => <Tag color="blue">{CAPABILITY_LABELS[v] || v || '未知'}</Tag> },
              { title: '调用次数', dataIndex: 'calls' },
              { title: 'Token 消耗', dataIndex: 'tokens' },
              { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
            ]}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="按供应商 (provider)" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="provider"
            size="small"
            pagination={false}
            dataSource={data.by_provider}
            columns={[
              { title: '供应商', dataIndex: 'provider', render: (v: string) => <Tag color="geekblue">{PROVIDER_LABELS[v] || v || '未知'}</Tag> },
              { title: '调用次数', dataIndex: 'calls' },
              { title: 'Token 消耗', dataIndex: 'tokens' },
              { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
            ]}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="按模型 (model)" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="model"
            size="small"
            pagination={false}
            dataSource={data.by_model}
            columns={[
              { title: '模型', dataIndex: 'model', render: (v: string) => <code style={{ fontSize: 12 }}>{v || '未知'}</code> },
              { title: '调用次数', dataIndex: 'calls' },
              { title: 'Token 消耗', dataIndex: 'tokens' },
              { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
            ]}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="按用户角色" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="role"
            size="small"
            pagination={false}
            dataSource={data.by_role}
            columns={[
              { title: '角色', dataIndex: 'role', render: (v: string) => ROLE_LABELS[v] || v || '未知' },
              { title: '调用次数', dataIndex: 'calls' },
              { title: 'Token 消耗', dataIndex: 'tokens' },
              { title: '估算成本 (RMB)', dataIndex: 'cost', render: (v: number) => v.toFixed(4) },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}

// ========== Safety Tab ==========

function SafetyTab({ data, loading }: { data?: AiUsageStats; loading: boolean }) {
  if (loading && !data) return <Card className="surface"><Spin tip="加载中" /></Card>
  if (!data) return <Empty description="暂无数据" />
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8}>
        <Card title="安全指标" className="surface">
          <Statistic title="无关问题拦截次数" value={data.out_of_scope_blocked_count} prefix={<SafetyOutlined />} valueStyle={{ color: '#7e67b4' }} />
          <Statistic title="限流次数" value={data.rate_limited_count} prefix={<StopOutlined />} valueStyle={{ color: '#cf1322' }} style={{ marginTop: 16 }} />
          <Statistic title="降级次数" value={data.degraded_count} prefix={<FireOutlined />} valueStyle={{ color: '#fa8c16' }} style={{ marginTop: 16 }} />
          <Statistic title="模型失败次数" value={data.failed_count} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#cf1322' }} style={{ marginTop: 16 }} />
          <Statistic title="Token 缺失行数" value={data.usage_unavailable_count} prefix={<ThunderboltOutlined />} valueStyle={{ color: '#fa8c16' }} style={{ marginTop: 16 }} />
        </Card>
      </Col>
      <Col xs={24} lg={16}>
        <Card title="降级原因分布" className="surface" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="reason"
            size="small"
            pagination={false}
            dataSource={data.by_degrade_reason}
            columns={[
              { title: '降级原因', dataIndex: 'reason', render: (v: string) => <Tag color="orange">{v || '未知'}</Tag> },
              { title: '次数', dataIndex: 'count' },
            ]}
          />
          <Typography.Paragraph type="secondary" style={{ padding: 12, marginBottom: 0 }}>
            说明：范围外拦截由规则与 LLM 双层判定，命中后使用固定中文兜底回复，不进入大模型生成；
            限流与降级由 Guard 模块在 LLM 调用前判定，命中后工单/查询等业务接口仍可使用。
            Token 缺失行数表示模型响应未返回 usage 块的调用数（已诚实标记 usage_unavailable=true，不伪造 0）。
          </Typography.Paragraph>
        </Card>
      </Col>
    </Row>
  )
}

// ========== Logs Tab ==========

function LogsTab() {
  const [page, setPage] = useState(1)
  const [route, setRoute] = useState<string | undefined>(undefined)
  const [tier, setTier] = useState<string | undefined>(undefined)
  const [capability, setCapability] = useState<string | undefined>(undefined)
  const [provider, setProvider] = useState<string | undefined>(undefined)
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [success, setSuccess] = useState<boolean | undefined>(undefined)
  const [degraded, setDegraded] = useState<boolean | undefined>(undefined)
  const query = useQuery({
    queryKey: ['admin', 'ai-usage', 'logs', page, route, tier, capability, provider, sessionId, success, degraded],
    queryFn: () => getAiUsageLogs({ page, page_size: 20, route, model_tier: tier, capability, provider, session_id: sessionId, success, degraded }),
  })
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />

  return (
    <Card
      title="近期模型调用明细"
      className="surface"
      extra={
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Select
            allowClear placeholder="能力" style={{ width: 140 }}
            value={capability} onChange={v => { setCapability(v); setPage(1) }}
            options={Object.entries(CAPABILITY_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear placeholder="供应商" style={{ width: 140 }}
            value={provider} onChange={v => { setProvider(v); setPage(1) }}
            options={Object.entries(PROVIDER_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Input.Search
            allowClear placeholder="session_id 模糊" style={{ width: 180 }}
            value={sessionId} onChange={e => { setSessionId(e.target.value || undefined); setPage(1) }}
            onSearch={v => { setSessionId(v || undefined); setPage(1) }}
          />
          <Select
            allowClear placeholder="场景" style={{ width: 140 }}
            value={route} onChange={v => { setRoute(v); setPage(1) }}
            options={Object.entries(ROUTE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear placeholder="模型分层" style={{ width: 140 }}
            value={tier} onChange={v => { setTier(v); setPage(1) }}
            options={Object.entries(TIER_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear placeholder="结果" style={{ width: 120 }}
            value={success} onChange={v => { setSuccess(v); setPage(1) }}
            options={[{ value: true, label: '成功' }, { value: false, label: '失败' }]}
          />
          <Select
            allowClear placeholder="降级" style={{ width: 120 }}
            value={degraded} onChange={v => { setDegraded(v); setPage(1) }}
            options={[{ value: true, label: '已降级' }, { value: false, label: '正常' }]}
          />
        </div>
      }
      styles={{ body: { padding: 0 } }}
    >
      <Table
        rowKey="id"
        size="small"
        loading={query.isLoading}
        dataSource={query.data?.items}
        scroll={{ x: 1400 }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
          { title: 'request_id', dataIndex: 'request_id', width: 120, ellipsis: true, render: (v: string) => <code style={{ fontSize: 11 }}>{v ? v.slice(0, 10) + '…' : '—'}</code> },
          { title: 'session_id', dataIndex: 'session_id', width: 140, ellipsis: true, render: (v: string | null) => <code style={{ fontSize: 11 }}>{v ? v.slice(0, 14) + '…' : '—'}</code> },
          { title: '角色', dataIndex: 'role', width: 90, render: (v: string) => ROLE_LABELS[v] || v || '—' },
          { title: '能力', dataIndex: 'capability', width: 110, render: (v: string) => v ? <Tag color="blue" style={{ fontSize: 11 }}>{CAPABILITY_LABELS[v] || v}</Tag> : '—' },
          { title: '场景', dataIndex: 'route', width: 110, render: (v: string) => v ? (ROUTE_LABELS[v] || v) : '—' },
          { title: '分层', dataIndex: 'model_tier', width: 90, render: (v: string) => <Tag color={TIER_COLORS[v] || 'default'} style={{ fontSize: 11 }}>{TIER_LABELS[v] || v}</Tag> },
          { title: '供应商', dataIndex: 'provider', width: 100, render: (v: string) => v ? <Tag color="geekblue" style={{ fontSize: 11 }}>{PROVIDER_LABELS[v] || v}</Tag> : '—' },
          { title: '模型', dataIndex: 'model_name', width: 130, ellipsis: true, render: (v: string) => <code style={{ fontSize: 11 }}>{v || '—'}</code> },
          { title: 'Token', width: 130, render: (_: unknown, r: AiUsageLogItem) => (
            <span>
              <span>{r.total_tokens || (r.input_tokens + r.output_tokens)}</span>
              {r.usage_unavailable && <Tag color="orange" style={{ fontSize: 10, marginLeft: 4 }}>未返回</Tag>}
              {r.text_count != null && <small style={{ color: '#888', marginLeft: 4 }}>(×{r.text_count})</small>}
            </span>
          ) },
          { title: '耗时', dataIndex: 'latency_ms', width: 80, render: (v: number) => `${v}ms` },
          { title: '成本 (RMB)', dataIndex: 'estimated_cost_rmb', width: 100, render: (v: number) => v ? v.toFixed(4) : '0' },
          {
            title: '标记', width: 220, render: (_: unknown, r: AiUsageLogItem) => (
              <>
                {r.cache_hit && <Tag color="green" style={{ fontSize: 11 }}>缓存</Tag>}
                {r.rate_limited && <Tag color="red" style={{ fontSize: 11 }}>限流</Tag>}
                {r.budget_exceeded && <Tag color="magenta" style={{ fontSize: 11 }}>预算超</Tag>}
                {r.degraded && <Tag color="orange" style={{ fontSize: 11 }}>降级</Tag>}
                {r.degrade_reason && <Tag style={{ fontSize: 11 }}>{r.degrade_reason}</Tag>}
                {!r.success && <Tag color="volcano" style={{ fontSize: 11 }}>失败</Tag>}
                {r.error_code && <Tag color="red" style={{ fontSize: 11 }}>{r.error_code}</Tag>}
                {r.success && !r.cache_hit && !r.rate_limited && !r.degraded && <Tag style={{ fontSize: 11 }}>正常</Tag>}
              </>
            )
          },
          { title: '错误', dataIndex: 'error', ellipsis: true, render: (v: string | null) => v || '—' },
        ]}
        pagination={{
          current: page,
          pageSize: 20,
          total: query.data?.total,
          onChange: setPage,
          showTotal: t => `共 ${t} 条`,
        }}
      />
    </Card>
  )
}
