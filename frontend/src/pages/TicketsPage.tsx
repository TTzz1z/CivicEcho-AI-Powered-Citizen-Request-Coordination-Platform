import { Button, Card, DatePicker, Drawer, Form, Input, Select, Space } from 'antd'
import { FilterOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listCategories } from '../api/admin'
import { listTickets, ticketKeys } from '../api/tickets'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { TicketStatusTag, statusOptions } from '../components/TicketStatusTag'
import { TicketTable } from '../components/TicketTable'
import { useAuth } from '../auth/AuthContext'
import type { Priority, TicketFilters, TicketStatus } from '../types'
const {RangePicker}=DatePicker
const priorityOptions=[{value:'normal',label:'普通'},{value:'expedited',label:'加急'},{value:'urgent',label:'紧急'},{value:'major',label:'重大事件'}]
const slaOptions=[{value:'due_soon',label:'即将超时'},{value:'overdue',label:'已超时'},{value:'paused',label:'计时暂停'},{value:'on_track',label:'时限正常'}]

export function TicketsPage(){
  const {user}=useAuth();const [params,setParams]=useSearchParams();const categories=useQuery({queryKey:['categories'],queryFn:listCategories})
  const [advancedOpen,setAdvancedOpen]=useState(false)
  const filters=useMemo<TicketFilters>(()=>({page:Number(params.get('page')||1),page_size:Number(params.get('page_size')||20),status:(params.get('status')||undefined) as TicketStatus|undefined,request_type:params.get('request_type')||undefined,category_id:params.get('category_id')?Number(params.get('category_id')):undefined,priority:(params.get('priority')||undefined) as Priority|undefined,sla_state:(params.get('sla_state')||undefined) as TicketFilters['sla_state'],keyword:params.get('keyword')||undefined,created_from:params.get('created_from')||undefined,created_to:params.get('created_to')||undefined,mine:params.get('mine')==='true'||user?.role==='citizen',my_department:params.get('my_department')==='true',sort:(params.get('sort')||'created_at') as TicketFilters['sort'],order:(params.get('order')||'desc') as TicketFilters['order']}),[params,user])
  const query=useQuery({queryKey:ticketKeys.list(filters),queryFn:()=>listTickets(filters)})
  const update=(next:TicketFilters)=>{const clean=new URLSearchParams();Object.entries(next).forEach(([k,v])=>{if(v!==undefined&&v!==''&&v!==false)clean.set(k,String(v))});setParams(clean)}
  const base=user?.role==='admin'?'/admin/tickets':user?.role==='agent'?'/agent/tickets':user?.role==='department_staff'?'/department/tickets':'/citizen/tickets';const title=user?.role==='citizen'?'我的工单':user?.role==='department_staff'?'部门工单':user?.role==='agent'?'坐席工单台':'全部工单'
  const categoryOptions=categories.data?.filter(c=>c.is_active).map(c=>({value:c.id,label:`${'　'.repeat(c.level-1)}${c.name} · ${c.code}`}))
  const activeFilterCount=[filters.request_type,filters.category_id,filters.priority,filters.sla_state,filters.created_from,filters.mine,filters.my_department].filter(v=>v!==undefined&&v!==''&&v!==false).length
  return <><PageHeader eyebrow="TICKET CENTER" title={title} description="关键词与状态首屏直达;分类、优先级、SLA 收进高级筛选,条件保留在网址中。" extra={query.isFetching&&<TicketStatusTag status="processing" label="正在同步"/>}/>
  <Card className="surface" style={{marginBottom:16}}>
    <Form layout="inline" initialValues={{status:filters.status,keyword:filters.keyword}} onFinish={v=>update({...filters,page:1,status:v.status,keyword:v.keyword?.trim()})}>
      <Form.Item name="keyword"><Input allowClear prefix={<SearchOutlined/>} placeholder="编号、描述或地点" style={{width:280}}/></Form.Item>
      <Form.Item name="status"><Select allowClear placeholder="全部状态" style={{width:140}} options={statusOptions}/></Form.Item>
      <Form.Item><Space>
        <Button type="primary" htmlType="submit">查询</Button>
        <Button icon={<FilterOutlined/>} onClick={()=>setAdvancedOpen(true)}>
          高级筛选{activeFilterCount>0?` (${activeFilterCount})`:''}
        </Button>
        <Button icon={<ReloadOutlined/>} onClick={()=>setParams({})}>重置</Button>
      </Space></Form.Item>
    </Form>
  </Card>
  <Drawer title="高级筛选" placement="right" width={380} open={advancedOpen} onClose={()=>setAdvancedOpen(false)}>
    <Form layout="vertical" initialValues={{request_type:filters.request_type,category_id:filters.category_id,priority:filters.priority,sla_state:filters.sla_state,date:filters.created_from?[dayjs(filters.created_from),dayjs(filters.created_to)]:undefined,scope:filters.mine?'mine':'department'}} onFinish={v=>{update({...filters,page:1,request_type:v.request_type,category_id:v.category_id,priority:v.priority,sla_state:v.sla_state,mine:user?.role==='citizen'||(user?.role==='department_staff'&&v.scope==='mine'),my_department:user?.role==='department_staff'&&v.scope==='department',created_from:v.date?.[0]?.startOf('day').toISOString(),created_to:v.date?.[1]?.add(1,'day').startOf('day').toISOString()});setAdvancedOpen(false)}}>
      <Form.Item name="category_id" label="诉求分类"><Select showSearch optionFilterProp="label" allowClear placeholder="全部分类" options={categoryOptions}/></Form.Item>
      <Form.Item name="priority" label="优先级"><Select allowClear placeholder="全部优先级" options={priorityOptions}/></Form.Item>
      <Form.Item name="sla_state" label="SLA 状态"><Select allowClear placeholder="全部 SLA 状态" options={slaOptions}/></Form.Item>
      <Form.Item name="request_type" label="诉求类型"><Select allowClear placeholder="全部类型" options={['投诉','建议','咨询','求助'].map(v=>({value:v,label:v}))}/></Form.Item>
      {user?.role==='department_staff'&&<Form.Item name="scope" label="工单范围"><Select options={[{value:'department',label:'本部门工单'},{value:'mine',label:'分派给我的工单'}]}/></Form.Item>}
      <Form.Item name="date" label="创建时间范围"><RangePicker style={{width:'100%'}}/></Form.Item>
      <Form.Item><Space style={{width:'100%',justifyContent:'flex-end'}}>
        <Button onClick={()=>setAdvancedOpen(false)}>取消</Button>
        <Button type="primary" htmlType="submit">应用筛选</Button>
      </Space></Form.Item>
    </Form>
  </Drawer>
  <Card className="surface" styles={{body:{padding:0}}}>{query.isError?<ErrorState error={query.error} retry={()=>query.refetch()}/>:<TicketTable items={query.data?.items} total={query.data?.total} loading={query.isLoading} filters={filters} onChange={update} basePath={base}/>}</Card></>
}
