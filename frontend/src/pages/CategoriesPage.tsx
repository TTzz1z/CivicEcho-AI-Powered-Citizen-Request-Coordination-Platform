import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd'
import { ApartmentOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createCategory, listCategories, listDepartments, updateCategory } from '../api/admin'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import type { Category } from '../types'

type Values={code:string;name:string;parent_id?:number;default_department_id?:number;accept_sla_minutes:number;resolve_sla_minutes:number}

export function CategoriesPage(){
  const qc=useQueryClient();const categories=useQuery({queryKey:['categories'],queryFn:listCategories});const departments=useQuery({queryKey:['departments'],queryFn:listDepartments})
  const [editing,setEditing]=useState<Category|null|undefined>();const [form]=Form.useForm<Values>()
  const save=useMutation({mutationFn:(v:Values)=>editing?updateCategory(editing.id,v):createCategory(v),onSuccess:()=>{message.success(editing?'分类已更新':'分类已创建');setEditing(undefined);void qc.invalidateQueries({queryKey:['categories']})},onError:e=>message.error(e instanceof ApiError?e.message:'保存失败')})
  if(categories.isError)return <ErrorState error={categories.error} retry={()=>categories.refetch()}/>
  const open=(item:null|Category)=>{setEditing(item);form.setFieldsValue(item?{...item,parent_id:item.parent_id||undefined,default_department_id:item.default_department_id||undefined}:{accept_sla_minutes:120,resolve_sla_minutes:4320})}
  return <><PageHeader eyebrow="SERVICE TAXONOMY" title="诉求分类" description="维护最多三级的统一分类编码、默认责任部门和默认办理时限。停用不会影响历史工单。" extra={<Button type="primary" icon={<PlusOutlined/>} onClick={()=>{form.resetFields();open(null)}}>新增分类</Button>}/>
    <Card className="surface" styles={{body:{padding:0}}}><Table rowKey="id" loading={categories.isLoading} dataSource={categories.data} pagination={false} scroll={{x:1050}} columns={[
      {title:'层级',dataIndex:'level',width:72,render:v=><Tag color="blue">L{v}</Tag>},{title:'分类编码',dataIndex:'code',width:190},{title:'分类名称',render:(_,r)=><span style={{paddingLeft:(r.level-1)*20}}><ApartmentOutlined/> {r.name}</span>},
      {title:'默认责任部门',dataIndex:'default_department_name',render:v=>v||'—'},{title:'受理时限',dataIndex:'accept_sla_minutes',render:v=>`${v} 分钟`},{title:'办理时限',dataIndex:'resolve_sla_minutes',render:v=>`${v} 分钟`},
      {title:'状态',dataIndex:'is_active',render:v=><Tag color={v?'success':'default'}>{v?'启用':'停用'}</Tag>},{title:'操作',render:(_,r)=><Space><Button type="link" onClick={()=>open(r)}>编辑</Button><Popconfirm title={r.is_active?'确认停用？':'确认启用？'} description="存在启用子分类时不能停用上级分类。" onConfirm={()=>updateCategory(r.id,{is_active:!r.is_active}).then(()=>qc.invalidateQueries({queryKey:['categories']}))}><Button type="link" danger={r.is_active}>{r.is_active?'停用':'启用'}</Button></Popconfirm></Space>},
    ]}/></Card>
    <Modal title={editing?'编辑分类':'新增分类'} open={editing!==undefined} onCancel={()=>setEditing(undefined)} onOk={()=>form.submit()} confirmLoading={save.isPending} destroyOnHidden><Alert type="info" showIcon message="工单只能选择没有启用子项的末级分类；编码创建后不可修改。" style={{marginBottom:16}}/><Form form={form} layout="vertical" onFinish={v=>save.mutate(v)}><Form.Item name="code" label="分类编码" rules={[{required:true},{pattern:/^[A-Z0-9_-]+$/,message:'仅支持大写字母、数字、下划线和连字符'}]}><Input disabled={!!editing} placeholder="例如 CSGL-GGSS-LD"/></Form.Item><Form.Item name="name" label="分类名称" rules={[{required:true},{min:2}]}><Input/></Form.Item><Form.Item name="parent_id" label="上级分类"><Select allowClear options={categories.data?.filter(c=>c.is_active&&c.level<3&&c.id!==editing?.id).map(c=>({value:c.id,label:`L${c.level} ${c.name} (${c.code})`}))}/></Form.Item><Form.Item name="default_department_id" label="默认责任部门"><Select allowClear options={departments.data?.filter(d=>d.is_active).map(d=>({value:d.id,label:d.name}))}/></Form.Item><Space size="large"><Form.Item name="accept_sla_minutes" label="默认受理时限（分钟）" rules={[{required:true}]}><InputNumber min={1} max={525600}/></Form.Item><Form.Item name="resolve_sla_minutes" label="默认办理时限（分钟）" rules={[{required:true}]}><InputNumber min={1} max={525600}/></Form.Item></Space></Form></Modal>
  </>
}
