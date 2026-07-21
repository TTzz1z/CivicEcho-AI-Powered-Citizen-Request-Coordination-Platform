import { useState } from 'react'
import {
  Alert, Badge, Button, Card, Col, Collapse, DatePicker, Descriptions, Empty,
  Form, Input, Modal, Popconfirm, Row, Select, Space, Spin, Table, Tabs, Tag,
  Tooltip, Typography, Upload, message,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, DeleteOutlined, DownloadOutlined,
  EditOutlined, FileTextOutlined, InboxOutlined, ReloadOutlined, SearchOutlined,
  UploadOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import {
  createKbDocument, directPublishKbDocument, expireKbDocument, getKbDocument,
  listKbChunks, listKbDocumentVersions, listKbDocuments, listKbFeedback,
  reindexKbDocument, submitKbForReview, updateKbDocument, uploadKbDocument,
  withdrawKbDocument,
} from '../api/kb'
import { listDepartments } from '../api/admin'
import type {
  KbDocStatus, KbDocFilters, KbDocument, KbFeedback, KbFeedbackType,
  KbType, KbVisibility,
} from '../types'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'

const { TextArea } = Input
const { Dragger } = Upload

const KB_TYPE_OPTIONS: { label: string; value: KbType }[] = [
  { label: '公开政策', value: 'policy' },
  { label: '办事指南', value: 'guide' },
  { label: '常见问题', value: 'faq' },
  { label: '部门内部制度', value: 'internal' },
  { label: '标准办理流程', value: 'procedure' },
  { label: '脱敏历史案例', value: 'case' },
]

const VISIBILITY_OPTIONS: { label: string; value: KbVisibility }[] = [
  { label: '公开（市民可见）', value: 'PUBLIC' },
  { label: '本部门可见', value: 'DEPARTMENT' },
  { label: '内部（仅管理员）', value: 'INTERNAL' },
]

const STATUS_LABELS: Record<KbDocStatus, { label: string; color: string }> = {
  DRAFT: { label: '草稿', color: 'default' },
  REVIEWING: { label: '待审核', color: 'processing' },
  PUBLISHED: { label: '已发布', color: 'success' },
  REJECTED: { label: '已驳回', color: 'error' },
  WITHDRAWN: { label: '已下线', color: 'warning' },
  EXPIRED: { label: '已失效', color: 'default' },
  PARSE_FAILED: { label: '解析失败', color: 'error' },
}

export function DepartmentKbPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  return (
    <>
      <PageHeader
        eyebrow="DEPARTMENT KB"
        title="政策知识库管理"
        description={isAdmin
          ? '管理员可管理所有部门的文档、审核发布、重建索引、处理反馈与无答案问题。'
          : '部门人员可上传和管理本部门文档、提交审核，并查询本部门政策库反馈。'}
      />
      <Tabs
        defaultActiveKey="documents"
        items={[
          { key: 'documents', label: '文档管理', children: <DocumentsTab /> },
          { key: 'upload', label: '上传新文档', children: <UploadTab /> },
          { key: 'raw', label: '直接录入', children: <RawContentTab /> },
          { key: 'feedback', label: '反馈与无答案', children: <FeedbackTab /> },
        ]}
      />
    </>
  )
}

// ========== Documents Tab ==========

