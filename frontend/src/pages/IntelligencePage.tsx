import { useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Empty, Form, Input, List, Row, Space, Tag, Tooltip, Typography, message,
} from 'antd'
import { BulbOutlined, CloudSyncOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  analyzeTicket, listHotspots, listIntegrationStatuses, listSuggestions, reviewSuggestion,
  syncDirectory, syncExternalTicket,
} from '../api/intelligence'
import type { AiSuggestion, AiSuggestionType } from '../types'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { CitizenPreReview } from './CitizenPreReview'

const TRIAGE_TYPES: AiSuggestionType[] = ['triage_assistant']
const HANDLING_TYPES: AiSuggestionType[] = ['handling_assistant']

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

function TriageBody({ item }: { item: AiSuggestion }) {
  const value = item.result || {}
  const summary = (value.case_summary || {}) as Record<string, unknown>
  const classification = (value.classification || {}) as Record<string, unknown>
  const urgency = (value.urgency || {}) as Record<string, unknown>
  const completeness = (value.completeness || {}) as Record<string, unknown>
  const candidates = (value.department_candidates || value.recommended_departments || []) as Record<string, unknown>[]
  const sla = (value.sla_recommendation || {}) as Record<string, unknown>
  const completenessScore = Number(completeness.completeness_score ?? (value.confidence_labels as Record<string, unknown> | undefined)?.completeness_score)
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Descriptions size="small" column={1} title="诉求摘要" items={[
        { key: 'd', label: '摘要', children: String(summary.description || '—') },
        { key: 'l', label: '地点', children: String(summary.location || '—') },
        { key: 't', label: '持续/时间', children: String(summary.duration || '—') },
        { key: 'a', label: '影响范围', children: String(summary.affected_scope || '—') },
      ]}
      />
      <Descriptions size="small" column={1} title="事项分类与紧急度" items={[
        { key: 'rt', label: '诉求类型', children: String(classification.request_type || '—') },
        { key: 'c', label: '分类', children: `${classification.category || '—'}${classification.subcategory ? ` / ${classification.subcategory}` : ''}` },
        { key: 'cr', label: '分类理由', children: String(classification.reason || '—') },
        { key: 'u', label: '紧急程度', children: <Tag color={urgency.emergency ? 'red' : 'blue'}>{String(urgency.level || 'normal')}</Tag> },
        { key: 'ur', label: '紧急理由', children: String(urgency.reason || '—') },
      ]}
      />
      <Card size="small" title="信息完整性" type="inner" extra={
        Number.isFinite(completenessScore) && completenessScore > 0 ? (
          <Tooltip title="按必填字段覆盖率估算：描述、地点、时间、联系方式等规则计分，不是模型自评。">
            <Tag color="cyan">信息完整度 {completenessScore}%</Tag>
          </Tooltip>
        ) : null
      }
      >
        <Descriptions size="small" column={1} items={[
          { key: 'st', label: '结论', children: completeness.complete ? '信息完整' : '建议补充信息' },
          { key: 'm', label: '待追问字段', children: asStringList(completeness.missing_fields).join('、') || '无' },
          { key: 'q', label: '追问建议', children: asStringList(completeness.follow_up_questions).join('；') || '无' },
        ]}
        />
      </Card>
      <Card size="small" title="责任部门推荐" type="inner">
        <List
          size="small"
          locale={{ emptyText: '暂无部门候选' }}
          dataSource={candidates}
          renderItem={(row) => (
            <List.Item>
              <Space wrap>
                <b>{String(row.department_name || '—')}</b>
                {row.recommendation_level != null && <Tag>{String(row.recommendation_level)}</Tag>}
                {row.reason != null && <Typography.Text type="secondary">{String(row.reason)}</Typography.Text>}
              </Space>
            </List.Item>
          )}
        />
      </Card>
      <Descriptions size="small" column={1} title="SLA 建议（内部参考）" items={[
        { key: 'r', label: '响应建议', children: String(sla.response_deadline || '—') },
        { key: 'h', label: '办理建议', children: String(sla.handling_deadline || '—') },
        { key: 'rr', label: '说明', children: String(sla.reason || '不构成对市民的办结承诺') },
      ]}
      />
      <Alert type="info" showIcon message="受理告知语（可复制）" description={<Typography.Paragraph copyable style={{ marginBottom: 0 }}>{String(value.intake_notice_draft || '')}</Typography.Paragraph>} />
    </Space>
  )
}

