import { Alert, App, Button, Card, DatePicker, Drawer, Form, Input, List, Modal, Select, Space, Tag, Typography } from 'antd'
import { DownloadOutlined, FilterOutlined, ReloadOutlined, SearchOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listCategories, listDepartmentStaff, listDepartments } from '../api/admin'
import { formatApiErrorMessage } from '../api/client'
import { batchAssignTickets, exportTicketsCsv, listTickets, ticketKeys } from '../api/tickets'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { TicketStatusTag, statusOptions } from '../components/TicketStatusTag'
import { TicketTable } from '../components/TicketTable'
import { DepartmentQueueTabs } from '../components/DepartmentQueueTabs'
import { WorkspaceTableRegion } from '../components/WorkspaceTableRegion'
import { useAuth } from '../auth/AuthContext'
import type { Priority, Ticket, TicketBatchAssignResult, TicketFilters, TicketStatus } from '../types'
const {RangePicker}=DatePicker
const priorityOptions=[{value:'normal',label:'普通'},{value:'expedited',label:'加急'},{value:'urgent',label:'紧急'},{value:'major',label:'重大事件'}]
const slaOptions=[{value:'due_soon',label:'即将超时'},{value:'overdue',label:'已超时'},{value:'paused',label:'计时暂停'},{value:'on_track',label:'时限正常'}]

