import { Alert, Button, Card, Descriptions, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { createDepartment, listDepartments, updateDepartment } from '../api/admin'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { WorkspaceTableRegion } from '../components/WorkspaceTableRegion'
import type { Department } from '../types'

export function DepartmentsPage() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['departments'], queryFn: listDepartments })
  const [editing, setEditing] = useState<Department | null | undefined>()
  const [detail, setDetail] = useState<Department | null>(null)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [form] = Form.useForm()
  const save = useMutation({
    mutationFn: (v: { code: string; name: string; description?: string }) =>
      editing ? updateDepartment(editing.id, v) : createDepartment(v),
    onSuccess: () => {
      message.success(editing ? '部门已更新' : '部门已创建')
      setEditing(undefined)
      void qc.invalidateQueries({ queryKey: ['departments'] })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '保存失败'),
  })
  const toggleActive = useMutation({
    mutationFn: (d: Department) => updateDepartment(d.id, { is_active: !d.is_active }),
    onSuccess: (_, d) => {
      message.success(d.is_active ? '部门已停用' : '部门已重新启用')
      void qc.invalidateQueries({ queryKey: ['departments'] })
    },
    onError: e => message.error(e instanceof ApiError ? e.message : '状态切换失败'),
  })
  const filtered = useMemo(() => {
    const term = keyword.trim().toLowerCase()
    return (query.data || []).filter(item => {
      if (statusFilter === 'active' && !item.is_active) return false
      if (statusFilter === 'inactive' && item.is_active) return false
      if (!term) return true
      return (
        item.code.toLowerCase().includes(term)
        || item.name.toLowerCase().includes(term)
        || (item.description || '').toLowerCase().includes(term)
      )
    })
  }, [query.data, keyword, statusFilter])
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return <>
    <PageHeader eyebrow="ORGANIZATION" title="部门管理" description="停用部门后将不能接收新工单，历史工单与办理记录仍会保留。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields() }}>创建部门</Button>} />
    <Card className="surface" style={{ marginBottom: 16 }}>
      <Space wrap>
        <Input allowClear prefix={<SearchOutlined />} placeholder="按部门编码、名称或职责搜索" style={{ width: 260 }} value={keyword} onChange={e => setKeyword(e.target.value)} />
        <Select id="department-status-filter" aria-label="按部门状态筛选" value={statusFilter} style={{ width: 130 }} onChange={setStatusFilter} options={[
          { value: 'all', label: '全部状态' },
          { value: 'active', label: '仅启用' },
          { value: 'inactive', label: '仅停用' },
        ]} />
        {(keyword || statusFilter !== 'all') && <Button onClick={() => { setKeyword(''); setStatusFilter('all') }}>重置</Button>}
      </Space>
    </Card>
    <Card className="surface" styles={{ body: { padding: 0 } }}>
      <WorkspaceTableRegion label="部门列表">
        <Table
          rowKey="id"
          size="small"
          scroll={{ x: 520 }}
          loading={query.isLoading}
          dataSource={filtered}
          locale={{ emptyText: '没有符合条件的部门' }}
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 个部门` }}
          columns={[
            { title: '部门编码', dataIndex: 'code', responsive: ['md'], width: 150, ellipsis: true },
            { title: '部门名称', dataIndex: 'name', ellipsis: true, render: (v, r: Department) => <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setDetail(r)}>{v}</Button> },
            { title: '说明', dataIndex: 'description', responsive: ['md'], ellipsis: true, render: v => v || '—' },
            { title: '状态', dataIndex: 'is_active', width: 88, render: v => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag> },
            {
              title: '操作',
              width: 140,
              render: (_, r: Department) => (
                <Space size={4}>
                  <Button type="link" size="small" onClick={() => { setEditing(r); form.setFieldsValue(r) }}>编辑</Button>
                  <Popconfirm
                    title={r.is_active ? '确认停用该部门？' : '确认重新启用？'}
                    description="停用后无法派发新工单到该部门，已有关联数据不受影响。"
                    onConfirm={() => toggleActive.mutate(r)}
                  >
                    <Button type="link" size="small" danger={r.is_active}>{r.is_active ? '停用' : '启用'}</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </WorkspaceTableRegion>
    </Card>
    <Drawer title={detail ? `部门详情 · ${detail.name}` : '部门详情'} open={!!detail} onClose={() => setDetail(null)} size="min(420px, 100vw)">
      {detail && <Descriptions size="small" column={1} bordered items={[
        { key: 'code', label: '部门编码', children: detail.code },
        { key: 'name', label: '部门名称', children: detail.name },
        { key: 'active', label: '状态', children: <Tag color={detail.is_active ? 'success' : 'default'}>{detail.is_active ? '启用' : '停用'}</Tag> },
        { key: 'desc', label: '部门职责', children: detail.description || '暂无说明' },
      ]} />}
    </Drawer>
    <Modal title={editing ? '编辑部门' : '创建部门'} open={editing !== undefined} onCancel={() => setEditing(undefined)} onOk={() => form.submit()} confirmLoading={save.isPending} width={520} destroyOnHidden>
      <Alert type="info" showIcon message="部门编码创建后不可修改" style={{ marginBottom: 18 }} />
      <Form form={form} layout="vertical" onFinish={v => save.mutate(v)}>
        <Form.Item name="code" label="部门编码" rules={[{ required: true }, { pattern: /^[a-z0-9-]+$/, message: '仅支持小写字母、数字和连字符' }]}><Input disabled={!!editing} /></Form.Item>
        <Form.Item name="name" label="部门名称" rules={[{ required: true }, { min: 2 }]}><Input /></Form.Item>
        <Form.Item name="description" label="部门职责"><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>
  </>
}