function HandlingBody({ item }: { item: AiSuggestion }) {
  const value = item.result || {}
  const summary = (value.case_summary || {}) as Record<string, unknown>
  const factsOk = Boolean(value.facts_sufficient)
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Descriptions size="small" column={1} title="诉求与派发信息" items={[
        { key: 'd', label: '摘要', children: String(summary.description || '—') },
        { key: 'dept', label: '责任部门', children: String(summary.assigned_department || '—') },
        { key: 'c', label: '分类', children: String(summary.classification || '—') },
        { key: 'k', label: '已知事实', children: asStringList(summary.known_facts).join('；') || '尚无办理事实' },
      ]}
      />
      <Card size="small" title="现场核查清单" type="inner">
        <List size="small" dataSource={asStringList(value.verification_checklist)} renderItem={(row) => <List.Item>{row}</List.Item>} locale={{ emptyText: '暂无核查项' }} />
      </Card>
      <Card size="small" title="办理方案" type="inner">
        <List size="small" dataSource={asStringList(value.handling_plan)} renderItem={(row) => <List.Item>{row}</List.Item>} locale={{ emptyText: '暂无方案' }} />
      </Card>
      <Alert type="warning" showIcon message="风险提示" description={asStringList(value.risk_warnings).join('；') || '无'} />
      <Descriptions size="small" column={1} title="政策依据 / 协同 / 证据" items={[
        { key: 'p', label: '政策依据', children: asStringList(value.policy_references).join('；') || '—' },
        { key: 'co', label: '协同建议', children: asStringList(value.collaboration_suggestions).join('；') || '—' },
        { key: 'e', label: '证据清单', children: asStringList(value.evidence_checklist).join('、') || '—' },
        { key: 'm', label: '缺失办理事实', children: asStringList(value.missing_handling_facts).join('、') || '无' },
      ]}
      />
      <Alert
        type={factsOk ? 'success' : 'info'}
        showIcon
        message={factsOk ? '回复文书草稿（含已填事实，仍需人工复核）' : '回复模板（尚未填写真实办理事实，仅占位符）'}
        description={<Typography.Paragraph copyable style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{String(value.reply_draft || value.reply_template || '')}</Typography.Paragraph>}
      />
    </Space>
  )
}

function LegacyBody({ item }: { item: AiSuggestion }) {
  const value = item.result
  if (item.suggestion_type === 'summary') {
    return <Typography.Paragraph copyable>{String(value.summary || '')}</Typography.Paragraph>
  }
  if (item.suggestion_type === 'completeness') {
    return <Descriptions size="small" column={1} items={[
      { key: 'state', label: '结论', children: value.complete ? '信息完整' : '建议补充信息' },
      { key: 'missing', label: '缺失项', children: asStringList(value.missing_fields).join('、') || '无' },
    ]}
    />
  }
  if (item.suggestion_type === 'risk') {
    return <Alert showIcon type={value.level === 'urgent' ? 'error' : 'warning'} message={String(value.recommendation || '')} />
  }
  if (item.suggestion_type === 'assignment') {
    return <List size="small" dataSource={(value.recommended_departments as { department_name: string }[] || [])} renderItem={(row) => <List.Item>{row.department_name}</List.Item>} />
  }
  if (item.suggestion_type === 'similarity') {
    const matches = (value.matches as { ticket_id: string; score: number }[] || [])
    return (
      <List
        size="small"
        dataSource={matches}
        locale={{ emptyText: '未发现明显相似诉求' }}
        renderItem={(row) => (
          <List.Item>
            <Space>
              <b>{row.ticket_id}</b>
              <Tooltip title="基于诉求文本 bigram 重合度估算，不是模型自评。">
                <Tag>相似匹配度 {Math.round(row.score * 100)}%</Tag>
              </Tooltip>
            </Space>
          </List.Item>
        )}
      />
    )
  }
  return <pre className="ai-json-result">{JSON.stringify(value, null, 2)}</pre>
}

function ResultBody({ item }: { item: AiSuggestion }) {
  if (item.suggestion_type === 'triage_assistant') return <TriageBody item={item} />
  if (item.suggestion_type === 'handling_assistant') return <HandlingBody item={item} />
  return <LegacyBody item={item} />
}

export function IntelligencePage() {
  const { user } = useAuth()
  if (user?.role === 'citizen') return <CitizenPreReview />
  return <StaffAiWorkbench />
}

