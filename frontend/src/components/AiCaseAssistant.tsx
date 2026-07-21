import { useState } from 'react'
import { Alert, Badge, Button, Card, Collapse, Empty, Input, Modal, Space, Spin, Tag, Timeline, Tooltip, Typography, message } from 'antd'
import {
  BulbOutlined, CheckOutlined, CloseOutlined, CopyOutlined, EditOutlined, ReloadOutlined, RobotOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { ApiError } from '../api/client'
import {
  getKbTicketAdvice,
  listKbTicketAdviceReviews,
  reviewKbTicketAdvice,
} from '../api/kb'
import type { KbAdviceReviewDecision, KbAdviceReviewRecord } from '../api/kb'
import type { KbCitation, KbTicketAdvice, TicketDetail } from '../types'

interface Props {
  ticket: TicketDetail
}

const DECISION_LABEL: Record<KbAdviceReviewDecision, string> = {
  adopted: '采纳',
  adopted_with_edits: '修改后采纳',
  rejected: '驳回',
}

const DECISION_TAG_COLOR: Record<KbAdviceReviewDecision, string> = {
  adopted: 'green',
  adopted_with_edits: 'blue',
  rejected: 'red',
}

const DECISION_BADGE_STATUS: Record<KbAdviceReviewDecision, 'success' | 'processing' | 'error'> = {
  adopted: 'success',
  adopted_with_edits: 'processing',
  rejected: 'error',
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = dayjs(iso)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : iso
}

/**
 * 部门端 AI 办件助手（RAG 加持版）。
 * 输出模块：适用依据 / 材料检查 / 办理流程 / 时限与风险 / 相似案例 / 回复草稿 + 引用列表。
 * 所有结果仅供工作人员参考，不会自动发送给市民。
 *
 * 三态人工确认（r3-3）：采纳 / 修改后采纳 / 驳回，记录审计轨迹，
 * 不修改工单状态与 version。
 */
export function AiCaseAssistant({ ticket }: Props) {
  const [advice, setAdvice] = useState<KbTicketAdvice | null>(null)
  const [hasReviewed, setHasReviewed] = useState(false)
  const [reviewModalOpen, setReviewModalOpen] = useState(false)
  const [pendingDecision, setPendingDecision] = useState<KbAdviceReviewDecision | null>(null)
  const [editSummary, setEditSummary] = useState('')
  const queryClient = useQueryClient()

  const analyze = useMutation({
    mutationFn: () => getKbTicketAdvice(ticket.ticket_id),
    onSuccess: (data) => {
      setAdvice(data)
      setHasReviewed(false)
      if (data.no_evidence) {
        message.warning('未检索到适用政策依据，已给出建议性回复')
      } else {
        message.success('AI 建议已生成，仅供人工参考')
      }
    },
    onError: e => message.error(e instanceof ApiError ? e.message : 'AI 分析失败'),
  })

  const reviewsQuery = useQuery({
    queryKey: ['kb', 'tickets', ticket.ticket_id, 'advice-reviews'],
    queryFn: () => listKbTicketAdviceReviews(ticket.ticket_id),
  })

  const reviewMutation = useMutation({
    mutationFn: (decision: KbAdviceReviewDecision) => reviewKbTicketAdvice(ticket.ticket_id, {
      decision,
      edit_summary: editSummary.trim() || undefined,
      advice_snapshot: advice ? { ...advice } : undefined,
    }),
    onSuccess: () => {
      message.success('审核已记录，工单状态未变更')
      setHasReviewed(true)
      setReviewModalOpen(false)
      setEditSummary('')
      setPendingDecision(null)
      void queryClient.invalidateQueries({
        queryKey: ['kb', 'tickets', ticket.ticket_id, 'advice-reviews'],
      })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '审核提交失败'),
  })

  const regenerate = () => {
    analyze.mutate()
  }

  const openReviewModal = (decision: KbAdviceReviewDecision) => {
    setPendingDecision(decision)
    setEditSummary('')
    setReviewModalOpen(true)
  }

  const closeReviewModal = () => {
    setReviewModalOpen(false)
    setEditSummary('')
    setPendingDecision(null)
  }

  const submitReview = () => {
    if (!pendingDecision) return
    if (pendingDecision === 'adopted_with_edits' && !editSummary.trim()) {
      message.warning('请填写修改内容摘要')
      return
    }
    if (editSummary.length > 1000) {
      message.warning('修改内容摘要不超过 1000 字符')
      return
    }
    reviewMutation.mutate(pendingDecision)
  }

  const latestReview: KbAdviceReviewRecord | null = reviewsQuery.data?.[0] ?? null
  const buttonsDisabled = hasReviewed
  const reviews: KbAdviceReviewRecord[] = reviewsQuery.data ?? []

  return (
    <Card
      className="surface"
      title={<Space><RobotOutlined />AI 办件助手</Space>}
      extra={
        <Space>
          <Tag color="orange">仅辅助参考</Tag>
          {advice?.provider && <Tag color="blue">{advice.provider}</Tag>}
          {latestReview && (
            <Badge
              status={DECISION_BADGE_STATUS[latestReview.decision]}
              text={
                <Space size={4}>
                  <span>已审核：</span>
                  <Tag color={DECISION_TAG_COLOR[latestReview.decision]} style={{ margin: 0 }}>
                    {DECISION_LABEL[latestReview.decision]}
                  </Tag>
                </Space>
              }
            />
          )}
        </Space>
      }
      style={{ marginTop: 20 }}
    >
      <Alert
        type="warning"
        showIcon
        message="AI 仅提供办理建议，不得自动受理、驳回、修改状态、派发或发送正式回复。所有动作必须由工作人员确认。"
        style={{ marginBottom: 16 }}
      />

      {!advice && (
        <Button
          type="primary"
          icon={<BulbOutlined />}
          loading={analyze.isPending}
          onClick={() => analyze.mutate()}
        >
          生成办理建议
        </Button>
      )}

      {analyze.isPending && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
          <div style={{ marginTop: 8 }}>
            <Typography.Text type="secondary">正在检索政策库并生成结构化建议…</Typography.Text>
          </div>
        </div>
      )}

      {advice && !analyze.isPending && (
        <>
          {advice.no_evidence && (
            <Alert
              type="warning"
              showIcon
              message="未检索到适用依据"
              description="以下建议为通用模板，请人工核实工单详情并查阅本部门内部制度。"
              style={{ marginBottom: 16 }}
            />
          )}

          <Collapse
            defaultActiveKey={['policies', 'steps', 'reply']}
            items={[
              {
                key: 'policies',
                label: `适用依据 (${advice.applicable_policies.length})`,
                children: advice.applicable_policies.length ? (
                  <ul style={{ marginBottom: 0 }}>{advice.applicable_policies.map((p, i) => <li key={i}>{p}</li>)}</ul>
                ) : <Empty description="未检索到适用依据" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
              },
              {
                key: 'verify',
                label: `材料检查 (${advice.verification_needed.length})`,
                children: <ul style={{ marginBottom: 0 }}>{advice.verification_needed.map((v, i) => <li key={i}>{v}</li>)}</ul>,
              },
              {
                key: 'material',
                label: '材料完整性',
                children: <Typography.Paragraph style={{ marginBottom: 0 }}>{advice.material_completeness}</Typography.Paragraph>,
              },
              {
                key: 'steps',
                label: `办理流程 (${advice.suggested_steps.length})`,
                children: <ol style={{ marginBottom: 0 }}>{advice.suggested_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>,
              },
              {
                key: 'boundary',
                label: '责任边界',
                children: <Typography.Paragraph style={{ marginBottom: 0 }}>{advice.responsibility_boundary}</Typography.Paragraph>,
              },
              {
                key: 'timeline',
                label: '时限与风险',
                children: (
                  <Typography.Paragraph
                    type={advice.timeline_risk.includes('超时') || advice.timeline_risk.includes('风险') ? 'danger' : undefined}
                    style={{ marginBottom: 0 }}
                  >
                    {advice.timeline_risk}
                  </Typography.Paragraph>
                ),
              },
              {
                key: 'cases',
                label: `相似案例 (${advice.similar_cases.length})`,
                children: advice.similar_cases.length ? (
                  <ul style={{ marginBottom: 0 }}>{advice.similar_cases.map((c, i) => <li key={i}>{c}</li>)}</ul>
                ) : <Typography.Text type="secondary">暂无相似案例</Typography.Text>,
              },
              {
                key: 'reply',
                label: '回复草稿（可编辑 / 复制）',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Typography.Paragraph
                      copyable={{ icon: [<CopyOutlined key="c" />, '复制草稿'] }}
                      style={{ whiteSpace: 'pre-wrap', marginBottom: 0, background: 'rgba(22,124,114,0.05)', padding: 12, borderRadius: 6 }}
                    >
                      {advice.reply_draft}
                    </Typography.Paragraph>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      草稿仅供参考，必须人工核实事实后方可发送。
                    </Typography.Text>
                  </Space>
                ),
              },
              {
                key: 'citations',
                label: `引用来源 (${advice.citations.length})`,
                children: advice.citations.length ? (
                  <Collapse
                    size="small"
                    items={advice.citations.map(c => ({
                      key: c.index,
                      label: (
                        <Space wrap>
                          <Tag color="blue">来源{c.index}</Tag>
                          <Typography.Text strong>{c.title}</Typography.Text>
                          {c.doc_number && <Typography.Text type="secondary">{c.doc_number}</Typography.Text>}
                          {c.department && <Tag>{c.department}</Tag>}
                          {c.is_expired ? <Tag color="red">已失效</Tag> : <Tag color="green">有效</Tag>}
                        </Space>
                      ),
                      children: <CitationDetail citation={c} />,
                    }))}
                  />
                ) : <Empty description="无引用（基于规则生成）" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
              },
            ]}
          />

          <div style={{ marginTop: 16 }}>
            {buttonsDisabled && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="本建议已完成人工审核。如需重新评估，请重新生成建议后再审核。"
              />
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <Space wrap>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  disabled={buttonsDisabled}
                  loading={reviewMutation.isPending && pendingDecision === 'adopted'}
                  onClick={() => reviewMutation.mutate('adopted')}
                >
                  采纳
                </Button>
                <Button
                  icon={<EditOutlined />}
                  disabled={buttonsDisabled}
                  loading={reviewMutation.isPending && pendingDecision === 'adopted_with_edits'}
                  onClick={() => openReviewModal('adopted_with_edits')}
                >
                  修改后采纳
                </Button>
                <Button
                  danger
                  icon={<CloseOutlined />}
                  disabled={buttonsDisabled}
                  loading={reviewMutation.isPending && pendingDecision === 'rejected'}
                  onClick={() => openReviewModal('rejected')}
                >
                  驳回
                </Button>
              </Space>
              <Tooltip title="基于最新知识库重新生成">
                <Button icon={<ReloadOutlined />} loading={analyze.isPending} onClick={regenerate}>
                  重新生成
                </Button>
              </Tooltip>
            </div>

            {reviews.length > 0 && (
              <Card size="small" title="审核历史" style={{ marginTop: 16 }}>
                <Timeline
                  items={reviews.map(r => ({
                    color: DECISION_TAG_COLOR[r.decision],
                    children: (
                      <div>
                        <Space wrap>
                          <Tag color={DECISION_TAG_COLOR[r.decision]}>{DECISION_LABEL[r.decision]}</Tag>
                          <Typography.Text strong>{r.operator_name ?? '未知用户'}</Typography.Text>
                          {r.operator_role && (
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {roleLabel(r.operator_role)}
                            </Typography.Text>
                          )}
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {formatDateTime(r.operated_at)}
                          </Typography.Text>
                        </Space>
                        {r.edit_summary && (
                          <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                            {r.edit_summary}
                          </Typography.Paragraph>
                        )}
                      </div>
                    ),
                  }))}
                />
              </Card>
            )}
          </div>

          <Modal
            title={pendingDecision === 'adopted_with_edits' ? '修改后采纳' : '驳回原因'}
            open={reviewModalOpen}
            onOk={submitReview}
            onCancel={closeReviewModal}
            confirmLoading={reviewMutation.isPending}
            okText="提交"
            cancelText="取消"
            destroyOnHidden
          >
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              {pendingDecision === 'adopted_with_edits'
                ? '请填写修改内容摘要（必填，最多 1000 字符）。提交后仅记录审计轨迹，不修改工单状态。'
                : '请填写驳回原因（可选，最多 1000 字符）。提交后仅记录审计轨迹，不修改工单状态。'}
            </Typography.Paragraph>
            <Input.TextArea
              value={editSummary}
              onChange={e => setEditSummary(e.target.value)}
              rows={4}
              maxLength={1000}
              showCount
              placeholder={pendingDecision === 'adopted_with_edits'
                ? '例如：补充了关于……的说明，调整了……的措辞'
                : '例如：建议与实际政策不符 / 材料检查项不完整'}
            />
          </Modal>
        </>
      )}
    </Card>
  )
}

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    admin: '管理员',
    agent: '坐席',
    department_staff: '部门工作人员',
    citizen: '市民',
  }
  return map[role] || role
}