export function TicketsPage(){
  const {user}=useAuth();const {message}=App.useApp();const qc=useQueryClient();const [params,setParams]=useSearchParams();const categories=useQuery({queryKey:['categories'],queryFn:listCategories})
  const [advancedOpen,setAdvancedOpen]=useState(false)
  const [exporting,setExporting]=useState(false)
  const [selectedRows,setSelectedRows]=useState<Ticket[]>([])
  const [batchModalOpen,setBatchModalOpen]=useState(false)
  const [batchResult,setBatchResult]=useState<TicketBatchAssignResult|null>(null)
  const [batchForm]=Form.useForm<{department_id:number;assigned_user_id?:number;note?:string}>()
  const selectedDepartmentId=Form.useWatch('department_id',batchForm)
  const canBatchAssign=user?.role==='agent'||user?.role==='admin'
  const filters=useMemo<TicketFilters>(()=>({page:Number(params.get('page')||1),page_size:Number(params.get('page_size')||20),status:(params.get('status')||undefined) as TicketStatus|undefined,request_type:params.get('request_type')||undefined,category_id:params.get('category_id')?Number(params.get('category_id')):undefined,priority:(params.get('priority')||undefined) as Priority|undefined,sla_state:(params.get('sla_state')||undefined) as TicketFilters['sla_state'],work_queue:(params.get('work_queue')||undefined) as TicketFilters['work_queue'],keyword:params.get('keyword')||undefined,created_from:params.get('created_from')||undefined,created_to:params.get('created_to')||undefined,mine:params.get('mine')==='true'||user?.role==='citizen',my_department:params.get('my_department')==='true',sort:(params.get('sort')||'created_at') as TicketFilters['sort'],order:(params.get('order')||'desc') as TicketFilters['order']}),[params,user])
  const query=useQuery({queryKey:ticketKeys.list(filters),queryFn:()=>listTickets(filters)})
  const departments=useQuery({queryKey:['departments'],queryFn:listDepartments,enabled:canBatchAssign&&batchModalOpen})
  const departmentStaff=useQuery({queryKey:['department-staff',selectedDepartmentId],queryFn:()=>listDepartmentStaff(selectedDepartmentId!),enabled:canBatchAssign&&batchModalOpen&&typeof selectedDepartmentId==='number'&&selectedDepartmentId>0})
  const batchMutation=useMutation({
    mutationFn:(values:{department_id:number;assigned_user_id?:number;note?:string})=>batchAssignTickets({
      ticket_ids:selectedRows.map(row=>row.ticket_id),
      department_id:values.department_id,
      assigned_user_id:values.assigned_user_id||undefined,
      note:values.note?.trim()||undefined,
      versions:Object.fromEntries(selectedRows.map(row=>[row.ticket_id,row.version])),
    }),
    onSuccess:result=>{
      void qc.invalidateQueries({queryKey:ticketKeys.all})
      setBatchModalOpen(false)
      setSelectedRows([])
      batchForm.resetFields()
      setBatchResult(result)
    },
    onError:err=>message.error(formatApiErrorMessage(err,'批量派发失败，请稍后重试')),
  })
  const update=(next:TicketFilters)=>{setSelectedRows([]);const clean=new URLSearchParams();Object.entries(next).forEach(([k,v])=>{if(v!==undefined&&v!==''&&v!==false)clean.set(k,String(v))});setParams(clean)}
  const handleExport=async()=>{
    if(exporting)return
    setExporting(true)
    try{
      await exportTicketsCsv(filters)
      message.success('工单 CSV 已开始下载')
    }catch(err){
      message.error(formatApiErrorMessage(err,'工单导出失败，请稍后重试'))
    }finally{
      setExporting(false)
    }
  }
  const base=user?.role==='admin'?'/admin/tickets':user?.role==='agent'?'/agent/tickets':user?.role==='department_staff'?'/department/tickets':'/citizen/tickets';const title=user?.role==='citizen'?'我的工单':user?.role==='department_staff'?'部门工单':user?.role==='agent'?'坐席工单台':'全部工单'
  const categoryOptions=categories.data?.filter(c=>c.is_active).map(c=>({value:c.id,label:`${'　'.repeat(c.level-1)}${c.name} · ${c.code}`}))
  const isDepartment = user?.role === 'department_staff'
  const activeFilterCount=[filters.request_type,filters.category_id,filters.priority,filters.sla_state,filters.created_from,filters.my_department, isDepartment && filters.mine].filter(v=>v!==undefined&&v!==''&&v!==false).length
  const description = isDepartment ? '查看部门可见工单，按办理状态与 SLA 安排任务。'
    : user?.role === 'citizen' ? '查看已提交的诉求、办理进度和公开答复。' : '按编号、状态或高级条件查询工单。'
  const selectedRowKeys=useMemo(()=>selectedRows.map(row=>row.ticket_id),[selectedRows])
  return <><PageHeader title={title} description={description} extra={query.isFetching&&<TicketStatusTag status="processing" label="正在同步"/>}/>
  <Card className="surface ticket-filters" styles={{body:{padding:'12px 16px'}}}>
    {isDepartment && <DepartmentQueueTabs filters={filters} onChange={update} />}
    {(user?.role === 'agent' || user?.role === 'admin') && <Space wrap className="ticket-quick-views">
      <Button type={!filters.work_queue && !filters.sla_state ? 'primary' : 'default'}
        aria-pressed={!filters.work_queue && !filters.sla_state}
        onClick={() => update({ ...filters, page: 1, status: undefined, work_queue: undefined, sla_state: undefined })}>全部队列</Button>
      <Button type={filters.work_queue === 'awaiting_review' ? 'primary' : 'default'}
        aria-pressed={filters.work_queue === 'awaiting_review'}
        onClick={() => update({ ...filters, page: 1, status: undefined, work_queue: 'awaiting_review', sla_state: undefined })}>待复核</Button>
      <Button type={filters.work_queue === 'returned' ? 'primary' : 'default'}
        aria-pressed={filters.work_queue === 'returned'}
        onClick={() => update({ ...filters, page: 1, status: undefined, work_queue: 'returned', sla_state: undefined })}>被退回</Button>
      <Button type={filters.sla_state === 'due_soon' ? 'primary' : 'default'}
        aria-pressed={filters.sla_state === 'due_soon'}
        onClick={() => update({ ...filters, page: 1, status: undefined, work_queue: undefined, sla_state: 'due_soon' })}>即将超时</Button>
    </Space>}
    <Form key={`${filters.status ?? ''}|${filters.keyword ?? ''}`} className="ticket-filter-form" layout="inline"
      initialValues={{status:filters.status,keyword:filters.keyword}} onFinish={v=>update({...filters,page:1,status:v.status,keyword:v.keyword?.trim()})}>
      <Form.Item name="keyword" className="ticket-keyword"><Input aria-label="搜索工单" allowClear prefix={<SearchOutlined aria-hidden/>} placeholder="编号、描述或地点" maxLength={100}/></Form.Item>
      <Form.Item name="status" className="ticket-status-filter"><Select aria-label="工单状态" allowClear placeholder="全部状态" options={statusOptions}/></Form.Item>
      <Form.Item><Space wrap>
        <Button type="primary" htmlType="submit">查询</Button>
        <Button icon={<FilterOutlined/>} onClick={()=>setAdvancedOpen(true)}>
          高级筛选{activeFilterCount>0?` (${activeFilterCount})`:''}
        </Button>
        <Button icon={<ReloadOutlined/>} onClick={()=>{setSelectedRows([]);setParams({})}}>重置</Button>
        <Button icon={<DownloadOutlined/>} loading={exporting} disabled={exporting} onClick={()=>void handleExport()}>导出 CSV</Button>
      </Space></Form.Item>
    </Form>
    {canBatchAssign && selectedRows.length > 0 && (
      <div className="ticket-batch-bar" role="region" aria-label="批量派发操作栏">
        <Space wrap>
          <Typography.Text strong>已选 {selectedRows.length} 条</Typography.Text>
          {selectedRows.length > 50 && <Typography.Text type="danger">单次最多批量派发 50 条工单</Typography.Text>}
        </Space>
        <Space wrap>
          <Button onClick={()=>setSelectedRows([])}>清空选择</Button>
          <Button type="primary" icon={<SendOutlined/>} disabled={selectedRows.length === 0 || selectedRows.length > 50}
            onClick={()=>{batchForm.resetFields();setBatchModalOpen(true)}}>批量派发</Button>
        </Space>
      </div>
    )}
  </Card>
  <Drawer title="高级筛选" placement="right" size="min(380px, 100vw)" destroyOnHidden open={advancedOpen} onClose={()=>setAdvancedOpen(false)}>
    <Form layout="vertical" initialValues={{request_type:filters.request_type,category_id:filters.category_id,priority:filters.priority,sla_state:filters.sla_state,date:filters.created_from?[dayjs(filters.created_from),dayjs(filters.created_to)]:undefined,scope:filters.mine?'mine':filters.my_department?'primary':'all'}} onFinish={v=>{update({...filters,page:1,request_type:v.request_type,category_id:v.category_id,priority:v.priority,sla_state:v.sla_state,mine:user?.role==='citizen'||(isDepartment&&v.scope==='mine'),my_department:isDepartment&&v.scope==='primary',created_from:v.date?.[0]?.startOf('day').toISOString(),created_to:v.date?.[1]?.add(1,'day').startOf('day').toISOString()});setAdvancedOpen(false)}}>
      <Form.Item name="category_id" label="诉求分类"><Select showSearch optionFilterProp="label" allowClear placeholder="全部分类" options={categoryOptions}/></Form.Item>
      <Form.Item name="priority" label="优先级"><Select allowClear placeholder="全部优先级" options={priorityOptions}/></Form.Item>
      <Form.Item name="sla_state" label="SLA 状态"><Select allowClear placeholder="全部 SLA 状态" options={slaOptions}/></Form.Item>
      <Form.Item name="request_type" label="诉求类型"><Select allowClear placeholder="全部类型" options={['投诉','建议','咨询','求助'].map(v=>({value:v,label:v}))}/></Form.Item>
      {isDepartment&&<Form.Item name="scope" label="工单范围"><Select options={[{value:'all',label:'全部可见工单（含协办）'},{value:'primary',label:'本部门为责任部门'},{value:'mine',label:'主单分派给我'}]}/></Form.Item>}
      <Form.Item name="date" label="创建时间范围"><RangePicker style={{width:'100%'}}/></Form.Item>
      <Form.Item><Space style={{width:'100%',justifyContent:'flex-end'}}>
        <Button onClick={()=>setAdvancedOpen(false)}>取消</Button>
        <Button type="primary" htmlType="submit">应用筛选</Button>
      </Space></Form.Item>
    </Form>
  </Drawer>
  <Card className="surface" styles={{body:{padding:0}}}>{query.isError?<ErrorState error={query.error} retry={()=>query.refetch()}/>:<WorkspaceTableRegion label={`${title}列表`}><TicketTable items={query.data?.items} total={query.data?.total} loading={query.isLoading} filters={filters} onChange={update} basePath={base} selectable={canBatchAssign} selectedRowKeys={selectedRowKeys} onSelectionChange={(_keys,rows)=>setSelectedRows(rows)}/></WorkspaceTableRegion>}</Card>
  <Modal title={`批量派发（已选 ${selectedRows.length} 条）`} open={batchModalOpen} onCancel={()=>setBatchModalOpen(false)} onOk={()=>batchForm.submit()} confirmLoading={batchMutation.isPending} okText="确认派发" cancelText="取消" destroyOnHidden>
    <Alert type="info" showIcon message="仅“已受理”状态的工单可派发；如存在状态不符或版本冲突，将按单反馈结果。" style={{marginBottom:16}}/>
    <Form form={batchForm} layout="vertical" onFinish={values=>batchMutation.mutate(values)}>
      <Form.Item name="department_id" label="责任部门" rules={[{required:true,message:'请选择责任部门'}]}>
        <Select placeholder="请选择责任部门" loading={departments.isLoading}
          onChange={()=>batchForm.setFieldValue('assigned_user_id',undefined)}
          options={departments.data?.filter(d=>d.is_active).map(d=>({value:d.id,label:d.name}))}/>
      </Form.Item>
      <Form.Item name="assigned_user_id" label="承办人（可选）">
        <Select allowClear disabled={!selectedDepartmentId} loading={departmentStaff.isLoading}
          placeholder={selectedDepartmentId?'不指定则由部门自行认领':'请先选择责任部门'}
          options={departmentStaff.data?.filter(u=>u.is_active).map(u=>({value:u.id,label:u.display_name}))}/>
      </Form.Item>
      <Form.Item name="note" label="派发备注（可选）">
        <Input.TextArea rows={3} maxLength={2000} showCount placeholder="批量派发"/>
      </Form.Item>
    </Form>
  </Modal>
  <Modal title="批量派发结果" open={Boolean(batchResult)} onCancel={()=>setBatchResult(null)} footer={<Button type="primary" onClick={()=>setBatchResult(null)}>知道了</Button>} destroyOnHidden>
    {batchResult && (
      <Space direction="vertical" size={14} style={{width:'100%'}}>
        <Alert type={batchResult.failed.length>0?'warning':'success'} showIcon
          message={`成功 ${batchResult.succeeded.length} 条，失败 ${batchResult.failed.length} 条`}/>
        {batchResult.succeeded.length>0 && (
          <div>
            <Typography.Text strong>派发成功（{batchResult.succeeded.length}）</Typography.Text>
            <List size="small" style={{marginTop:8}} bordered dataSource={batchResult.succeeded} renderItem={item=>(
              <List.Item>
                <Space wrap>
                  <span className="workspace-reference">{item.ticket_id}</span>
                  {item.work_order_no && <Tag color="blue">{item.work_order_no}</Tag>}
                  <Tag color="green">v{item.version}</Tag>
                </Space>
              </List.Item>
            )}/>
          </div>
        )}
        {batchResult.failed.length>0 && (
          <div>
            <Typography.Text strong type="danger">派发失败（{batchResult.failed.length}）</Typography.Text>
            <List size="small" style={{marginTop:8}} bordered dataSource={batchResult.failed} renderItem={item=>(
              <List.Item>
                <Space direction="vertical" size={2} style={{width:'100%'}}>
                  <Space wrap>
                    <span className="workspace-reference">{item.ticket_id}</span>
                    <Tag color="red">{item.code}</Tag>
                  </Space>
                  <Typography.Text type="secondary">{item.message}</Typography.Text>
                </Space>
              </List.Item>
            )}/>
          </div>
        )}
      </Space>
    )}
  </Modal>
  </>
}
