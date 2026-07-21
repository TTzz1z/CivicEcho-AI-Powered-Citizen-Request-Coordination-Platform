import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Divider, Form, Input, Select, Space, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, EditOutlined, FileTextOutlined, SendOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { preReview, type PreReviewData } from '../api/intelligence'
import { createTicket } from '../api/tickets'
import { ApiError } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { loadChatDraft, saveChatDraft } from '../utils/chatStorage'

const { TextArea } = Input
const REQUEST_TYPES = ['投诉', '建议', '咨询', '求助']

interface DraftState {
  description: string
  request_type?: string
  location?: string
  occurred_at_text?: string
  target?: string
  contact?: string
}

export function CitizenPreReview() {
  const { user } = useAuth()
  const nav = useNavigate()
  const [form] = Form.useForm<DraftState>()
  const [result, setResult] = useState<PreReviewData | null>(null)
  const [editing, setEditing] = useState<Record<string, boolean>>({})
  const [editedFields, setEditedFields] = useState<Record<string, string>>({})
  const [normalizedText, setNormalizedText] = useState('')
  const [useNormalized, setUseNormalized] = useState(true)
  const draftKey = `tingting_pre_review_draft_${user?.id}`

  // Restore draft on mount (TTL + contact stripped)
  useEffect(() => {
    const draft = loadChatDraft<DraftState>(draftKey)
    if (draft?.description) {
      form.setFieldsValue(draft)
      message.info('已恢复上次未提交的草稿')
    }
  }, [draftKey, form])

  const analyze = useMutation({
    mutationFn: (values: DraftState) => preReview({
      description: values.description,
      request_type: values.request_type || undefined,
      location: values.location || undefined,
      occurred_at_text: values.occurred_at_text || undefined,
      target: values.target || undefined,
      contact: values.contact || undefined,
    }),
    onSuccess: (data) => {
      setResult(data)
      setNormalizedText(data.normalized_description)
      setUseNormalized(true)
      setEditing({})
      setEditedFields({})
      message.success('智能预审完成，请核对以下信息')
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '预审分析失败，请稍后重试'),
  })

  const submit = useMutation({
    mutationFn: () => {
      const values = form.getFieldsValue()
      const finalType = editedFields['identified_type'] || result?.identified_type || values.request_type || '投诉'
      const finalLocation = editedFields['identified_location'] || result?.identified_location || values.location || ''
      const finalTime = editedFields['identified_time'] || result?.identified_time || values.occurred_at_text || undefined
      const finalTarget = editedFields['identified_target'] || result?.identified_target || values.target || undefined
      const finalDescription = useNormalized ? normalizedText : values.description
      return createTicket({
        idempotency_key: `web-pre-review-${user?.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        request_type: finalType,
        description: finalDescription,
        location: finalLocation || '未提供',
        occurred_at_text: finalTime && finalTime !== '未提供' ? finalTime : undefined,
        target: finalTarget && finalTarget !== '未提供' ? finalTarget : undefined,
        contact: values.contact || undefined,
        source: 'web-pre-review',
      })
    },
    onSuccess: (data) => {
      localStorage.removeItem(draftKey)
      message.success(`工单已提交，编号：${data.ticket.ticket_id}`)
      nav(`/citizen/tickets/${data.ticket.ticket_id}`)
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '提交失败，请稍后重试'),
  })

  const saveDraft = () => {
    const values = form.getFieldsValue()
    saveChatDraft(draftKey, values)
    message.success('草稿已保存到本地（联系方式不会长期保存）')
  }

  const startEdit = (field: string) => setEditing(prev => ({ ...prev, [field]: true }))
  const saveEdit = (field: string, value: string) => {
    setEditedFields(prev => ({ ...prev, [field]: value }))
    setEditing(prev => ({ ...prev, [field]: false }))
  }

  const getFieldValue = (field: string, original: string) => editedFields[field] ?? original

  const urgencyColor = (hint: string) => hint.includes('基本生活') ? 'red' : hint.includes('安全') ? 'orange' : 'green'

  return <>
    <PageHeader eyebrow="PRE-SUBMISSION CHECK" title="提交前智能预审" description="描述您的诉求，AI 将帮您识别信息、检查完整性、规范表述并推荐受理部门，确认无误后一键提交。" />
    <Card className="surface" title="描述您的诉求" extra={<ThunderboltOutlined style={{ color: '#167c72' }} />}>
      <Form form={form} layout="vertical" onFinish={v => analyze.mutate(v)}>
        <Form.Item name="description" label="诉求描述" rules={[{ required: true, message: '请描述您遇到的问题' }, { min: 4, message: '至少输入4个字' }]}>
          <TextArea rows={4} placeholder="请详细描述您遇到的问题，例如：幸福路社区3号楼旁的路灯已经坏了三天，晚上出行很不方便…" maxLength={5000} showCount />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0 16px' }}>
          <Form.Item name="request_type" label="诉求类型（可选）">
            <Select allowClear placeholder="自动识别" options={REQUEST_TYPES.map(t => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item name="location" label="地点（可选）">
            <Input placeholder="如：幸福路社区3号楼旁" />
          </Form.Item>
          <Form.Item name="occurred_at_text" label="发生时间（可选）">
            <Input placeholder="如：三天前 / 2026年7月16日" />
          </Form.Item>
          <Form.Item name="target" label="涉及对象（可选）">
            <Input placeholder="如：市政路灯 / 物业公司" />
          </Form.Item>
          <Form.Item name="contact" label="联系方式（可选）">
            <Input placeholder="手机号，便于回访" />
          </Form.Item>
        </div>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={analyze.isPending} icon={<ThunderboltOutlined />}>开始智能预审</Button>
            <Button onClick={saveDraft}>保存草稿</Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>

    {result && <>
      {/* AI 识别结果 */}
      <Card className="surface" style={{ marginTop: 20 }} title={<Space><FileTextOutlined />AI 识别结果</Space>} extra={<Tag color="cyan">仅供参考，可修改</Tag>}>
        <Descriptions size="small" column={{ xs: 1, sm: 2 }} items={[
          { key: 'type', label: '诉求类型', children: editing['identified_type']
            ? <Select size="small" defaultValue={getFieldValue('identified_type', result.identified_type)} options={REQUEST_TYPES.map(t => ({ value: t, label: t }))} onChange={v => saveEdit('identified_type', v)} onBlur={() => setEditing(p => ({ ...p, identified_type: false }))} style={{ width: 100 }} autoFocus />
            : <Space><Tag color="blue">{getFieldValue('identified_type', result.identified_type)}</Tag><Button size="small" type="text" icon={<EditOutlined />} onClick={() => startEdit('identified_type')} /></Space> },
          { key: 'target', label: '涉及对象', children: editing['identified_target']
            ? <Input size="small" defaultValue={getFieldValue('identified_target', result.identified_target)} onPressEnter={e => saveEdit('identified_target', (e.target as HTMLInputElement).value)} onBlur={e => saveEdit('identified_target', e.target.value)} style={{ width: 160 }} autoFocus />
            : <Space><span>{getFieldValue('identified_target', result.identified_target)}</span><Button size="small" type="text" icon={<EditOutlined />} onClick={() => startEdit('identified_target')} /></Space> },
          { key: 'location', label: '地点', children: editing['identified_location']
            ? <Input size="small" defaultValue={getFieldValue('identified_location', result.identified_location)} onPressEnter={e => saveEdit('identified_location', (e.target as HTMLInputElement).value)} onBlur={e => saveEdit('identified_location', e.target.value)} style={{ width: 200 }} autoFocus />
            : <Space><span>{getFieldValue('identified_location', result.identified_location)}</span><Button size="small" type="text" icon={<EditOutlined />} onClick={() => startEdit('identified_location')} /></Space> },
          { key: 'time', label: '时间', children: editing['identified_time']
            ? <Input size="small" defaultValue={getFieldValue('identified_time', result.identified_time)} onPressEnter={e => saveEdit('identified_time', (e.target as HTMLInputElement).value)} onBlur={e => saveEdit('identified_time', e.target.value)} style={{ width: 160 }} autoFocus />
            : <Space><span>{getFieldValue('identified_time', result.identified_time)}</span><Button size="small" type="text" icon={<EditOutlined />} onClick={() => startEdit('identified_time')} /></Space> },
          { key: 'impact', label: '影响范围', children: result.impact },
          { key: 'urgency', label: '紧急程度', children: <Tag color={urgencyColor(result.urgency_hint)}>{result.urgency_hint}</Tag> },
        ]} />
      </Card>

      {/* 信息补全 */}
      {result.missing_fields.length > 0 && (
        <Card className="surface" style={{ marginTop: 20 }} title="信息补全" extra={<Tag color="orange">还需补充 {result.missing_fields.length} 项</Tag>}>
          <Alert type="info" showIcon message="补充以下信息可以加快受理速度" style={{ marginBottom: 16 }} />
          {result.missing_fields.map(field => (
            <div key={field} style={{ marginBottom: 12 }}>
              <Typography.Text strong>{field}</Typography.Text>
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>{result.field_tips[field]}</Typography.Text>
              {field === '具体地点' && <Input style={{ marginTop: 6 }} placeholder="请输入具体地点" onChange={e => { if (e.target.value) saveEdit('identified_location', e.target.value) }} />}
              {field === '发生时间' && <Input style={{ marginTop: 6 }} placeholder="请输入发生时间" onChange={e => { if (e.target.value) saveEdit('identified_time', e.target.value) }} />}
              {field === '涉及对象' && <Input style={{ marginTop: 6 }} placeholder="请输入涉及对象" onChange={e => { if (e.target.value) saveEdit('identified_target', e.target.value) }} />}
            </div>
          ))}
        </Card>
      )}
      {result.missing_fields.length === 0 && (
        <Alert style={{ marginTop: 20 }} type="success" showIcon icon={<CheckCircleOutlined />} message="信息完整" description="您的诉求信息已经足够完整，可以直接提交。" />
      )}

      {/* 规范化诉求 */}
      <Card className="surface" style={{ marginTop: 20 }} title="规范化诉求描述" extra={<Tag>AI 生成</Tag>}>
        <TextArea value={normalizedText} onChange={e => setNormalizedText(e.target.value)} rows={4} style={{ marginBottom: 12 }} />
        <Space>
          <Button type={useNormalized ? 'primary' : 'default'} onClick={() => setUseNormalized(true)}>使用此版本</Button>
          <Button onClick={() => { setNormalizedText(form.getFieldValue('description') || ''); setUseNormalized(false) }}>保留原文</Button>
          <Button loading={analyze.isPending} onClick={() => analyze.mutate(form.getFieldsValue())}>重新生成</Button>
        </Space>
      </Card>

      {/* 办理建议 */}
      {result.recommended_department && (
        <Card className="surface" style={{ marginTop: 20 }} title="办理建议">
          <Descriptions size="small" column={1} items={[
            { key: 'dept', label: '推荐受理部门', children: <Tag color="cyan">{result.recommended_department}</Tag> },
            { key: 'reason', label: '推荐理由', children: result.department_reason },
          ]} />
          <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>最终受理部门由坐席工作人员确认，此建议仅供参考。</Typography.Text>
        </Card>
      )}

      {/* 底部操作 */}
      <Divider />
      <Space size="middle">
        <Button onClick={saveDraft}>保存草稿</Button>
        <Button type="primary" size="large" icon={<SendOutlined />} loading={submit.isPending} onClick={() => submit.mutate()}>确认提交工单</Button>
      </Space>
    </>}
  </>
}
