import { useState } from 'react'
import { Button, Form, Input, Modal, Select, Tag } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { AiSuggestion, Ticket } from '../types'
import { triageCandidates } from './TriageSuggestion'
import { WorkspaceError } from './WorkspaceState'

type ReviewDecision = NonNullable<AiSuggestion['review_decision']>
export type SaveTriageReview = (decision: ReviewDecision, comment?: string, editedContent?: Record<string, unknown>) => Promise<unknown>

const decisionLabels: Record<ReviewDecision, string> = {
  adopted: '已采纳', adopted_with_edits: '修改后已采纳', rejected: '已拒绝',
  helpful: '有帮助', not_helpful: '无帮助',
}

export function TriageReview({ ticket, item, saving, error, onSave }: {
  ticket: Ticket | undefined
  item: AiSuggestion | undefined
  saving: boolean
  error: unknown
  onSave: SaveTriageReview
}) {
  const [comment, setComment] = useState('')
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm<{ note: string; department?: string }>()
  const eligible = ticket?.status === 'pending' || ticket?.status === 'accepted'
  const canReview = eligible && item?.suggestion_type === 'triage_assistant'
  const candidates = item ? [...new Set(triageCandidates(item).map((candidate) => String(candidate.department_name)))] : []
  const lastDecision = item?.review_decision
  const save = (decision: ReviewDecision) => {
    void onSave(decision, comment.trim() || undefined).catch(() => undefined)
  }

  return (
    <>
      <div className="triage-review-state">
        <span>最近审核记录</span>
        <Tag color={lastDecision === 'rejected' ? 'error' : lastDecision ? 'processing' : 'default'}>
          {lastDecision ? decisionLabels[lastDecision] : '待人工确认'}
        </Tag>
        {item?.review_comment && <p>{item.review_comment}</p>}
      </div>
      <Form layout="vertical" className="triage-review-form">
        <Form.Item label="审核备注（选填）" htmlFor="triage-comment">
          <Input.TextArea id="triage-comment" value={comment} onChange={(event) => setComment(event.target.value)}
            disabled={!canReview || saving} rows={3} maxLength={1000} placeholder="记录判断依据或待核实事项" />
        </Form.Item>
      </Form>
      <div className="triage-review-actions">
        <Button type="primary" disabled={!canReview || saving} onClick={() => save('adopted')}>记录为已采纳</Button>
        <Button disabled={!canReview || saving} onClick={() => setEditing(true)}>记录修改后采纳</Button>
        <Button danger disabled={!canReview || saving} onClick={() => save('rejected')}>拒绝建议</Button>
      </div>
      {saving && <p role="status" className="triage-muted">正在保存审核记录…</p>}
      {Boolean(error) && !editing && <WorkspaceError error={error} fallback="审核记录保存失败。" />}
      <div className="triage-detail-action">
        {ticket && <Link className="triage-detail-link" to={`/agent/tickets/${ticket.ticket_id}`} aria-label="前往工单详情继续办理">前往工单详情 <ArrowRightOutlined /></Link>}
        <p>受理、派发与复核在工单详情办理。</p>
      </div>
      <Modal title="记录修改后采纳" open={editing} onCancel={() => setEditing(false)} onOk={() => form.submit()}
        okText="保存修订记录" confirmLoading={saving} cancelButtonProps={{ disabled: saving }} closable={!saving}
        mask={{ closable: !saving }} keyboard={!saving} destroyOnHidden>
        <p className="triage-muted">修订只随 AI 审核保存。责任部门由坐席在工单详情人工选择。</p>
        <Form form={form} layout="vertical" preserve={false} onFinish={async ({ note, department }) => {
          try {
            await onSave('adopted_with_edits', comment.trim() || undefined, {
              note: note.trim(),
              ...(department ? { department_candidate: department } : {}),
            })
            setEditing(false)
          } catch {
            // The mutation error is rendered in the dialog and preserves the form.
          }
        }}>
          {candidates.length > 0 && <Form.Item name="department" label="记录部门候选（选填）">
            <Select allowClear options={candidates.map((value) => ({ value, label: value }))} />
          </Form.Item>}
          <Form.Item name="note" label="修订内容" rules={[{ required: true, whitespace: true, message: '请输入实际修订内容' }]}>
            <Input.TextArea rows={4} maxLength={1000} />
          </Form.Item>
          {Boolean(error) && <WorkspaceError error={error} fallback="修订记录保存失败。" />}
        </Form>
      </Modal>
    </>
  )
}
