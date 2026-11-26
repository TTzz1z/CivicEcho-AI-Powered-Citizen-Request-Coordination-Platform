import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Card, Divider, Form, Input, Select, Space, Tag, Typography } from 'antd'
import { BulbOutlined, CopyOutlined, DislikeOutlined, LikeOutlined, QuestionCircleOutlined, ReloadOutlined, StopOutlined, WarningOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { streamRagQuery, submitKbFeedback } from '../api/kb'
import type { KbFeedbackPayload, KbRagAnswer, KbRagQuery, Role } from '../types'
import { PageHeader } from './PageHeader'
import { filterDisplayCitations, PolicyCitations } from './PolicyCitations'
import { WorkspaceError, WorkspaceLoading } from './WorkspaceState'

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

type SearchAnswer = { data: KbRagAnswer; question: string; stopped?: boolean }
type FeedbackType = KbFeedbackPayload['feedback_type']
type StreamPhase = 'idle' | 'retrieving' | 'streaming'

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
  const { message } = App.useApp()
  const [form] = Form.useForm<KbRagQuery>()
  const [phase, setPhase] = useState<StreamPhase>('idle')
  const [result, setResult] = useState<SearchAnswer | null>(null)
  const [streamingResult, setStreamingResult] = useState<SearchAnswer | null>(null)
  const [streamError, setStreamError] = useState<unknown>(null)
  const [rated, setRated] = useState<SearchAnswer | null>(null)
  const activeRequest = useRef<AbortController | null>(null)
  const streamingRef = useRef<SearchAnswer | null>(null)

  useEffect(() => () => {
    activeRequest.current?.abort()
    activeRequest.current = null
  }, [])

  const feedback = useMutation({
    mutationFn: ({ answer, type }: { answer: SearchAnswer; type: FeedbackType }) => submitKbFeedback({
      query_text: answer.question,
      answer_text: answer.data.answer,
      document_ids: filterDisplayCitations(answer.data.citations, answer.data.no_evidence).map(c => c.doc_id),
      feedback_type: type,
      comment: '',
      route: roleToRoute(user?.role),
    }),
    onSuccess: (_, submission) => { setRated(submission.answer); message.success('反馈已记录，感谢您的支持') },
    onError: e => message.error(e instanceof ApiError ? e.message : '反馈提交失败'),
  })

  const runStreamQuery = async (values: KbRagQuery) => {
    const question = values.query?.trim()
    if (!question) {
      message.warning('请输入您要咨询的问题')
      return
    }
    if (activeRequest.current) return

    const controller = new AbortController()
    activeRequest.current = controller
    streamingRef.current = null
    setStreamingResult(null)
    setStreamError(null)
    setPhase('retrieving')

    const isCurrent = () => activeRequest.current === controller && !controller.signal.aborted

    try {
      let receivedDone = false
      const done = await streamRagQuery(
        { ...values, query: question },
        {
          onMeta: meta => {
            if (!isCurrent()) return
            const initial: SearchAnswer = {
              question,
              data: {
                answer: streamingRef.current?.data.answer ?? '',
                citations: meta.citations,
                no_evidence: meta.no_evidence,
                retrieval_count: meta.retrieval_count,
                latency_ms: 0,
                generated_at: new Date().toISOString(),
              },
            }
            streamingRef.current = initial
            setStreamingResult(initial)
            setPhase('streaming')
          },
          onDelta: chunk => {
            if (!isCurrent()) return
            const base = streamingRef.current ?? {
              question,
              data: {
                answer: '',
                citations: [],
                no_evidence: false,
                retrieval_count: 0,
                latency_ms: 0,
                generated_at: new Date().toISOString(),
              },
            }
            const updated: SearchAnswer = {
              question: base.question,
              data: {
                ...base.data,
                answer: `${base.data.answer}${chunk}`,
              },
            }
            streamingRef.current = updated
            setStreamingResult(updated)
            setPhase('streaming')
          },
          onDone: payload => {
            if (!isCurrent()) return
            receivedDone = true
            streamingRef.current = null
            setStreamingResult(null)
            setResult({ data: payload, question })
            setPhase('idle')
          },
        },
        controller.signal,
      )
      if (!receivedDone && isCurrent() && done) {
        streamingRef.current = null
        setStreamingResult(null)
        setResult({ data: done, question })
        setPhase('idle')
      }
    } catch (err) {
      if ((err instanceof DOMException && err.name === 'AbortError') || controller.signal.aborted) {
        return
      }
      if (isCurrent()) {
        streamingRef.current = null
        setStreamingResult(null)
        setResult(null)
        setStreamError(err)
        setPhase('idle')
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }
    }
  }

  const stopGeneration = () => {
    const controller = activeRequest.current
    if (!controller) return
    const partial = streamingRef.current
    activeRequest.current = null
    controller.abort()
    streamingRef.current = null
    setStreamingResult(null)
    setStreamError(null)
    setPhase('idle')
    if (partial && partial.data.answer.trim()) {
      setResult({ data: partial.data, question: partial.question, stopped: true })
    }
  }

  const isBusy = phase !== 'idle'

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
          icon={<WarningOutlined aria-hidden />}
          type="info"
          title="使用须知"
          description="本系统只依据已发布的公开政策、办事指南、常见问题等回答。如未检索到依据，建议拨打 12345 热线或前往窗口咨询。"
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical" onFinish={values => void runStreamQuery(values)}>
          <Form.Item
            name="query"
            label="您要咨询的政策问题"
            rules={[{ required: true, message: '请输入咨询问题' }, { min: 2, max: 2000 }]}
          >
            <TextArea
              rows={3}
              maxLength={2000}
              showCount
              placeholder="请输入政策主题或您需要了解的办理事项"
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
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={isBusy} icon={<BulbOutlined aria-hidden />}>
                查询政策
              </Button>
              {isBusy && (
                <Button danger icon={<StopOutlined aria-hidden />} onClick={stopGeneration}>
                  停止生成
                </Button>
              )}
              {result && !isBusy && (
                <Button onClick={() => form.submit()} icon={<ReloadOutlined aria-hidden />}>
                  重新生成
                </Button>
              )}
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {phase === 'retrieving' && (
        <Card className="surface" aria-busy="true">
          <WorkspaceLoading label="正在检索政策资料并生成回答" />
        </Card>
      )}
      {streamError !== null && <WorkspaceError error={streamError} fallback="检索失败，请稍后重试。" retry={() => form.submit()} />}

      {phase === 'streaming' && streamingResult && (
        <KbRagResultCard
          result={streamingResult.data}
          question={streamingResult.question}
          role={user?.role}
          streaming
          showFeedback={false}
          feedbackSent={false}
          onFeedback={() => {}}
          feedbackLoading={false}
        />
      )}

      {result && streamError === null && phase === 'idle' && (
        <KbRagResultCard
          result={result.data}
          question={result.question}
          role={user?.role}
          stopped={result.stopped}
          showFeedback={!result.stopped}
          feedbackSent={rated === result}
          onFeedback={(type) => feedback.mutate({ answer: result, type })}
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
  result, question, role, streaming = false, stopped = false, showFeedback = true, feedbackSent, onFeedback, feedbackLoading,
}: {
  result: KbRagAnswer
  question: string
  role?: Role
  streaming?: boolean
  stopped?: boolean
  showFeedback?: boolean
  feedbackSent: boolean
  onFeedback: (t: FeedbackType) => void
  feedbackLoading: boolean
}) {
  const sources = filterDisplayCitations(result.citations, result.no_evidence)
  return (
    <Card
      className="surface"
      title={
        <Space wrap>
          <Typography.Text strong>政策咨询结果</Typography.Text>
          {streaming && <Tag color="processing">正在生成…</Tag>}
          {stopped && <Tag color="default">已停止生成</Tag>}
          {result.no_evidence ? (
            <Tag color="orange">未检索到依据</Tag>
          ) : (
            <Tag color={sources.length ? 'green' : 'default'}>{sources.length ? `引用 ${sources.length} 条资料` : '无可展示引用'}</Tag>
          )}
          {role && <Tag>{roleLabels[role]}视角</Tag>}
          {!streaming && (result.provider === 'rules' || result.degraded
            ? <Tag color="gold">规则生成</Tag>
            : result.provider && <Tag color="blue">模型来源：{result.model || result.provider}</Tag>)}
          {!streaming && !stopped && <Typography.Text type="secondary" style={{ fontSize: 12 }}>耗时 {result.latency_ms} ms</Typography.Text>}
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" className="policy-result-text">问题：{question}</Typography.Paragraph>
      {result.no_evidence ? (
        <Alert
          type="warning"
          showIcon
          icon={<QuestionCircleOutlined aria-hidden />}
          title="未检索到有效依据"
          description={result.answer || (streaming ? '正在生成引导说明…' : '')}
        />
      ) : (
        <>
          <Typography.Paragraph
            copyable={!streaming && result.answer ? { icon: [<CopyOutlined key="c" />, '复制回答'] } : false}
            className="policy-result-text"
          >
            {result.answer}
            {streaming && <span className="ce-streaming-cursor" aria-hidden="true" />}
          </Typography.Paragraph>

          <PolicyCitations citations={sources} canReadDocument={Boolean(role)} />
        </>
      )}

      {showFeedback && (
        <>
          <Divider />

          <Space wrap>
            <Typography.Text type="secondary">本次回答是否有帮助？</Typography.Text>
            <Button
              size="small"
              icon={<LikeOutlined aria-hidden />}
              disabled={feedbackSent}
              loading={feedbackLoading}
              onClick={() => onFeedback('helpful')}
            >有帮助</Button>
            <Button
              size="small"
              icon={<DislikeOutlined aria-hidden />}
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
