import { useState } from 'react'
import {
  Alert, Badge, Button, Card, Col, Descriptions, Empty, Form, Input, InputNumber,
  Modal, Popconfirm, Progress, Row, Select, Space, Spin, Statistic, Table, Tabs,
  Tag, Typography, message,
} from 'antd'
import {
  AlertOutlined, AuditOutlined, BulbOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ExperimentOutlined, PlayCircleOutlined,
  ThunderboltOutlined, ToolOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import {
  createKbEvalCase, listKbEvalCases, listKbFeedback, listKbNoAnswer,
  listKbDocuments, ragQuery, ragRetrieve, resolveKbNoAnswer, reviewKbDocument,
  runKbEval,
} from '../api/kb'
import type {
  KbDocStatus, KbDocument, KbEvalCase, KbEvalCasePayload, KbEvalRunResult,
  KbFeedback, KbFeedbackType, KbNoAnswer, KbNoAnswerStatus, KbRagAnswer,
  KbRetrievalResult,
} from '../types'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { KbRagPanel } from '../components/KbRagPanel'

const { TextArea } = Input

const STATUS_LABELS: Record<KbDocStatus, { label: string; color: string }> = {
  DRAFT: { label: '草稿', color: 'default' },
  REVIEWING: { label: '待审核', color: 'processing' },
  PUBLISHED: { label: '已发布', color: 'success' },
  REJECTED: { label: '已驳回', color: 'error' },
  WITHDRAWN: { label: '已下线', color: 'warning' },
  EXPIRED: { label: '已失效', color: 'default' },
  PARSE_FAILED: { label: '解析失败', color: 'error' },
}

export function AdminKbPage() {
  return (
    <>
      <PageHeader
        eyebrow="ADMIN AI KB"
        title="知识库治理审核"
        description="管理员可审核发布文档、运行 RAG 测试台、管理评测集、处理无答案问题与查询反馈。"
      />
      <Tabs
        defaultActiveKey="review"
        items={[
          { key: 'review', label: '文档审核', children: <ReviewTab /> },
          { key: 'testbed', label: 'RAG 测试台', children: <TestbedTab /> },
          { key: 'eval', label: '评测中心', children: <EvalTab /> },
          { key: 'no_answer', label: '无答案问题', children: <NoAnswerTab /> },
          { key: 'feedback', label: '反馈审计', children: <FeedbackTab /> },
        ]}
      />
    </>
  )
}

// ========== Review Tab ==========

function ReviewTab() {
  const qc = useQueryClient()
  const list = useQuery({
    queryKey: ['kb', 'documents', 'reviewing'],
    queryFn: () => listKbDocuments({ status: 'REVIEWING', page: 1, page_size: 50 }),
  })

  const review = useMutation({
    mutationFn: ({ docId, decision, comment }: { docId: number; decision: 'publish' | 'reject'; comment: string }) =>
      reviewKbDocument(docId, decision, comment),
    onSuccess: (_d, vars) => {
      message.success(vars.decision === 'publish' ? '已通过审核并发布' : '已驳回')
      void qc.invalidateQueries({ queryKey: ['kb', 'documents'] })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '审核失败'),
  })

  return (
    <Card className="surface">
      <Alert
        type="info"
        showIcon
        icon={<AuditOutlined />}
        message="待审核文档"
        description="管理员需逐项核对文档标题、文号、公开范围与正文内容后决定是否发布。已驳回文档将退回为草稿状态。"
        style={{ marginBottom: 16 }}
      />
      {list.isError ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          loading={list.isLoading}
          dataSource={list.data?.items}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '文号', dataIndex: 'doc_number', width: 140, ellipsis: true },
            { title: '类型', dataIndex: 'kb_type', width: 100,
              render: (t: string) => <Tag>{kbTypeLabel(t)}</Tag> },
            { title: '公开范围', dataIndex: 'visibility', width: 100,
              render: (v: string) => <Tag>{v}</Tag> },
            { title: '版本', dataIndex: 'version', width: 60 },
            { title: '部门', dataIndex: 'department_name', width: 120, ellipsis: true },
            { title: '提交时间', dataIndex: 'updated_at', width: 110,
              render: (v?: string | null) => v ? v.slice(0, 10) : '—' },
            { title: '操作', key: 'actions', width: 200, fixed: 'right' as const,
              render: (_: unknown, r: KbDocument) => (
                <Space>
                  <ReviewAction docId={r.id} onReview={(decision, comment) => review.mutate({ docId: r.id, decision, comment })} loading={review.isPending} />
                </Space>
              ) },
          ]}
        />
      )}
    </Card>
  )
}

