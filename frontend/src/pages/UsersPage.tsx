import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createUser, listDepartments, listUsersPage, updateUser } from '../api/admin'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import type { Role, User, UserFilters } from '../types'

const roles: { value: Role; label: string }[] = [
  { value: 'citizen', label: '市民' }, { value: 'agent', label: '坐席' },
  { value: 'department_staff', label: '部门人员' }, { value: 'admin', label: '管理员' },
]

export function UsersPage() {
  const qc = useQueryClient()
  const [filters,setFilters]=useState<UserFilters>({page:1,page_size:10,sort:'created_at',order:'desc'})
  const users = useQuery({ queryKey: ['users',filters], queryFn: () => listUsersPage(filters) })
  const deps = useQuery({ queryKey: ['departments'], queryFn: listDepartments })
  const [open, setOpen] = useState(false); const [editing, setEditing] = useState<User | null>(null)
  const [form] = Form.useForm(); const [filterForm]=Form.useForm()
  const save = useMutation({
    mutationFn: (v: { username: string; password?: string; display_name: string; role: Role; department_id?: number; is_active: boolean }) => editing ? updateUser(editing.id, v) : createUser({ ...v, password: v.password!, is_active: v.is_active ?? true }),
    onSuccess: () => { message.success(editing ? '用户信息已更新' : '用户已创建'); setOpen(false); setEditing(null); form.resetFields(); void qc.invalidateQueries({ queryKey: ['users'] }) },
    onError: e => message.error(e instanceof ApiError ? e.message : '保存失败'),
  })
  if (users.isError) return <ErrorState error={users.error} retry={() => users.refetch()} />
  const show = (u?: User) => { setEditing(u || null); setOpen(true); form.setFieldsValue(u || { role: 'citizen', is_active: true }) }
  return <>
    <PageHeader eyebrow="IDENTITY MANAGEMENT" title="用户管理" description="列表由服务端分页、筛选和排序；密码只在创建或重置时提交。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => show()}>创建用户</Button>} />
    <Card className="surface" style={{marginBottom:16}}><Form form={filterForm} layout="inline" onFinish={v=>setFilters(f=>({...f,...v,keyword:v.keyword?.trim()||undefined,page:1}))}>
      <Form.Item name="keyword"><Input allowClear prefix={<SearchOutlined/>} placeholder="用户名或显示名称"/></Form.Item>
      <Form.Item name="role"><Select allowClear placeholder="全部角色" style={{width:130}} options={roles}/></Form.Item>
      <Form.Item name="is_active"><Select allowClear placeholder="全部状态" style={{width:120}} options={[{value:true,label:'启用'},{value:false,label:'停用'}]}/></Form.Item>
      <Form.Item name="department_id"><Select allowClear placeholder="全部部门" style={{width:150}} options={deps.data?.map(d=>({value:d.id,label:d.name}))}/></Form.Item>
      <Form.Item><Space><Button type="primary" htmlType="submit">查询</Button><Button onClick={()=>{filterForm.resetFields();setFilters({page:1,page_size:10,sort:'created_at',order:'desc'})}}>重置</Button></Space></Form.Item>
    </Form></Card>
    <Card className="surface" styles={{ body: { padding: 0 } }}><Table<User> rowKey="id" loading={users.isLoading} dataSource={users.data?.items} locale={{emptyText:'没有符合条件的用户'}} columns={[
      { title: '用户名', dataIndex: 'username', sorter:true, sortOrder:filters.sort==='username'?(filters.order==='asc'?'ascend':'descend'):null },
      { title: '显示名称', dataIndex: 'display_name', sorter:true, sortOrder:filters.sort==='display_name'?(filters.order==='asc'?'ascend':'descend'):null },
      { title: '角色', dataIndex: 'role', sorter:true, sortOrder:filters.sort==='role'?(filters.order==='asc'?'ascend':'descend'):null, render: v => <Tag>{roles.find(r => r.value === v)?.label}</Tag> },
      { title: '所属部门', dataIndex: 'department_id', render: v => deps.data?.find(d => d.id === v)?.name || '—' },
      { title: '状态', dataIndex: 'is_active', render: v => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '操作', render: (_, r) => <Space><Button type="link" onClick={() => show(r)}>编辑</Button><Popconfirm title={r.is_active ? '确认停用此用户？' : '确认启用此用户？'} description="停用后该账号将无法登录。" onConfirm={() => updateUser(r.id, { is_active: !r.is_active }).then(() => qc.invalidateQueries({ queryKey: ['users'] }))}><Button type="link" danger={r.is_active}>{r.is_active ? '停用' : '启用'}</Button></Popconfirm></Space> },
    ]} pagination={{current:filters.page,pageSize:filters.page_size,total:users.data?.total,showSizeChanger:true,showTotal:t=>`共 ${t} 个用户`}} onChange={(pagination,_,sorter)=>{const item=Array.isArray(sorter)?sorter[0]:sorter;setFilters(f=>({...f,page:pagination.current||1,page_size:pagination.pageSize||10,sort:(item.field as UserFilters['sort'])||f.sort,order:item.order==='ascend'?'asc':item.order==='descend'?'desc':f.order}))}} /></Card>
    <Modal title={editing ? '编辑用户' : '创建用户'} open={open} onCancel={() => { setOpen(false); setEditing(null) }} onOk={() => form.submit()} confirmLoading={save.isPending} destroyOnHidden><Form form={form} layout="vertical" onFinish={v => save.mutate(v)}>
      <Form.Item name="username" label="用户名" rules={[{ required: !editing, message: '请输入用户名' }, { min: 3, message: '至少 3 个字符' }]}><Input disabled={!!editing} /></Form.Item>
      <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}><Input /></Form.Item>
      <Form.Item name="role" label="角色" rules={[{ required: true }]}><Select options={roles} /></Form.Item>
      <Form.Item noStyle shouldUpdate={(p, c) => p.role !== c.role}>{({ getFieldValue }) => getFieldValue('role') === 'department_staff' && <Form.Item name="department_id" label="所属部门" rules={[{ required: true, message: '请选择部门' }]}><Select options={deps.data?.filter(d => d.is_active).map(d => ({ value: d.id, label: d.name }))} /></Form.Item>}</Form.Item>
      <Form.Item name="password" label={editing ? '重置密码（留空则不修改）' : '初始密码'} rules={[{ required: !editing, message: '请输入初始密码' }, { min: 12, message: '密码至少 12 个字符' }]}><Input.Password autoComplete="new-password" /></Form.Item>
      <Form.Item name="is_active" label="启用账号" valuePropName="checked"><Switch /></Form.Item>
    </Form></Modal>
  </>
}