function StaffAiWorkbench() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [form] = Form.useForm<{ ticket_id: string }>()
  const [suggestions, setSuggestions] = useState<AiSuggestion[]>([])
  const role = user?.role
  const isAgent = role === 'agent' || role === 'admin'
  const isDept = role === 'department_staff'
  const capability = isDept ? 'handling_assistant' : 'triage_assistant'
  const types = isDept ? HANDLING_TYPES : TRIAGE_TYPES
  const title = isDept ? 'AI 办件与文书辅助' : '智能分诊与派发'
  const description = isDept
    ? '面向已派发工单：生成核查清单、办理方案与回复模板。未填写真实办理事实时只给占位符模板；AI 不会自动办结。'
    : '面向受理分派：生成分类、紧急度、完整性与部门候选。不生成办结文书或未核实的处理结果；AI 不会自动派发。'
  const ticketBase = role === 'admin' ? '/admin/tickets' : role === 'department_staff' ? '/department/tickets' : '/agent/tickets'

  const mergeSuggestions = (incoming: AiSuggestion[]) => setSuggestions((prev) => {
    const byId = new Map<string, AiSuggestion>()
    for (const item of [...prev, ...incoming]) byId.set(item.id, item)
    return Array.from(byId.values()).sort((a, b) => b.created_at.localeCompare(a.created_at))
  })

  const analyze = useMutation({
    mutationFn: (ticketId: string) => analyzeTicket(ticketId.trim().toUpperCase(), types, capability),
    onSuccess: (data) => { mergeSuggestions(data); message.success('AI 建议已生成，仅供人工参考，不会自动变更工单状态') },
    onError: (e) => message.error(e instanceof ApiError ? e.message : '分析失败'),
  })
  const history = useMutation({
    mutationFn: (ticketId: string) => listSuggestions(ticketId.trim().toUpperCase()),
    onSuccess: (data) => {
      const filtered = data.filter((item) => (isDept
        ? ['handling_assistant', 'ticket_advice', 'document_draft'].includes(item.suggestion_type)
        : ['triage_assistant', 'assignment', 'summary', 'completeness', 'risk', 'similarity'].includes(item.suggestion_type)))
      if (filtered.length === 0) message.info('该工单暂无本角色可见的历史建议')
      else { mergeSuggestions(filtered); message.success(`已加载 ${filtered.length} 条历史建议`) }
    },
    onError: (e) => message.error(e instanceof ApiError ? e.message : '加载历史建议失败'),
  })
  const hotspots = useQuery({ queryKey: ['ai', 'hotspots'], queryFn: () => listHotspots(30), enabled: isAgent || isDept })
  const integrations = useQuery({ queryKey: ['integrations', 'status'], queryFn: listIntegrationStatuses, enabled: role === 'admin' })
  const directory = useMutation({
    mutationFn: syncDirectory,
    onSuccess: (r) => { message.success(`目录同步完成：新增 ${r.created}，更新 ${r.updated}`); void qc.invalidateQueries({ queryKey: ['integrations'] }) },
    onError: (e) => message.error(e instanceof Error ? e.message : '同步失败'),
  })
  const external = useMutation({
    mutationFn: (id: string) => syncExternalTicket(id),
    onSuccess: (r) => message.success(`已请求外部工单同步 ${r.external_ticket_id}`),
    onError: (e) => message.error(e instanceof Error ? e.message : '同步失败'),
  })

  const qualityReview = async (item: AiSuggestion, decision: 'helpful' | 'not_helpful') => {
    await reviewSuggestion(item.id, decision)
    setSuggestions((current) => current.map((row) => (row.id === item.id ? { ...row, review_decision: decision } : row)))
    message.success('模型质量反馈已记录（不会修改工单字段）')
  }

  const adoptReview = async (item: AiSuggestion, decision: 'adopted' | 'adopted_with_edits' | 'rejected') => {
    await reviewSuggestion(item.id, decision)
    setSuggestions((current) => current.map((row) => (row.id === item.id ? { ...row, review_decision: decision } : row)))
    message.success(decision === 'rejected' ? '已拒绝本条建议' : '已记录业务采纳（不会自动派发/办结，请在工单详情继续操作）')
  }

  const workOrderConfigured = useMemo(
    () => (integrations.data || []).some((item) => item.integration_type === 'work_order' && item.configured),
    [integrations.data],
  )

  return (
    <>
      <PageHeader eyebrow="AI ADVISORY" title={title} description={description} />
      <Alert
        className="surface"
        showIcon
        icon={<SafetyCertificateOutlined />}
        type="warning"
        message="人机协同边界"
        description="AI 只提供建议。采纳记录不会自动派发、填写办理结果或办结；真实业务操作必须在工单详情完成。模型质量反馈（有帮助/无帮助）不会写入业务字段。"
        style={{ marginBottom: 20 }}
      />
      <Card className="surface" title={isDept ? '按已派发工单生成办件建议' : '按待受理/已受理工单生成分诊建议'} extra={<BulbOutlined />}>
        <Form
          form={form}
          layout="inline"
          onFinish={(v) => { setSuggestions([]); analyze.mutate(v.ticket_id) }}
        >
          <Form.Item name="ticket_id" label="工单编号" rules={[{ required: true, message: '请输入工单编号' }]}>
            <Input aria-label="工单编号" placeholder="QT2026071400000001" style={{ width: 240 }} />
          </Form.Item>
          <Form.Item>
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={analyze.isPending}>
                {isDept ? '生成办件建议' : '生成分诊建议'}
              </Button>
              <Button
                loading={history.isPending}
                onClick={() => {
                  const id = form.getFieldValue('ticket_id')
                  if (id) { setSuggestions([]); history.mutate(id) }
                  else message.warning('请先输入工单编号')
                }}
              >
                加载历史建议
              </Button>
              {role === 'admin' && workOrderConfigured && (
                <Button
                  icon={<CloudSyncOutlined />}
                  loading={external.isPending}
                  onClick={() => {
                    const id = form.getFieldValue('ticket_id')
                    if (id) external.mutate(id)
                    else message.warning('请先输入工单编号')
                  }}
                >
                  同步外部工单（已配置）
                </Button>
              )}
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Row gutter={[20, 20]} style={{ marginTop: 20 }}>
        {suggestions.map((item) => (
          <Col xs={24} lg={24} key={item.id}>
            <Card
              className="surface ai-suggestion-card"
              title={(
                <Space wrap>
                  {item.suggestion_type === 'triage_assistant' ? '智能分诊建议' : item.suggestion_type === 'handling_assistant' ? '办件文书建议' : item.suggestion_type}
                  {item.risk_level !== 'none' && <Tag color={item.risk_level === 'urgent' ? 'red' : 'orange'}>{item.risk_level}</Tag>}
                  <Tag>{item.provider}/{item.model_name}</Tag>
                </Space>
              )}
            >
              <ResultBody item={item} />
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>{item.explanation}</Typography.Text>
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 12 }}
                message="AI 只提供建议；采纳仅记审核决策，不会自动派发、填写办理结果或办结。真实业务操作请前往工单详情完成。"
              />
              <div style={{ marginTop: 14 }}>
                <Space wrap>
                  {(item.suggestion_type === 'triage_assistant' || item.suggestion_type === 'handling_assistant') && (
                    <>
                      <Button size="small" type="primary" onClick={() => void adoptReview(item, 'adopted')}>
                        {isDept ? '记录采纳意见' : '记录为已采纳'}
                      </Button>
                      <Tooltip title="仅记录审核决策，不会自动修改工单字段、派发或办结">
                        <Button size="small" onClick={() => void adoptReview(item, 'adopted_with_edits')}>
                          记录修改后采纳
                        </Button>
                      </Tooltip>
                      <Button size="small" danger onClick={() => void adoptReview(item, 'rejected')}>
                        {isDept ? '放弃本次建议' : '拒绝建议'}
                      </Button>
                      <Link to={`${ticketBase}/${item.ticket_id}`}>
                        <Button size="small">前往工单详情继续办理</Button>
                      </Link>
                    </>
                  )}
                  <Button size="small" type={item.review_decision === 'helpful' ? 'primary' : 'default'} onClick={() => void qualityReview(item, 'helpful')}>有帮助</Button>
                  <Button size="small" danger={item.review_decision === 'not_helpful'} onClick={() => void qualityReview(item, 'not_helpful')}>无帮助</Button>
                </Space>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {(isAgent || isDept) && (
        <Card className="surface" title="近 30 天热点问题聚类" style={{ marginTop: 20 }}>
          {hotspots.isError ? <ErrorState error={hotspots.error} retry={() => hotspots.refetch()} /> : (
            <List
              loading={hotspots.isLoading}
              dataSource={hotspots.data}
              locale={{ emptyText: <Empty description="当前可见范围内尚未形成热点聚类" /> }}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={<Space>{item.label}<Tag color="blue">{item.count} 件</Tag>{item.urgent_count > 0 && <Tag color="red">紧急 {item.urgent_count}</Tag>}</Space>}
                    description={`样本工单：${item.sample_ticket_ids.join('、')}`}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      )}

      {role === 'admin' && (
        <Card className="surface" title="平台接入状态" style={{ marginTop: 20 }} extra={<Button loading={directory.isPending} onClick={() => directory.mutate()}>同步组织人员目录</Button>}>
          {integrations.isError ? <ErrorState error={integrations.error} retry={() => integrations.refetch()} /> : (
            <List
              loading={integrations.isLoading}
              grid={{ gutter: 12, xs: 1, sm: 2, lg: 4 }}
              dataSource={integrations.data}
              renderItem={(item) => (
                <List.Item>
                  <Card size="small">
                    <b>{item.integration_type}</b>
                    <div style={{ margin: '10px 0' }}>
                      <Tag color={item.configured ? 'green' : 'default'}>{item.configured ? '已配置' : '待配置'}</Tag>
                      <Tag>{item.mode}</Tag>
                    </div>
                    <Typography.Text type="secondary">{item.message}</Typography.Text>
                  </Card>
                </List.Item>
              )}
            />
          )}
        </Card>
      )}
    </>
  )
}
