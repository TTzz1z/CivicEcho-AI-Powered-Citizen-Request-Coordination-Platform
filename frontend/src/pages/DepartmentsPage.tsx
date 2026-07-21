import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tag, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createDepartment, listDepartments, updateDepartment } from '../api/admin'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import type { Department } from '../types'

export function DepartmentsPage() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['departments'], queryFn: listDepartments })
  const [editing, setEditing] = useState<Department | null | undefined>()
  const [form] = Form.useForm()
  const save = useMutation({
    mutationFn: (v: { code: string; name: string; description?: string }) => editing ? updateDepartment(editing.id, v) : createDepartment(v),
    onSuccess: () => { message.success(editing ? '部门已更新' : '部门已创建'); setEditing(undefined); void qc.invalidateQueries({ queryKey: ['departments'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '保存失败'),
  })
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return <>
    <PageHeader eyebrow="ORGANIZATION" title="部门管理" description="停用部门后将不能接收新工单，历史工单与办理记录仍会保留。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields() }}>创建部门</Button>} />
    <Card className="surface" styles={{ body: { padding: 0 } }}><Table rowKey="id" loading={query.isLoading} dataSource={query.data} columns={[
      { title: '部门编码', dataIndex: 'code' }, { title: '部门名称', dataIndex: 'name' }, { title: '说明', dataIndex: 'description', render: v => v || '—' },
      { title: '状态', dataIndex: 'is_active', render: v => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '操作', render: (_, r) => <Space><Button type="link" onClick={() => { setEditing(r); form.setFieldsValue(r) }}>编辑</Button><Popconfirm title={r.is_active ? '确认停用该部门？' : '确认重新启用？'} description="停用后无法派发新工单到该部门，已有关联数据不受影响。" onConfirm={() => updateDepartment(r.id, { is_active: !r.is_active }).then(() => qc.invalidateQueries({ queryKey: ['departments'] }))}><Button type="link" danger={r.is_active}>{r.is_active ? '停用' : '启用'}</Button></Popconfirm></Space> },
    ]} /></Card>
    <Modal title={editing ? '编辑部门' : '创建部门'} open={editing !== undefined} onCancel={() => setEditing(undefined)} onOk={() => form.submit()} confirmLoading={save.isPending} destroyOnHidden>
      <Alert type="info" showIcon message="部门编码创建后不可修改" style={{ marginBottom: 18 }} />
      <Form form={form} layout="vertical" onFinish={v => save.mutate(v)}><Form.Item name="code" label="部门编码" rules={[{ required: true }, { pattern: /^[a-z0-9-]+$/, message: '仅支持小写字母、数字和连字符' }]}><Input disabled={!!editing} /></Form.Item><Form.Item name="name" label="部门名称" rules={[{ required: true }, { min: 2 }]}><Input /></Form.Item><Form.Item name="description" label="部门职责"><Input.TextArea rows={3} /></Form.Item></Form>
    </Modal>
  </>
}