function CitationDetail({ citation }: { citation: KbCitation }) {
  return (
    <div>
      {citation.excerpt && (
        <Typography.Paragraph
          style={{
            background: 'rgba(22,124,114,0.05)',
            padding: 12,
            borderRadius: 6,
            whiteSpace: 'pre-wrap',
            marginBottom: 12,
          }}
        >
          {citation.excerpt}
        </Typography.Paragraph>
      )}
      <Space wrap>
        {citation.published_at && <Tag>发布：{citation.published_at.slice(0, 10)}</Tag>}
        {citation.effective_at && <Tag>生效：{citation.effective_at.slice(0, 10)}</Tag>}
        {citation.expires_at && (
          <Tag color={citation.is_expired ? 'red' : 'default'}>
            失效：{citation.expires_at.slice(0, 10)}
          </Tag>
        )}
        {citation.kb_type && <Tag>{kbTypeLabel(citation.kb_type)}</Tag>}
        {citation.version && <Tag>v{citation.version}</Tag>}
      </Space>
    </div>
  )
}

function kbTypeLabel(t: string) {
  const map: Record<string, string> = {
    policy: '公开政策', guide: '办事指南', faq: '常见问题',
    internal: '内部制度', procedure: '办理流程', case: '历史案例',
  }
  return map[t] || t
}