function ReviewAction({ docId, onReview, loading }: { docId: number; onReview: (decision: 'publish' | 'reject', comment: string) => void; loading: boolean }) {
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState('')
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>审核</Button>
      <Modal
        open={open}
        title={`审核文档 #${docId}`}
        onCancel={() => setOpen(false)}
        footer={[
          <Button key="reject" danger loading={loading} onClick={() => { onReview('reject', comment); setOpen(false) }}>
            驳回
          </Button>,
          <Button key="publish" type="primary" loading={loading} onClick={() => { onReview('publish', comment); setOpen(false) }}>
            通过并发布
          </Button>,
        ]}
      >
        <Input.TextArea rows={4} placeholder="审核意见（可选）" value={comment} onChange={e => setComment(e.target.value)} />
      </Modal>
    </>
  )
}

// ========== RAG Testbed Tab ==========

function TestbedTab() {
  const [mode, setMode] = useState<'answer' | 'retrieve'>('answer')
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<{ region?: string; domain?: string; audience?: string }>({})
  const [result, setResult] = useState<KbRagAnswer | null>(null)
  const [retrieveResult, setRetrieveResult] = useState<KbRetrievalResult | null>(null)

  const run = useMutation({
    mutationFn: async () => {
      if (!query.trim()) throw new Error('请输入测试查询')
      if (mode === 'answer') return { type: 'answer' as const, data: await ragQuery({ query, ...filters }) }
      return { type: 'retrieve' as const, data: await ragRetrieve({ query, ...filters }) }
    },
    onSuccess: (r) => {
      if (r.type === 'answer') setResult(r.data)
      else setRetrieveResult(r.data)
      message.success('测试完成')
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '测试失败'),
  })

  return (
    <>
      <Card className="surface" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          icon={<ExperimentOutlined />}
          message="RAG 测试台"
          description="管理员可在发布前对任意查询进行端到端 RAG 测试，验证检索命中率与回答质量。可切换“回答模式”（含 LLM 生成）与“仅检索模式”（仅返回切片）。"
          style={{ marginBottom: 16 }}
        />
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            <Select value={mode} onChange={setMode} style={{ width: 140 }}
              options={[{ value: 'answer', label: '回答模式' }, { value: 'retrieve', label: '仅检索模式' }]} />
            <Input placeholder="地区" allowClear style={{ width: 120 }} onChange={e => setFilters(f => ({ ...f, region: e.target.value || undefined }))} />
            <Input placeholder="领域" allowClear style={{ width: 120 }} onChange={e => setFilters(f => ({ ...f, domain: e.target.value || undefined }))} />
            <Input placeholder="人群" allowClear style={{ width: 120 }} onChange={e => setFilters(f => ({ ...f, audience: e.target.value || undefined }))} />
          </Space>
          <Input.TextArea
            rows={3}
            placeholder="输入测试查询，例如：本市低保申请需要哪些材料？"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending} onClick={() => run.mutate()}>
            运行测试
          </Button>
        </Space>
      </Card>

      {mode === 'answer' && result && (
        <Card className="surface" title={<Space><BulbOutlined />回答结果</Space>}
          extra={<Tag color={result.no_evidence ? 'orange' : 'green'}>{result.no_evidence ? '无依据' : `${result.retrieval_count} 条来源`}</Tag>}>
          <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap', marginBottom: 16 }}>
            {result.answer}
          </Typography.Paragraph>
          <Descriptions size="small" column={4} bordered>
            <Descriptions.Item label="检索来源数">{result.retrieval_count}</Descriptions.Item>
            <Descriptions.Item label="耗时">{result.latency_ms} ms</Descriptions.Item>
            <Descriptions.Item label="Provider">{result.provider || '—'}</Descriptions.Item>
            <Descriptions.Item label="Model">{result.model || '—'}</Descriptions.Item>
          </Descriptions>
          {result.citations.length > 0 && (
            <>
              <Typography.Title level={5} style={{ marginTop: 16 }}>引用列表</Typography.Title>
              <Table
                size="small"
                rowKey="index"
                pagination={false}
                dataSource={result.citations}
                columns={[
                  { title: '#', dataIndex: 'index', width: 50 },
                  { title: '标题', dataIndex: 'title', ellipsis: true },
                  { title: '文号', dataIndex: 'doc_number', width: 140, ellipsis: true },
                  { title: '部门', dataIndex: 'department', width: 120 },
                  { title: '状态', width: 80, render: (_: unknown, r: typeof result.citations[0]) =>
                    r.is_expired ? <Tag color="red">已失效</Tag> : <Tag color="green">有效</Tag> },
                  { title: '相关度', dataIndex: 'score', width: 80,
                    render: (s?: number) => s != null ? Math.round(s * 100) / 100 : '—' },
                ]}
              />
            </>
          )}
        </Card>
      )}

      {mode === 'retrieve' && retrieveResult && (
        <Card className="surface" title={<Space><ThunderboltOutlined />检索结果</Space>}
          extra={<Tag color="blue">可访问文档 {retrieveResult.accessible_doc_count}</Tag>}>
          {retrieveResult.chunks.length === 0 ? (
            <Empty description="未检索到切片" />
          ) : (
            <Table
              size="small"
              rowKey="chunk_id"
              pagination={false}
              dataSource={retrieveResult.chunks}
              columns={[
                { title: '切片ID', dataIndex: 'chunk_id', width: 80 },
                { title: '相关度', dataIndex: 'score', width: 100,
                  render: (s: number) => <Progress percent={Math.round(s * 100)} size="small" /> },
                { title: '字符数', dataIndex: 'char_count', width: 80 },
                { title: '状态', width: 80, render: (_: unknown, r: typeof retrieveResult.chunks[0]) =>
                  r.is_expired ? <Tag color="red">已失效</Tag> : <Tag color="green">有效</Tag> },
                { title: '内容', dataIndex: 'content', ellipsis: true,
                  render: (c: string) => <Typography.Text>{c.slice(0, 200)}…</Typography.Text> },
              ]}
            />
          )}
        </Card>
      )}
    </>
  )
}