function DocumentsTab() {
  const { user } = useAuth()
  const [filters, setFilters] = useState<KbDocFilters>({ page: 1, page_size: 20 })
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null)
  const qc = useQueryClient()

  const list = useQuery({
    queryKey: ['kb', 'documents', filters],
    queryFn: () => listKbDocuments(filters),
  })

  const departments = useQuery({
    queryKey: ['departments'],
    queryFn: listDepartments,
    enabled: user?.role === 'admin',
  })

  const submitReview = useMutation({
    mutationFn: (docId: number) => submitKbForReview(docId),
    onSuccess: () => { message.success('已提交审核'); void qc.invalidateQueries({ queryKey: ['kb', 'documents'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '提交失败'),
  })

  const withdraw = useMutation({
    mutationFn: (docId: number) => withdrawKbDocument(docId, '部门主动下线'),
    onSuccess: () => { message.success('已下线'); void qc.invalidateQueries({ queryKey: ['kb', 'documents'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '下线失败'),
  })

  const expire = useMutation({
    mutationFn: (docId: number) => expireKbDocument(docId, '政策已失效'),
    onSuccess: () => { message.success('已标记失效'); void qc.invalidateQueries({ queryKey: ['kb', 'documents'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '操作失败'),
  })

  const reindex = useMutation({
    mutationFn: (docId: number) => reindexKbDocument(docId),
    onSuccess: (data) => { message.success(`重建完成，共 ${data.chunk_count} 切片`); void qc.invalidateQueries({ queryKey: ['kb', 'documents'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '重建失败'),
  })

  const directPublish = useMutation({
    mutationFn: (docId: number) => directPublishKbDocument(docId, '管理员直发'),
    onSuccess: () => { message.success('已直接发布'); void qc.invalidateQueries({ queryKey: ['kb', 'documents'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '发布失败'),
  })

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '标题', dataIndex: 'title', ellipsis: true,
      render: (t: string, r: KbDocument) => (
        <a onClick={() => setSelectedDocId(r.id)}>{t}</a>
      ) },
    { title: '文号', dataIndex: 'doc_number', width: 140, ellipsis: true },
    { title: '类型', dataIndex: 'kb_type', width: 100,
      render: (t: KbType) => <Tag>{kbTypeLabel(t)}</Tag> },
    { title: '公开范围', dataIndex: 'visibility', width: 100,
      render: (v: KbVisibility) => <Tag color={v === 'PUBLIC' ? 'green' : v === 'DEPARTMENT' ? 'blue' : 'red'}>{v}</Tag> },
    { title: '版本', dataIndex: 'version', width: 60 },
    { title: '状态', dataIndex: 'status', width: 100,
      render: (s: KbDocStatus) => {
        const meta = STATUS_LABELS[s]
        return <Tag color={meta.color}>{meta.label}</Tag>
      } },
    { title: '切片', dataIndex: 'chunk_count', width: 60 },
    { title: '部门', dataIndex: 'department_name', width: 120, ellipsis: true },
    { title: '发布时间', dataIndex: 'published_at', width: 110,
      render: (v?: string | null) => v ? v.slice(0, 10) : '—' },
    { title: '操作', key: 'actions', width: 280, fixed: 'right' as const,
      render: (_: unknown, r: KbDocument) => (
        <Space size="small" wrap>
          <Button size="small" onClick={() => setSelectedDocId(r.id)}>详情</Button>
          {(r.status === 'DRAFT' || r.status === 'REJECTED') && (
            <Button size="small" type="primary" loading={submitReview.isPending} onClick={() => submitReview.mutate(r.id)}>
              提交审核
            </Button>
          )}
          {r.status === 'PUBLISHED' && (
            <>
              <Button size="small" danger loading={withdraw.isPending} onClick={() => withdraw.mutate(r.id)}>下线</Button>
              <Popconfirm title="确认标记为已失效？" onConfirm={() => expire.mutate(r.id)}>
                <Button size="small">标记失效</Button>
              </Popconfirm>
            </>
          )}
          <Button size="small" icon={<ReloadOutlined />} loading={reindex.isPending} onClick={() => reindex.mutate(r.id)}>重建索引</Button>
          {user?.role === 'admin' && (r.status === 'DRAFT' || r.status === 'REJECTED') && (
            <Popconfirm title="直接发布此文档？" onConfirm={() => directPublish.mutate(r.id)}>
              <Button size="small" type="primary" ghost>直发</Button>
            </Popconfirm>
          )}
        </Space>
      ) },
  ]

  return (
    <>
      <Card className="surface" style={{ marginBottom: 16 }}>
        <Form layout="inline" onValuesChange={(_, all) => setFilters({ ...all, page: 1 })}>
          <Form.Item name="keyword" label="关键词">
            <Input allowClear placeholder="标题/文号/关键词" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="kb_type" label="类型">
            <Select allowClear placeholder="全部" style={{ width: 140 }} options={KB_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select allowClear placeholder="全部" style={{ width: 120 }}
              options={Object.entries(STATUS_LABELS).map(([k, v]) => ({ value: k, label: v.label }))} />
          </Form.Item>
          {user?.role === 'admin' && (
            <Form.Item name="department_id" label="部门">
              <Select allowClear placeholder="全部" style={{ width: 160 }}
                options={(departments.data || []).map(d => ({ value: d.id, label: d.name }))} />
            </Form.Item>
          )}
          <Form.Item name="domain" label="领域">
            <Input allowClear placeholder="不限" style={{ width: 140 }} />
          </Form.Item>
        </Form>
      </Card>

      <Card className="surface">
        {list.isError ? (
          <ErrorState error={list.error} retry={() => list.refetch()} />
        ) : (
          <Table
            rowKey="id"
            size="small"
            loading={list.isLoading}
            dataSource={list.data?.items}
            columns={columns}
            scroll={{ x: 1400 }}
            pagination={{
              current: list.data?.page || filters.page,
              pageSize: list.data?.page_size || filters.page_size,
              total: list.data?.total || 0,
              showSizeChanger: true,
              onChange: (page, page_size) => setFilters(f => ({ ...f, page, page_size })),
            }}
          />
        )}
      </Card>

      {selectedDocId && (
        <DocumentDetailDrawer docId={selectedDocId} onClose={() => setSelectedDocId(null)} />
      )}
    </>
  )
}

function DocumentDetailDrawer({ docId, onClose }: { docId: number; onClose: () => void }) {
  const [editOpen, setEditOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [chunksOpen, setChunksOpen] = useState(false)

  const detail = useQuery({
    queryKey: ['kb', 'document', docId],
    queryFn: () => getKbDocument(docId),
  })

  return (
    <Modal
      open
      title={detail.data?.title || '文档详情'}
      onCancel={onClose}
      footer={[
        <Button key="versions" onClick={() => setVersionsOpen(true)}>版本历史</Button>,
        <Button key="chunks" onClick={() => setChunksOpen(true)}>切片预览</Button>,
        <Button key="download" icon={<DownloadOutlined />} href={`/api/v1/kb/documents/${docId}/download`} target="_blank">
          下载源文件
        </Button>,
        detail.data && (detail.data.status === 'DRAFT' || detail.data.status === 'REJECTED') && (
          <Button key="edit" type="primary" icon={<EditOutlined />} onClick={() => setEditOpen(true)}>编辑元数据</Button>
        ),
        <Button key="close" onClick={onClose}>关闭</Button>,
      ].filter(Boolean) as React.ReactNode[]}
      width={900}
    >
      {detail.isLoading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : detail.isError ? (
        <ErrorState error={detail.error} retry={() => detail.refetch()} />
      ) : detail.data ? (
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label="标题" span={2}>{detail.data.title}</Descriptions.Item>
          <Descriptions.Item label="文号">{detail.data.doc_number || '—'}</Descriptions.Item>
          <Descriptions.Item label="类型"><Tag>{kbTypeLabel(detail.data.kb_type)}</Tag></Descriptions.Item>
          <Descriptions.Item label="公开范围"><Tag>{detail.data.visibility}</Tag></Descriptions.Item>
          <Descriptions.Item label="状态"><Tag>{STATUS_LABELS[detail.data.status].label}</Tag></Descriptions.Item>
          <Descriptions.Item label="版本">v{detail.data.version}</Descriptions.Item>
          <Descriptions.Item label="切片数">{detail.data.chunk_count}</Descriptions.Item>
          <Descriptions.Item label="部门">{detail.data.department_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="发布部门">{detail.data.published_department_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="领域">{detail.data.domain || '—'}</Descriptions.Item>
          <Descriptions.Item label="地区">{detail.data.region || '—'}</Descriptions.Item>
          <Descriptions.Item label="适用人群">{detail.data.audience || '—'}</Descriptions.Item>
          <Descriptions.Item label="生效时间">{detail.data.effective_at?.slice(0, 10) || '—'}</Descriptions.Item>
          <Descriptions.Item label="失效时间">{detail.data.expires_at?.slice(0, 10) || '—'}</Descriptions.Item>
          <Descriptions.Item label="发布时间">{detail.data.published_at?.slice(0, 10) || '—'}</Descriptions.Item>
          <Descriptions.Item label="文件类型">{detail.data.file_type}</Descriptions.Item>
          <Descriptions.Item label="OCR">{detail.data.ocr_status}</Descriptions.Item>
          <Descriptions.Item label="解析状态">{detail.data.parse_status}</Descriptions.Item>
          <Descriptions.Item label="索引状态">{detail.data.index_status}</Descriptions.Item>
          <Descriptions.Item label="嵌入模型">{detail.data.embedding_model || '—'}</Descriptions.Item>
          <Descriptions.Item label="关键词" span={2}>{detail.data.keywords || '—'}</Descriptions.Item>
          <Descriptions.Item label="标签" span={2}>{detail.data.tags.join('、') || '—'}</Descriptions.Item>
          <Descriptions.Item label="来源URL" span={2}>
            {detail.data.source_url ? <a href={detail.data.source_url} target="_blank" rel="noreferrer">{detail.data.source_url}</a> : '—'}
          </Descriptions.Item>
          {detail.data.review_comment && (
            <Descriptions.Item label="审核意见" span={2}>{detail.data.review_comment}</Descriptions.Item>
          )}
          {detail.data.rejected_reason && (
            <Descriptions.Item label="驳回原因" span={2}>{detail.data.rejected_reason}</Descriptions.Item>
          )}
        </Descriptions>
      ) : null}

      {editOpen && detail.data && (
        <EditMetadataModal doc={detail.data} onClose={() => setEditOpen(false)} />
      )}
      {versionsOpen && <VersionsModal docId={docId} onClose={() => setVersionsOpen(false)} />}
      {chunksOpen && <ChunksModal docId={docId} onClose={() => setChunksOpen(false)} />}
    </Modal>
  )
}

function EditMetadataModal({ doc, onClose }: { doc: ReturnType<typeof getKbDocument> extends Promise<infer T> ? T : never; onClose: () => void }) {
  const [form] = Form.useForm()
  const qc = useQueryClient()
  const update = useMutation({
    mutationFn: (values: Record<string, unknown>) => updateKbDocument(doc.id, values),
    onSuccess: () => {
      message.success('元数据已更新')
      void qc.invalidateQueries({ queryKey: ['kb', 'document', doc.id] })
      void qc.invalidateQueries({ queryKey: ['kb', 'documents'] })
      onClose()
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '更新失败'),
  })

  return (
    <Modal
      open
      title="编辑文档元数据"
      onCancel={onClose}
      onOk={() => form.validateFields().then(values => update.mutate(values))}
      confirmLoading={update.isPending}
      width={700}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          ...doc,
          tags: doc.tags.join(', '),
          effective_at: doc.effective_at?.slice(0, 10),
          expires_at: doc.expires_at?.slice(0, 10),
        }}
      >
        <Form.Item name="title" label="标题" rules={[{ required: true, min: 2, max: 500 }]}>
          <Input />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="doc_number" label="文号"><Input /></Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="kb_type" label="类型"><Select options={KB_TYPE_OPTIONS} /></Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="domain" label="领域"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="region" label="地区"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="audience" label="适用人群"><Input /></Form.Item>
          </Col>
        </Row>
        <Form.Item name="visibility" label="公开范围"><Select options={VISIBILITY_OPTIONS} /></Form.Item>
        <Form.Item name="keywords" label="关键词（逗号分隔）"><Input /></Form.Item>
        <Form.Item name="tags" label="标签（逗号分隔）"><Input /></Form.Item>
        <Form.Item name="source_url" label="来源URL"><Input /></Form.Item>
      </Form>
    </Modal>
  )
}

function VersionsModal({ docId, onClose }: { docId: number; onClose: () => void }) {
  const versions = useQuery({
    queryKey: ['kb', 'document', docId, 'versions'],
    queryFn: () => listKbDocumentVersions(docId),
  })
  return (
    <Modal open title="版本历史" onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>} width={800}>
      {versions.isLoading ? <Spin /> : versions.isError ? (
        <ErrorState error={versions.error} retry={() => versions.refetch()} />
      ) : (
        <Table
          rowKey="id"
          size="small"
          dataSource={versions.data}
          pagination={false}
          columns={[
            { title: '版本', dataIndex: 'version', width: 60, render: (v: number) => `v${v}` },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 100, render: (s: KbDocStatus) => <Tag>{STATUS_LABELS[s].label}</Tag> },
            { title: '切片', dataIndex: 'chunk_count', width: 60 },
            { title: '创建时间', dataIndex: 'created_at', width: 110, render: (v: string) => v.slice(0, 10) },
          ]}
        />
      )}
    </Modal>
  )
}

function ChunksModal({ docId, onClose }: { docId: number; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const chunks = useQuery({
    queryKey: ['kb', 'document', docId, 'chunks', page],
    queryFn: () => listKbChunks(docId, page, 20),
  })
  return (
    <Modal open title="切片预览" onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>} width={900}>
      {chunks.isLoading ? <Spin /> : chunks.isError ? (
        <ErrorState error={chunks.error} retry={() => chunks.refetch()} />
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            message={`共 ${chunks.data?.total || 0} 个切片`}
            description="切片用于 RAG 检索，每个切片包含原文片段、字符数与关键词。"
            style={{ marginBottom: 12 }}
          />
          <Table
            rowKey="id"
            size="small"
            dataSource={chunks.data?.items}
            pagination={{
              current: page, pageSize: 20, total: chunks.data?.total || 0,
              onChange: setPage,
            }}
            columns={[
              { title: '#', dataIndex: 'chunk_index', width: 50 },
              { title: '内容', dataIndex: 'content', ellipsis: true,
                render: (c: string) => <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{c.slice(0, 200)}…</Typography.Text> },
              { title: '字符数', dataIndex: 'char_count', width: 80 },
              { title: '关键词', dataIndex: 'keywords', width: 200, ellipsis: true,
                render: (k: string[]) => k.slice(0, 3).join('、') },
              { title: '嵌入', dataIndex: 'embedding_status', width: 110,
                render: (status: string | undefined, row: { has_embedding?: boolean }) => {
                  const label = ({
                    external: '外部向量',
                    hash_fallback: 'hash 回退',
                    missing: '缺失',
                    failed: '生成失败',
                  } as Record<string, string>)[status || ''] || (row.has_embedding ? '已有向量' : '缺失')
                  const color = status === 'external' ? 'success' : status === 'hash_fallback' ? 'warning' : 'error'
                  return <Tag color={color}>{label}</Tag>
                } },
            ]}
          />
        </>
      )}
    </Modal>
  )
}

// ========== Upload Tab ==========

function UploadTab() {
  const { user } = useAuth()
  const [form] = Form.useForm()
  const [file, setFile] = useState<File | null>(null)
  const qc = useQueryClient()
  const departments = useQuery({
    queryKey: ['departments'],
    queryFn: listDepartments,
    enabled: user?.role === 'admin',
  })

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('请先选择文件')
      const values = form.getFieldsValue()
      return uploadKbDocument(file, {
        ...values,
        tags: values.tags ? (typeof values.tags === 'string' ? values.tags : values.tags.join(',')) : undefined,
      })
    },
    onSuccess: () => {
      message.success('上传成功，文档已创建并自动解析索引')
      void qc.invalidateQueries({ queryKey: ['kb', 'documents'] })
      form.resetFields()
      setFile(null)
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '上传失败'),
  })

  return (
    <Card className="surface">
      <Alert
        type="info"
        showIcon
        icon={<UploadOutlined />}
        message="支持 PDF / Word / Markdown / Text 文件"
        description="系统将自动解析文件内容、分片、向量化并入库。扫描版 PDF 将标记为需要 OCR。"
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
        <Form.Item label="选择文件" required>
          <Dragger
            accept=".pdf,.docx,.md,.markdown,.txt"
            maxCount={1}
            beforeUpload={(f) => { setFile(f); return false }}
            onRemove={() => setFile(null)}
            fileList={file ? [{ uid: '-1', name: file.name, status: 'done' }] : []}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
            <p className="ant-upload-hint">单个文件最大 20MB，支持 PDF / Word / Markdown / Text</p>
          </Dragger>
        </Form.Item>

        <Form.Item name="title" label="标题">
          <Input placeholder="留空则使用文件名" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="doc_number" label="文号"><Input /></Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="kb_type" label="知识库类型" initialValue="policy">
              <Select options={KB_TYPE_OPTIONS} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="domain" label="领域"><Input placeholder="如：社保" /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="region" label="适用地区"><Input placeholder="如：本市" /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="audience" label="适用人群"><Input placeholder="如：居民" /></Form.Item>
          </Col>
        </Row>
        <Form.Item name="visibility" label="公开范围" initialValue="PUBLIC">
          <Select options={VISIBILITY_OPTIONS} />
        </Form.Item>
        {user?.role === 'admin' && (
          <Form.Item name="department_id" label="所属部门">
            <Select allowClear placeholder="留空使用上传者所在部门"
              options={(departments.data || []).map(d => ({ value: d.id, label: d.name }))} />
          </Form.Item>
        )}
        <Form.Item name="keywords" label="关键词（逗号分隔）"><Input /></Form.Item>
        <Form.Item name="tags" label="标签（逗号分隔）"><Input /></Form.Item>
        <Form.Item name="source_url" label="来源URL"><Input /></Form.Item>
        {user?.role === 'admin' && (
          <Form.Item name="auto_publish" label="自动发布" valuePropName="checked">
            <Select options={[{ value: false, label: '否（保存为草稿）' }, { value: true, label: '是（管理员直发）' }]} />
          </Form.Item>
        )}
        <Form.Item>
          <Button type="primary" icon={<UploadOutlined />} loading={upload.isPending} onClick={() => upload.mutate()}>
            上传并解析
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}

// ========== Raw Content Tab ==========

function RawContentTab() {
  const [form] = Form.useForm()
  const qc = useQueryClient()
  const create = useMutation({
    mutationFn: (values: Record<string, unknown>) => createKbDocument(values as any),
    onSuccess: () => {
      message.success('文档已创建并自动解析索引')
      void qc.invalidateQueries({ queryKey: ['kb', 'documents'] })
      form.resetFields()
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '创建失败'),
  })
  return (
    <Card className="surface">
      <Alert
        type="info"
        showIcon
        message="直接录入政策文本"
        description="适用于无源文件的小段政策内容、常见问题与内部制度。文本将自动分片并向量化。"
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical" style={{ maxWidth: 720 }}
        initialValues={{ kb_type: 'policy', visibility: 'PUBLIC' }}>
        <Form.Item name="title" label="标题" rules={[{ required: true, min: 2, max: 500 }]}>
          <Input placeholder="例如：城市居民最低生活保障申请指南" />
        </Form.Item>
        <Form.Item name="raw_content" label="正文内容" rules={[{ required: true, min: 10 }]}>
          <TextArea rows={8} placeholder="粘贴政策原文、办事指南或常见问题..." />
        </Form.Item>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="doc_number" label="文号"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="kb_type" label="类型"><Select options={KB_TYPE_OPTIONS} /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="visibility" label="公开范围"><Select options={VISIBILITY_OPTIONS} /></Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="domain" label="领域"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="region" label="地区"><Input /></Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="audience" label="适用人群"><Input /></Form.Item>
          </Col>
        </Row>
        <Form.Item name="keywords" label="关键词"><Input /></Form.Item>
        <Form.Item>
          <Button type="primary" loading={create.isPending} onClick={() => form.validateFields().then(values => create.mutate(values))}>
            创建文档
          </Button>
        </Form.Item>
      </Form>
    </Card>
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
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
            { title: '反馈类型', dataIndex: 'feedback_type', width: 100,
              render: (t: KbFeedbackType) => {
                const map = { helpful: { c: 'green', l: '有帮助' }, inaccurate: { c: 'red', l: '不准确' }, outdated: { c: 'orange', l: '过时' }, no_answer: { c: 'default', l: '未解答' } }
                return <Tag color={map[t].c}>{map[t].l}</Tag>
              } },
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
