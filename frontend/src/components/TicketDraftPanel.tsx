import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Divider, Input, Select, Space, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, EditOutlined, FileTextOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { preReview } from '../api/intelligence'
import { createTicket } from '../api/tickets'
import { ApiError } from '../api/client'

const { TextArea } = Input
const REQUEST_TYPES = ['投诉', '建议', '咨询', '求助']
const PHONE_RE = /^1[3-9]\d{9}$/

export interface DraftState {
  request_type?: string
  description?: string
  location?: string
  occurred_at_text?: string
  target?: string
  contact?: string
}

interface Props {
  draft: DraftState
  missing: string[]
  onChange: (draft: DraftState) => void
  onSubmitted: (ticketId: string) => void
}

export function TicketDraftPanel({ draft, missing, onChange, onSubmitted }: Props) {
  const { user } = useAuth()
  const nav = useNavigate()
  const [editing, setEditing] = useState<string | null>(null)
  const [normalized, setNormalized] = useState('')
  const [useNormalized, setUseNormalized] = useState(false)
  const [submittedId, setSubmittedId] = useState<string | null>(null)

  const set = (field: keyof DraftState, value: string) => onChange({ ...draft, [field]: value })

  // Validation
  const errors: Record<string, string> = {}
  if (!draft.request_type) errors.request_type = '请选择诉求类型'
  if (!draft.description || draft.description.trim().length < 4) errors.description = '描述至少4个字'
  if (!draft.location || !draft.location.trim()) errors.location = '请填写地点（咨询可填"不适用"）'
  if (draft.contact && !PHONE_RE.test(draft.contact) && !draft.contact.includes('@')) errors.contact = '请输入有效手机号或邮箱'
  const isValid = Object.keys(errors).length === 0

  const normalize = useMutation({
    mutationFn: () => preReview({
      description: draft.description || '',
      request_type: draft.request_type,
      location: draft.location,
      occurred_at_text: draft.occurred_at_text,
      target: draft.target,
      contact: draft.contact,
    }),
    onSuccess: (data) => { setNormalized(data.normalized_description); setUseNormalized(true) },
    onError: e => message.error(e instanceof ApiError ? e.message : '规范化失败'),
  })

  const submit = useMutation({
    mutationFn: () => createTicket({
      idempotency_key: `chat-draft-${user?.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      request_type: draft.request_type || '投诉',
      description: useNormalized && normalized ? normalized : (draft.description || ''),
      location: draft.location || '未提供',
      occurred_at_text: draft.occurred_at_text || undefined,
      target: draft.target || undefined,
      contact: draft.contact || undefined,
      source: 'rasa-chat-draft',
    }),
    onSuccess: (data) => {
      setSubmittedId(data.ticket.ticket_id)
      onSubmitted(data.ticket.ticket_id)
      message.success(`工单已提交：${data.ticket.ticket_id}`)
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '提交失败'),
  })

  if (submittedId) {
    return <Card className="surface draft-panel"><Alert type="success" showIcon icon={<CheckCircleOutlined />} message="工单已提交" description={<span>编号：<b>{submittedId}</b> <Button type="link" size="small" onClick={() => nav(`/citizen/tickets/${submittedId}`)}>查看办理进度</Button></span>} /></Card>
  }

  const fieldConfig: { key: keyof DraftState; label: string; required: boolean; placeholder: string }[] = [
    { key: 'request_type', label: '诉求类型', required: true, placeholder: '选择类型' },
    { key: 'description', label: '诉求描述', required: true, placeholder: '详细描述问题' },
    { key: 'location', label: '发生地点', required: true, placeholder: '如：幸福路社区3号楼旁' },
    { key: 'occurred_at_text', label: '发生时间', required: false, placeholder: '如：三天前 / 7月16日' },
    { key: 'target', label: '涉及对象', required: false, placeholder: '如：市政路灯 / 物业公司' },
    { key: 'contact', label: '联系方式', required: false, placeholder: '手机号（已登录可跳过）' },
  ]

  return <Card className="surface draft-panel" title={<Space><FileTextOutlined />工单草稿</Space>} extra={isValid ? <Tag color="green">可提交</Tag> : <Tag color="orange">待补全</Tag>}>
    {user?.role === 'citizen' && <Alert type="info" showIcon message="已绑定市民账号，联系方式可留空" style={{ marginBottom: 12 }} />}
    <Descriptions size="small" column={1} items={fieldConfig.map(f => ({
      key: f.key,
      label: <Space>{f.label}{f.required && <span style={{ color: '#ff4d4f' }}>*</span>}{errors[f.key] && <Typography.Text type="danger" style={{ fontSize: 12 }}>{errors[f.key]}</Typography.Text>}</Space>,
      children: editing === f.key
        ? (f.key === 'request_type'
          ? <Select size="small" autoFocus style={{ width: '100%' }} value={draft[f.key]} options={REQUEST_TYPES.map(t => ({ value: t, label: t }))} onChange={v => { set(f.key, v); setEditing(null) }} onBlur={() => setEditing(null)} />
          : f.key === 'description'
          ? <TextArea size="small" autoFocus rows={3} defaultValue={draft[f.key]} onBlur={e => { set(f.key, e.target.value); setEditing(null) }} />
          : <Input size="small" autoFocus defaultValue={draft[f.key]} placeholder={f.placeholder} onPressEnter={e => { set(f.key, (e.target as HTMLInputElement).value); setEditing(null) }} onBlur={e => { set(f.key, e.target.value); setEditing(null) }} />)
        : <Space>
            <span>{draft[f.key] || <Typography.Text type="secondary">{missing.includes(f.key) ? '待补充' : '—'}</Typography.Text>}</span>
            <Button size="small" type="text" icon={<EditOutlined />} onClick={() => setEditing(f.key)} />
          </Space>,
    }))} />

    <Divider style={{ margin: '12px 0' }} />
    <Typography.Text strong style={{ fontSize: 13 }}>规范化描述</Typography.Text>
    <div style={{ marginTop: 6 }}>
      {normalized ? <Typography.Paragraph style={{ fontSize: 13, background: '#f6f9f8', padding: 8, borderRadius: 6 }}>{normalized}</Typography.Paragraph> : <Typography.Text type="secondary" style={{ fontSize: 12 }}>点击"生成规范描述"由 AI 整理为正式工单文本</Typography.Text>}
      <Space style={{ marginTop: 6 }} wrap>
        <Button size="small" loading={normalize.isPending} onClick={() => normalize.mutate()}>生成规范描述</Button>
        {normalized && <Button size="small" type={useNormalized ? 'primary' : 'default'} onClick={() => setUseNormalized(true)}>使用此版本</Button>}
        {normalized && <Button size="small" onClick={() => setUseNormalized(false)}>保留原文</Button>}
      </Space>
    </div>

    <Divider style={{ margin: '12px 0' }} />
    <Button block type="primary" size="large" icon={<SendOutlined />} disabled={!isValid} loading={submit.isPending} onClick={() => submit.mutate()}>确认提交工单</Button>
    {!isValid && <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>请先补全标红的必填项</Typography.Text>}
  </Card>
}