// ========== Evaluation Tab ==========

function EvalTab() {
  const qc = useQueryClient()
  const [scenario, setScenario] = useState<string | undefined>()
  const [runResult, setRunResult] = useState<KbEvalRunResult | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const cases = useQuery({
    queryKey: ['kb', 'eval', 'cases', scenario],
    queryFn: () => listKbEvalCases(scenario),
  })

  const run = useMutation({
    mutationFn: (role: string) => runKbEval(scenario, role),
    onSuccess: (data) => {
      setRunResult(data)
      message.success(`评测完成，共 ${data.total} 个用例`)
      void qc.invalidateQueries({ queryKey: ['kb', 'eval'] })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '评测失败'),
  })

  return (
    <>
      <Card className="surface" style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          icon={<ExperimentOutlined />}
          message="RAG 评测中心"
          description="基于预置评测集运行端到端测试，量化检索命中率、引用准确率、忠实度、失效政策拦截率、权限隔离率与平均延迟。"
          style={{ marginBottom: 16 }}
        />
        <Space wrap>
          <Input placeholder="按场景过滤（可选）" allowClear style={{ width: 200 }}
            value={scenario} onChange={e => setScenario(e.target.value || undefined)} />
          <Select defaultValue="citizen" style={{ width: 140 }} id="eval-role"
            options={[
              { value: 'citizen', label: '市民视角' },
              { value: 'agent', label: '坐席视角' },
              { value: 'department_staff', label: '部门人员视角' },
              { value: 'admin', label: '管理员视角' },
            ]}
            onChange={(v) => { /* store in DOM dataset */ const el = document.getElementById('eval-role') as any; if (el) el.dataset.role = v }} />
          <Button type="primary" icon={<PlayCircleOutlined />} loading={run.isPending}
            onClick={() => {
              const el = document.getElementById('eval-role') as any
              const role = el?.dataset.role || 'citizen'
              run.mutate(role)
            }}>
            运行评测
          </Button>
          <Button icon={<ToolOutlined />} onClick={() => setCreateOpen(true)}>新建用例</Button>
        </Space>
      </Card>

      {runResult && (
        <Card className="surface" title="评测结果" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={4}><Statistic title="用例总数" value={runResult.total} /></Col>
            <Col span={4}><Statistic title="检索命中率" value={pct(runResult.metrics.retrieval_hit_rate)} suffix="%" /></Col>
            <Col span={4}><Statistic title="引用准确率" value={pct(runResult.metrics.citation_correct_rate)} suffix="%" /></Col>
            <Col span={4}><Statistic title="忠实度" value={pct(runResult.metrics.answer_faithful_rate)} suffix="%" /></Col>
            <Col span={4}><Statistic title="失效拦截率" value={pct(runResult.metrics.expired_policy_blocked_rate)} suffix="%" /></Col>
            <Col span={4}><Statistic title="权限隔离率" value={pct(runResult.metrics.permission_isolated_rate)} suffix="%" /></Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 12 }}>
            <Col span={4}><Statistic title="无答案率" value={pct(runResult.metrics.no_answer_rate)} suffix="%" /></Col>
            <Col span={4}><Statistic title="平均延迟" value={runResult.metrics.avg_latency_ms} suffix="ms" /></Col>
          </Row>
          <Table
            size="small"
            rowKey="case_id"
            style={{ marginTop: 16 }}
            pagination={false}
            dataSource={runResult.runs}
            columns={[
              { title: '用例ID', dataIndex: 'case_id', width: 70 },
              { title: '标题', dataIndex: 'title', ellipsis: true },
              { title: '场景', dataIndex: 'scenario', width: 120 },
              { title: '检索命中', dataIndex: 'retrieval_hit', width: 80,
                render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> },
              { title: '引用准确', dataIndex: 'citation_correct', width: 80,
                render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> },
              { title: '忠实', dataIndex: 'answer_faithful', width: 60,
                render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> },
              { title: '失效拦截', dataIndex: 'expired_policy_blocked', width: 80,
                render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> },
              { title: '权限隔离', dataIndex: 'permission_isolated', width: 80,
                render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> },
              { title: '无答案', dataIndex: 'no_evidence', width: 70,
                render: (v: boolean) => v ? <Tag color="orange">是</Tag> : '—' },
              { title: '耗时', dataIndex: 'latency_ms', width: 80, render: (v: number) => `${v}ms` },
            ]}
          />
        </Card>
      )}

      <Card className="surface" title={`评测用例（${cases.data?.length || 0}）`}>
        {cases.isError ? (
          <ErrorState error={cases.error} retry={() => cases.refetch()} />
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={cases.isLoading}
            dataSource={cases.data}
            pagination={false}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 70 },
              { title: '标题', dataIndex: 'title', ellipsis: true },
              { title: '场景', dataIndex: 'scenario', width: 120 },
              { title: '角色', dataIndex: 'expected_role', width: 100 },
              { title: '查询', dataIndex: 'query', ellipsis: true },
              { title: '期望命中', dataIndex: 'expected_doc_ids', width: 120, ellipsis: true },
              { title: '期望无答案', dataIndex: 'expected_no_answer', width: 90,
                render: (v: boolean) => v ? <Tag color="orange">是</Tag> : '—' },
              { title: '启用', dataIndex: 'is_active', width: 60,
                render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
            ]}
          />
        )}
      </Card>

      {createOpen && <CreateEvalCaseModal onClose={() => setCreateOpen(false)} />}
    </>
  )
}

