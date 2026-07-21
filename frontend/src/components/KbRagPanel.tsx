import { useState } from 'react'
import { Alert, Button, Card, Collapse, Empty, Form, Input, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { BulbOutlined, CopyOutlined, DislikeOutlined, LikeOutlined, QuestionCircleOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { ragQuery, submitKbFeedback } from '../api/kb'
import type { KbCitation, KbRagAnswer, KbRagQuery, Role } from '../types'
import { PageHeader } from './PageHeader'

const { TextArea } = Input

const roleLabels: Record<Role, string> = {
  citizen: '市民', agent: '坐席', department_staff: '部门人员', admin: '管理员',
}

const domainOptions = [
  '户籍', '教育', '医疗', '社保', '就业', '住房', '交通', '环保',
  '市场监管', '城管', '民政', '税务', '公安', '其他',
].map(v => ({ label: v, value: v }))

const audienceOptions = [
  '居民', '企业', '个体工商户', '老年人', '学生', '失业人员', '残疾人', '低保户', '其他',
].map(v => ({ label: v, value: v }))

const regionOptions = ['本市', '本区', '本街道', '本社区'].map(v => ({ label: v, value: v }))

interface Props {
  /** 角色专属标题/描述 */
  title?: string
  eyebrow?: string
  description?: string
  /** 是否允许使用元数据筛选（坐席/部门/管理员允许） */
  enableFilters?: boolean
}

/**
 * 政策咨询 RAG 查询面板。
 * - 市民：9 段式回答 + 反馈
 * - 坐席/部门/管理员：增强筛选 + 详细引用 + 反馈
 */
export function KbRagPanel({ title, eyebrow, description, enableFilters = false }: Props) {
  const { user } = useAuth()
  const [form] = Form.useForm<KbRagQuery>()
  const [result, setResult] = useState<KbRagAnswer | null>(null)
  const [feedbackSent, setFeedbackSent] = useState(false)

  const query = useMutation({
    mutationFn: (payload: KbRagQuery) => ragQuery(payload),
    onSuccess: (data) => {
      setResult(data)
      setFeedbackSent(false)
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '检索失败，请稍后重试'),
  })

  const feedback = useMutation({
    mutationFn: async (type: 'helpful' | 'inaccurate' | 'outdated' | 'no_answer') => {
      if (!result) return
      await submitKbFeedback({
        query_text: form.getFieldValue('query') || '',
        answer_text: result.answer,
        document_ids: result.citations.map(c => c.doc_id),
        feedback_type: type,
        comment: '',
        route: roleToRoute(user?.role),
      })
    },
    onSuccess: () => { setFeedbackSent(true); message.success('反馈已记录，感谢您的支持') },
    onError: e => message.error(e instanceof ApiError ? e.message : '反馈提交失败'),
  })

  const handleSubmit = (values: KbRagQuery) => {
    if (!values.query?.trim()) {
      message.warning('请输入您要咨询的问题')
      return
    }
    query.mutate(values)
  }

  const handleRegenerate = () => {
    const v = form.getFieldsValue()
    if (v.query?.trim()) query.mutate(v)
  }

  return (
    <>
      <PageHeader
        eyebrow={eyebrow || 'POLICY RAG'}
        title={title || '政策咨询'}
        description={description || '基于政务知识库的智能问答，回答均附引用来源，未检索到依据时不会编造政策。'}
      />
      <Card className="surface" style={{ marginBottom: 20 }}>
        <Alert
          showIcon
          icon={<WarningOutlined />}
          type="info"
          message="使用须知"
          description="本系统只依据已发布的公开政策、办事指南、常见问题等回答。如未检索到依据，建议拨打 12345 热线或前往窗口咨询。"
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="query"
            label="您要咨询的政策问题"
            rules={[{ required: true, message: '请输入咨询问题' }, { min: 2, max: 2000 }]}
          >
            <TextArea
              rows={3}
              placeholder="例如：本市低保申请需要哪些材料？办理流程是什么？"
              aria-label="政策咨询问题"
            />
          </Form.Item>
          {enableFilters && (
            <Space size="middle" wrap style={{ marginBottom: 8 }}>
              <Form.Item name="region" label="地区" style={{ marginBottom: 0 }}>
                <Select allowClear placeholder="不限" style={{ width: 140 }} options={regionOptions} />
              </Form.Item>
              <Form.Item name="domain" label="领域" style={{ marginBottom: 0 }}>
                <Select allowClear placeholder="不限" style={{ width: 160 }} options={domainOptions} />
              </Form.Item>
              <Form.Item name="audience" label="人群" style={{ marginBottom: 0 }}>
                <Select allowClear placeholder="不限" style={{ width: 160 }} options={audienceOptions} />
              </Form.Item>
            </Space>
          )}
          <Form.Item style={{ marginBottom: 0 }}>
            <Space>
              <Button type="primary" htmlType="submit" loading={query.isPending} icon={<BulbOutlined />}>
                查询政策
              </Button>
              {result && (
                <Button onClick={handleRegenerate} loading={query.isPending} icon={<ReloadOutlined />}>
                  重新生成
                </Button>
              )}
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {query.isPending && (
        <Card className="surface" style={{ textAlign: 'center', padding: 32 }}>
          <Spin size="large" />
          <div style={{ marginTop: 12 }}>
            <Typography.Text type="secondary">正在检索政策库并生成回答…</Typography.Text>
          </div>
        </Card>
      )}

      {result && !query.isPending && (
        <KbRagResultCard
          result={result}
          role={user?.role}
          feedbackSent={feedbackSent}
          onFeedback={(t) => feedback.mutate(t)}
          feedbackLoading={feedback.isPending}
        />
      )}
    </>
  )
}

function roleToRoute(role?: Role) {
  switch (role) {
    case 'citizen': return 'citizen_query'
    case 'agent': return 'agent_query'
    case 'department_staff': return 'dept_query'
    case 'admin': return 'admin_query'
    default: return 'rag_query'
  }
}

function KbRagResultCard({
  result, role, feedbackSent, onFeedback, feedbackLoading,
}: {
  result: KbRagAnswer
  role?: Role
  feedbackSent: boolean
  onFeedback: (t: 'helpful' | 'inaccurate' | 'outdated' | 'no_answer') => void
  feedbackLoading: boolean
}) {
  return (
    <Card
      className="surface"
      title={
        <Space>
          <Typography.Text strong>政策咨询结果</Typography.Text>
          {result.no_evidence ? (
            <Tag color="orange">未检索到依据</Tag>
          ) : (
            <Tag color="green">检索到 {result.retrieval_count} 条来源</Tag>
          )}
          {role && <Tag>{roleLabels[role]}视角</Tag>}
          {result.provider && <Tag color="blue">{result.provider}</Tag>}
        </Space>
      }
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          耗时 {result.latency_ms} ms
        </Typography.Text>
      }
    >
      {result.no_evidence ? (
        <Alert
          type="warning"
          showIcon
          icon={<QuestionCircleOutlined />}
          message="未检索到有效依据"
          description={result.answer}
        />
      ) : (
        <>
          <Typography.Paragraph
            copyable={{ icon: [<CopyOutlined key="c" />, '复制回答'] }}
            style={{ whiteSpace: 'pre-wrap', marginBottom: 16 }}
          >
            {result.answer}
          </Typography.Paragraph>

          <Divider />

          <Typography.Title level={5}>引用来源</Typography.Title>
          {result.citations.length === 0 ? (
            <Empty description="无引用" />
          ) : (
            <Collapse
              size="small"
              items={result.citations.map(c => ({
                key: c.index,
                label: (
                  <Space wrap>
                    <Tag color="blue">来源{c.index}</Tag>
                    <Typography.Text strong>{c.title}</Typography.Text>
                    {c.doc_number && <Typography.Text type="secondary">{c.doc_number}</Typography.Text>}
                    {c.department && <Tag>{c.department}</Tag>}
                    {c.is_expired ? (
                      <Tag color="red">已失效</Tag>
                    ) : (
                      <Tag color="green">有效</Tag>
                    )}
                    {typeof c.score === 'number' && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        相关度 {Math.round(c.score * 100) / 100}
                      </Typography.Text>
                    )}
                  </Space>
                ),
                children: <CitationDetail citation={c} />,
              }))}
            />
          )}

          <Divider />

          <Space>
            <Typography.Text type="secondary">本次回答是否有帮助？</Typography.Text>
            <Button
              size="small"
              icon={<LikeOutlined />}
              disabled={feedbackSent}
              loading={feedbackLoading}
              onClick={() => onFeedback('helpful')}
            >有帮助</Button>
            <Button
              size="small"
              icon={<DislikeOutlined />}
              disabled={feedbackSent}
              loading={feedbackLoading}
              onClick={() => onFeedback('inaccurate')}
            >不准确</Button>
            <Button
              size="small"
              disabled={feedbackSent}
              loading={feedbackLoading}
              onClick={() => onFeedback('outdated')}
            >政策过时</Button>
            <Button
              size="small"
              disabled={feedbackSent}
              loading={feedbackLoading}
              onClick={() => onFeedback('no_answer')}
            >未解答</Button>
            {feedbackSent && <Typography.Text type="success">已记录</Typography.Text>}
          </Space>
        </>
      )}
    </Card>
  )
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
        {citation.expires_at && <Tag color={citation.is_expired ? 'red' : 'default'}>
          失效：{citation.expires_at.slice(0, 10)}
        </Tag>}
        {citation.kb_type && <Tag>{kbTypeLabel(citation.kb_type)}</Tag>}
        {citation.version && <Tag>v{citation.version}</Tag>}
      </Space>
    </div>
  )
}

function Divider() {
  return <div style={{ borderTop: '1px solid #f0f0f0', margin: '16px 0' }} />
}

function kbTypeLabel(t: string) {
  const map: Record<string, string> = {
    policy: '公开政策', guide: '办事指南', faq: '常见问题',
    internal: '内部制度', procedure: '办理流程', case: '历史案例',
  }
  return map[t] || t
}