function CreateEvalCaseModal({ onClose }: { onClose: () => void }) {
  const [form] = Form.useForm<KbEvalCasePayload>()
  const qc = useQueryClient()
  const create = useMutation({
    mutationFn: (values: KbEvalCasePayload) => createKbEvalCase(values),
    onSuccess: () => {
      message.success('用例已创建')
      void qc.invalidateQueries({ queryKey: ['kb', 'eval'] })
      onClose()
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '创建失败'),
  })
  return (
    <Modal
      open
      title="新建评测用例"
      onCancel={onClose}
      onOk={() => form.validateFields().then(values => create.mutate(values))}
      confirmLoading={create.isPending}
      width={700}
    >
      <Form form={form} layout="vertical" initialValues={{ expected_role: 'citizen', is_active: true }}>
        <Form.Item name="title" label="标题" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
        <Form.Item name="scenario" label="场景" rules={[{ required: true }]}><Input placeholder="如：低保咨询" /></Form.Item>
        <Form.Item name="query" label="查询问题" rules={[{ required: true, min: 2 }]}><TextArea rows={2} /></Form.Item>
        <Form.Item name="expected_role" label="期望角色">
          <Select options={[
            { value: 'citizen', label: '市民' },
            { value: 'agent', label: '坐席' },
            { value: 'department_staff', label: '部门人员' },
            { value: 'admin', label: '管理员' },
          ]} />
        </Form.Item>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="expected_doc_ids" label="期望命中（逗号分隔）"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="must_cite_doc_ids" label="必须引用"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="must_not_cite_doc_ids" label="必须不引用"><Input /></Form.Item>
          </Col>
        </Row>
        <Form.Item name="must_avoid_keywords" label="禁止词（逗号分隔）"><Input /></Form.Item>
        <Form.Item name="expected_answer_summary" label="期望答案摘要"><TextArea rows={2} /></Form.Item>
        <Form.Item name="expected_no_answer" label="期望无答案" valuePropName="checked">
          <Select options={[{ value: false, label: '否' }, { value: true, label: '是' }]} />
        </Form.Item>
        <Form.Item name="notes" label="备注"><TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}

// ========== No-Answer Tab ==========

function NoAnswerTab() {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<KbNoAnswerStatus | undefined>()
  const qc = useQueryClient()
  const list = useQuery({
    queryKey: ['kb', 'no-answer', page, status],
    queryFn: () => listKbNoAnswer(page, 20, status),
  })

  const resolve = useMutation({
    mutationFn: ({ id, status, note }: { id: number; status: KbNoAnswerStatus; note: string }) =>
      resolveKbNoAnswer(id, status, note),
    onSuccess: () => {
      message.success('已处理')
      void qc.invalidateQueries({ queryKey: ['kb', 'no-answer'] })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '处理失败'),
  })

  return (
    <Card className="surface">
      <Alert
        type="info"
        showIcon
        icon={<AlertOutlined />}
        message="无答案问题清单"
        description="市民/坐席/部门人员发起的 RAG 查询未检索到依据时，会记录在此。管理员需补充对应政策并标记处理结果。"
        style={{ marginBottom: 16 }}
      />
      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 180 }}
          value={status}
          onChange={(v) => { setStatus(v); setPage(1) }}
          options={[
            { value: 'open', label: '待处理' },
            { value: 'assigned', label: '已分派' },
            { value: 'resolved', label: '已解决' },
            { value: 'wont_fix', label: '不予处理' },
          ]}
        />
      </Space>
      {list.isError ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          loading={list.isLoading}
          dataSource={list.data?.items}
          pagination={{
            current: page, pageSize: 20, total: list.data?.total || 0,
            onChange: setPage,
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '提问时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
            { title: '问题', dataIndex: 'query_text', ellipsis: true },
            { title: '角色', dataIndex: 'role', width: 100 },
            { title: '来源路由', dataIndex: 'route', width: 120 },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (s: KbNoAnswerStatus) => {
                const map = { open: { c: 'orange', l: '待处理' }, assigned: { c: 'blue', l: '已分派' }, resolved: { c: 'green', l: '已解决' }, wont_fix: { c: 'default', l: '不予处理' } }
                return <Tag color={map[s].c}>{map[s].l}</Tag>
              } },
            { title: '处理时间', dataIndex: 'resolved_at', width: 150,
              render: (v?: string | null) => v ? v.replace('T', ' ').slice(0, 19) : '—' },
            { title: '操作', key: 'actions', width: 200, fixed: 'right' as const,
              render: (_: unknown, r: KbNoAnswer) => (
                <ResolveAction na={r} onResolve={(s, note) => resolve.mutate({ id: r.id, status: s, note })} loading={resolve.isPending} />
              ) },
          ]}
        />
      )}
    </Card>
  )
}

function ResolveAction({ na, onResolve, loading }: { na: KbNoAnswer; onResolve: (s: KbNoAnswerStatus, note: string) => void; loading: boolean }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<KbNoAnswerStatus>('resolved')
  const [note, setNote] = useState('')
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)} disabled={na.status === 'resolved' || na.status === 'wont_fix'}>处理</Button>
      <Modal
        open={open}
        title={`处理无答案问题 #${na.id}`}
        onCancel={() => setOpen(false)}
        onOk={() => { onResolve(status, note); setOpen(false) }}
        confirmLoading={loading}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text type="secondary">问题：{na.query_text}</Typography.Text>
          <Select value={status} onChange={setStatus} style={{ width: '100%' }}
            options={[
              { value: 'resolved', label: '已解决（已补充政策）' },
              { value: 'assigned', label: '已分派（待补充政策）' },
              { value: 'wont_fix', label: '不予处理' },
            ]} />
          <Input.TextArea rows={3} placeholder="处理说明（可选）" value={note} onChange={e => setNote(e.target.value)} />
        </Space>
      </Modal>
    </>
  )
}

// ========== Feedback Tab ==========

function FeedbackTab() {
  const [page, setPage] = useState(1)
  const [feedbackType, setFeedbackType] = useState<KbFeedbackType | undefined>()
  const list = useQuery({
    queryKey: ['kb', 'feedback', page, feedbackType],
    queryFn: () => listKbFeedback(page, 20, feedbackType),
  })

  return (
    <Card className="surface">
      <Alert
        type="info"
        showIcon
        icon={<AuditOutlined />}
        message="RAG 反馈审计"
        description="管理员可查看所有角色对 RAG 回答的反馈，结合反馈类型优化知识库内容。"
        style={{ marginBottom: 16 }}
      />
      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="全部反馈类型"
          style={{ width: 180 }}
          value={feedbackType}
          onChange={(v) => { setFeedbackType(v); setPage(1) }}
          options={[
            { value: 'helpful', label: '有帮助' },
            { value: 'inaccurate', label: '不准确' },
            { value: 'outdated', label: '政策过时' },
            { value: 'no_answer', label: '未解答' },
          ]}
        />
      </Space>
      {list.isError ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          loading={list.isLoading}
          dataSource={list.data?.items}
          pagination={{
            current: page, pageSize: 20, total: list.data?.total || 0,
            onChange: setPage,
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
            { title: '反馈类型', dataIndex: 'feedback_type', width: 100,
              render: (t: KbFeedbackType) => {
                const map = { helpful: { c: 'green', l: '有帮助' }, inaccurate: { c: 'red', l: '不准确' }, outdated: { c: 'orange', l: '过时' }, no_answer: { c: 'default', l: '未解答' } }
                return <Tag color={map[t].c}>{map[t].l}</Tag>
              } },
            { title: '用户ID', dataIndex: 'user_id', width: 80 },
            { title: '来源路由', dataIndex: 'route', width: 120 },
            { title: '问题', dataIndex: 'query_text', ellipsis: true },
            { title: '引用文档', dataIndex: 'document_ids', width: 140,
              render: (ids: string[]) => ids.join(', ') || '—' },
            { title: '评论', dataIndex: 'comment', ellipsis: true },
          ]}
        />
      )}
    </Card>
  )
}

// ========== Utils ==========

function kbTypeLabel(t: string) {
  const map: Record<string, string> = {
    policy: '公开政策', guide: '办事指南', faq: '常见问题',
    internal: '内部制度', procedure: '办理流程', case: '历史案例',
  }
  return map[t] || t
}

function pct(v: number) {
  return Math.round(v * 1000) / 10
}
