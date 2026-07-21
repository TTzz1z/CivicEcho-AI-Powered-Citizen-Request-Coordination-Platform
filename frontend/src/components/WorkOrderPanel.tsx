import {
  Alert, Button, Card, Collapse, Descriptions, Empty, Form, Input, Modal, Select, Space, Tag, Timeline, Typography, message,
} from 'antd'
import {
  ApartmentOutlined, CheckCircleOutlined, RetweetOutlined, RollbackOutlined, TeamOutlined, UserSwitchOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listDepartments, listDepartmentStaff } from '../api/admin'
import {
  assignWorkOrder, createWorkOrder, openTicketDispute, resolveTicketDispute, returnTicketToDepartment,
  returnWorkOrder, reviewResolveTicket, startWorkOrder, submitWorkOrderResult, summarizeTicket, transferWorkOrder,
} from '../api/tickets'
import { ApiError } from '../api/client'
import type { TicketDetail, User, WorkOrder, WorkOrderType } from '../types'

type Mode = 'create'|'assign'|'start'|'return'|'transfer'|'submit'|'summarize'|'review_resolve'|'return_to_department'|'dispute'|'resolve_dispute'
type Values = {
  task_type?:WorkOrderType; department_id?:number; target_department_id?:number; assignee_user_id?:number;
  instructions?:string; remark?:string; result_summary?:string; result_measures?:string;
  result_outcome?:string; public_content?:string; internal_note?:string;
  resolution_summary?:string; resolution_measures?:string; resolution_outcome?:string; public_reply?:string;
  dispute_reason?:string; resolution?:string; primary_work_order_id?:string; return_reason?:string;
}

const typeMeta = {
  primary:{label:'主办任务',color:'cyan'}, support:{label:'协办任务',color:'geekblue'}, review:{label:'复核任务',color:'purple'},
} as const
const statusMeta = {
  pending:{label:'待办理',color:'default'}, processing:{label:'办理中',color:'processing'}, returned:{label:'已退回',color:'warning'},
  transferred:{label:'已转派',color:'default'}, submitted:{label:'已提交',color:'success'}, cancelled:{label:'已取消',color:'default'},
} as const
const collaborationLabels = {
  none:'常规流转', awaiting_citizen:'待市民补充', awaiting_dispatch:'待重新派发', in_progress:'多部门办理中',
  awaiting_summary:'待主办汇总', awaiting_review:'待坐席审核', disputed:'归属争议协调中', completed:'协同已完成',
} as const
const modeTitles:Record<Mode,string> = {
  create:'新增部门处置任务', assign:'指定任务责任人', start:'开始办理任务', return:'退回坐席重新派发',
  transfer:'转派其他部门', submit:'提交本部门处理结果', summarize:'汇总最终答复',
  review_resolve:'坐席审核办结', return_to_department:'退回主办部门补充',
  dispute:'发起责任归属争议', resolve_dispute:'管理员协调争议',
}
const outcomes=[{value:'resolved',label:'已解决'},{value:'partially_resolved',label:'部分解决'},{value:'unresolved',label:'暂未解决'}]

export function WorkOrderPanel({ticket,user,onChanged,collapseCompleted=false}:{ticket:TicketDetail;user:User;onChanged:()=>void;collapseCompleted?:boolean}){
  const [mode,setMode]=useState<Mode|null>(null)
  const [selected,setSelected]=useState<WorkOrder|null>(null)
  const [staffDepartment,setStaffDepartment]=useState<number|undefined>()
  const [form]=Form.useForm<Values>()
  const departments=useQuery({queryKey:['departments'],queryFn:listDepartments,enabled:user.role!=='citizen'})
  const staff=useQuery({queryKey:['department-staff',staffDepartment],queryFn:()=>listDepartmentStaff(staffDepartment!),enabled:!!staffDepartment&&user.role!=='citizen'})
  const primary=ticket.work_orders.find(x=>x.task_type==='primary'&&['pending','processing','submitted'].includes(x.status))
  const canCreate=['agent','admin'].includes(user.role)&&['accepted','assigned','processing'].includes(ticket.status)
  const canSummarize=ticket.collaboration_status==='awaiting_summary'&&(
    user.role==='admin'||(user.role==='department_staff'&&!!primary&&primary.department_id===user.department_id&&(primary.assignee_user_id==null||primary.assignee_user_id===user.id))
  )
  // P0-A: only agents (and admin as fallback) can review-resolve or return to department.
  const canReviewResolve=ticket.collaboration_status==='awaiting_review'&&['agent','admin'].includes(user.role)&&ticket.status==='processing'

  const open=(next:Mode,order?:WorkOrder)=>{
    form.resetFields();setSelected(order||null);setMode(next)
    const departmentId=order?.department_id
    setStaffDepartment(departmentId)
    if(next==='create')form.setFieldsValue({task_type:primary?'support':'primary'})
    if(next==='submit'||next==='summarize')form.setFieldsValue({result_outcome:'resolved',resolution_outcome:'resolved'})
  }
  const close=()=>{setMode(null);setSelected(null);setStaffDepartment(undefined);form.resetFields()}
  const mutation=useMutation({
    mutationFn:async(v:Values)=>{
      if(mode==='create')return createWorkOrder(ticket.ticket_id,{version:ticket.version,task_type:v.task_type!,department_id:v.department_id!,assignee_user_id:v.assignee_user_id,instructions:v.instructions!})
      if(mode==='assign')return assignWorkOrder(ticket.ticket_id,selected!.id,{version:selected!.version,remark:v.remark!,assignee_user_id:v.assignee_user_id!})
      if(mode==='start')return startWorkOrder(ticket.ticket_id,selected!.id,{version:selected!.version,remark:v.remark!})
      if(mode==='return')return returnWorkOrder(ticket.ticket_id,selected!.id,{version:selected!.version,remark:v.remark!})
      if(mode==='transfer')return transferWorkOrder(ticket.ticket_id,selected!.id,{version:selected!.version,remark:v.remark!,target_department_id:v.target_department_id!,assignee_user_id:v.assignee_user_id})
      if(mode==='submit')return submitWorkOrderResult(ticket.ticket_id,selected!.id,{version:selected!.version,remark:v.remark!,result_summary:v.result_summary!,result_measures:v.result_measures!,result_outcome:v.result_outcome!,public_content:v.public_content!,internal_note:v.internal_note})
      if(mode==='summarize')return summarizeTicket(ticket.ticket_id,{version:ticket.version,remark:v.remark!,resolution_summary:v.resolution_summary!,resolution_measures:v.resolution_measures!,resolution_outcome:v.resolution_outcome!,public_reply:v.public_reply!,internal_note:v.internal_note})
      if(mode==='review_resolve')return reviewResolveTicket(ticket.ticket_id,{version:ticket.version,remark:v.remark!,resolution_summary:v.resolution_summary!,resolution_measures:v.resolution_measures!,resolution_outcome:v.resolution_outcome!,public_reply:v.public_reply!,internal_note:v.internal_note})
      if(mode==='return_to_department')return returnTicketToDepartment(ticket.ticket_id,{version:ticket.version,remark:v.remark!,return_reason:v.return_reason!})
      if(mode==='dispute')return openTicketDispute(ticket.ticket_id,{version:ticket.version,remark:v.remark!,dispute_reason:v.dispute_reason!})
      return resolveTicketDispute(ticket.ticket_id,{version:ticket.version,remark:v.remark!,resolution:v.resolution!,primary_work_order_id:v.primary_work_order_id})
    },
    onSuccess:()=>{message.success('协同操作已完成');close();onChanged()},
    onError:e=>message.error(e instanceof ApiError?e.message:'协同操作失败'),
  })
  const options=departments.data?.filter(x=>x.is_active).map(x=>({value:x.id,label:x.name}))
  const staffOptions=staff.data?.map(x=>({value:x.id,label:x.display_name}))

  return <Card className="surface detail-card collaboration-panel" style={{marginTop:20}} title={<Space><ApartmentOutlined/>部门协同任务<Tag color={ticket.collaboration_status==='disputed'?'red':ticket.collaboration_status==='completed'?'green':'cyan'}>{collaborationLabels[ticket.collaboration_status]}</Tag></Space>} extra={<Space wrap>
    {canCreate&&<Button type="primary" icon={<TeamOutlined/>} onClick={()=>open('create')}>新增任务</Button>}
    {canSummarize&&<Button type="primary" icon={<CheckCircleOutlined/>} onClick={()=>open('summarize')}>汇总最终答复</Button>}
    {canReviewResolve&&<Button type="primary" icon={<CheckCircleOutlined/>} onClick={()=>open('review_resolve')}>审核办结</Button>}
    {canReviewResolve&&<Button icon={<RollbackOutlined/>} onClick={()=>open('return_to_department')}>退回部门</Button>}
    {user.role!=='citizen'&&ticket.collaboration_status!=='disputed'&&ticket.collaboration_status!=='awaiting_review'&&ticket.work_orders.length>0&&<Button danger onClick={()=>open('dispute')}>归属争议</Button>}
    {user.role==='admin'&&ticket.collaboration_status==='disputed'&&<Button danger type="primary" onClick={()=>open('resolve_dispute')}>协调争议</Button>}
  </Space>}>
    {ticket.collaboration_status==='awaiting_dispatch'&&<Alert showIcon type="warning" message="主办部门已退回，等待坐席重新派发" description={ticket.dispatch_return_reason} style={{marginBottom:16}}/>}
    {ticket.collaboration_status==='awaiting_review'&&<Alert showIcon type="info" message="主办部门已提交答复，等待坐席审核办结" style={{marginBottom:16}}/>}
    {ticket.collaboration_status==='disputed'&&<Alert showIcon type="error" message="责任归属存在争议" description={ticket.dispute_reason} style={{marginBottom:16}}/>}
    {ticket.dispute_resolution&&<Alert showIcon type="success" message="管理员协调结论" description={ticket.dispute_resolution} style={{marginBottom:16}}/>}
    {!ticket.work_orders.length?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未创建部门处置任务"/>:(() => {
      const isActive=(status:string)=>['pending','processing','returned','submitted'].includes(status)
      const activeOrders=ticket.work_orders.filter(o=>isActive(o.status))
      const earlierOrders=ticket.work_orders.filter(o=>!isActive(o.status))
      const primaryList=activeOrders.length?activeOrders:ticket.work_orders
      const renderOrders=(orders:WorkOrder[])=>(
        <div className="work-order-grid">
          {orders.map(order=>{
            const active=['pending','processing'].includes(order.status)
            const ownDepartment=user.role==='department_staff'&&user.department_id===order.department_id
            const canOperate=user.role==='admin'||(ownDepartment&&(order.assignee_user_id==null||order.assignee_user_id===user.id))
            const canAssign=['agent','admin'].includes(user.role)||ownDepartment
            return <article className={`work-order-card type-${order.task_type}`} key={order.id}>
              <div className="work-order-head"><div><Tag color={typeMeta[order.task_type].color}>{typeMeta[order.task_type].label}</Tag><Tag color={statusMeta[order.status].color}>{statusMeta[order.status].label}</Tag></div><Typography.Text type="secondary" copyable>{order.work_order_no}</Typography.Text></div>
              <h3>{order.department_name}</h3>
              <p className="work-order-instruction">{order.instructions}</p>
              <Descriptions size="small" column={1} items={[{key:'owner',label:'责任人',children:order.assignee_name||'待指定'},{key:'updated',label:'最近更新',children:new Date(order.updated_at).toLocaleString('zh-CN')}]}/>
              {order.result_summary&&<div className="work-order-result"><b>{order.result_summary}</b><p>{order.public_content}</p></div>}
              {order.return_reason&&<Alert type="warning" showIcon message={order.return_reason}/>}
              {user.role!=='citizen'&&<div className="work-order-actions">
                {canAssign&&active&&<Button size="small" icon={<UserSwitchOutlined/>} onClick={()=>open('assign',order)}>责任人</Button>}
                {canOperate&&order.status==='pending'&&<Button size="small" type="primary" onClick={()=>open('start',order)}>开始办理</Button>}
                {canOperate&&active&&<Button size="small" icon={<RetweetOutlined/>} onClick={()=>open('transfer',order)}>转派</Button>}
                {canOperate&&active&&<Button size="small" icon={<RollbackOutlined/>} onClick={()=>open('return',order)}>退回坐席</Button>}
                {canOperate&&active&&<Button size="small" type="primary" onClick={()=>open('submit',order)}>提交结果</Button>}
              </div>}
              {order.history.length>0&&user.role!=='citizen'&&<Timeline className="work-order-history" items={order.history.slice().reverse().map(h=>({children:<><b>{h.content}</b><div>{new Date(h.created_at).toLocaleString('zh-CN')}</div></>}))}/>}
            </article>
          })}
        </div>
      )
      if(!collapseCompleted) return renderOrders(ticket.work_orders)
      return <>
        {renderOrders(primaryList)}
        {earlierOrders.length>0&&activeOrders.length>0&&(
          <Collapse
            style={{marginTop:16}}
            items={[{key:'earlier',label:`较早的协同任务（${earlierOrders.length}）`,children:renderOrders(earlierOrders)}]}
          />
        )}
      </>
    })()}
    <Modal title={mode?modeTitles[mode]:''} open={!!mode} onCancel={close} onOk={()=>form.submit()} confirmLoading={mutation.isPending} okText="确认提交" cancelText="取消" width={640} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={v=>mutation.mutate(v)}>
        {mode==='create'&&<><Form.Item name="task_type" label="任务角色" rules={[{required:true}]}><Select options={[{value:'primary',label:'主办任务'},{value:'support',label:'协办任务'},{value:'review',label:'复核任务'}]}/></Form.Item><Form.Item name="department_id" label="处置部门" rules={[{required:true}]}><Select options={options} onChange={v=>{setStaffDepartment(v);form.setFieldValue('assignee_user_id',undefined)}}/></Form.Item><Form.Item name="assignee_user_id" label="责任人（可稍后指定）"><Select allowClear loading={staff.isLoading} options={staffOptions}/></Form.Item><Form.Item name="instructions" label="任务要求" rules={[{required:true},{min:2}]}><Input.TextArea rows={4} maxLength={5000} showCount/></Form.Item></>}
        {mode==='assign'&&<Form.Item name="assignee_user_id" label="责任人" rules={[{required:true}]}><Select loading={staff.isLoading} options={staffOptions}/></Form.Item>}
        {mode==='transfer'&&<><Form.Item name="target_department_id" label="目标部门" rules={[{required:true}]}><Select options={options?.filter(x=>x.value!==selected?.department_id)} onChange={v=>{setStaffDepartment(v);form.setFieldValue('assignee_user_id',undefined)}}/></Form.Item><Form.Item name="assignee_user_id" label="目标责任人（可选）"><Select allowClear loading={staff.isLoading} options={staffOptions}/></Form.Item></>}
        {mode==='submit'&&<><Form.Item name="result_summary" label="结果摘要" rules={[{required:true},{min:2}]}><Input maxLength={500} showCount/></Form.Item><Form.Item name="result_measures" label="处理措施" rules={[{required:true},{min:2}]}><Input.TextArea rows={3}/></Form.Item><Form.Item name="result_outcome" label="处理结果" rules={[{required:true}]}><Select options={outcomes}/></Form.Item><Form.Item name="public_content" label="本部门公开答复" rules={[{required:true},{min:2}]}><Input.TextArea rows={4}/></Form.Item><Form.Item name="internal_note" label="内部备注"><Input.TextArea rows={2}/></Form.Item></>}
        {mode==='summarize'&&<><Alert type="info" showIcon message="请综合全部部门结果形成统一对外答复。" style={{marginBottom:16}}/><Form.Item name="resolution_summary" label="最终结果摘要" rules={[{required:true},{min:2}]}><Input/></Form.Item><Form.Item name="resolution_measures" label="综合处理措施" rules={[{required:true},{min:2}]}><Input.TextArea rows={3}/></Form.Item><Form.Item name="resolution_outcome" label="最终结果" rules={[{required:true}]}><Select options={outcomes}/></Form.Item><Form.Item name="public_reply" label="对市民最终答复" rules={[{required:true},{min:2}]}><Input.TextArea rows={5}/></Form.Item><Form.Item name="internal_note" label="内部备注"><Input.TextArea rows={2}/></Form.Item></>}
        {mode==='review_resolve'&&<><Alert type="info" showIcon message="审核通过后工单变为待市民确认，市民可评价或申诉。" style={{marginBottom:16}}/><Form.Item name="resolution_summary" label="最终结果摘要" rules={[{required:true},{min:2}]}><Input/></Form.Item><Form.Item name="resolution_measures" label="综合处理措施" rules={[{required:true},{min:2}]}><Input.TextArea rows={3}/></Form.Item><Form.Item name="resolution_outcome" label="最终结果" rules={[{required:true}]}><Select options={outcomes}/></Form.Item><Form.Item name="public_reply" label="对市民最终答复" rules={[{required:true},{min:2}]}><Input.TextArea rows={5}/></Form.Item><Form.Item name="internal_note" label="内部备注"><Input.TextArea rows={2}/></Form.Item></>}
        {mode==='return_to_department'&&<><Alert type="warning" showIcon message="退回后主办部门可补充材料并重新提交审核。" style={{marginBottom:16}}/><Form.Item name="return_reason" label="退回原因" rules={[{required:true},{min:2}]}><Input.TextArea rows={4}/></Form.Item></>}
        {mode==='dispute'&&<Form.Item name="dispute_reason" label="争议说明" rules={[{required:true},{min:2}]}><Input.TextArea rows={4}/></Form.Item>}
        {mode==='resolve_dispute'&&<><Form.Item name="resolution" label="协调结论" rules={[{required:true},{min:2}]}><Input.TextArea rows={4}/></Form.Item><Form.Item name="primary_work_order_id" label="重新指定主办任务（可选）"><Select allowClear options={ticket.work_orders.filter(x=>['pending','processing','submitted'].includes(x.status)).map(x=>({value:x.id,label:`${x.department_name} · ${x.work_order_no}`}))}/></Form.Item></>}
        {mode&&mode!=='create'&&mode!=='submit'&&mode!=='summarize'&&mode!=='review_resolve'&&mode!=='dispute'&&mode!=='resolve_dispute'&&<Alert type={mode==='return'||mode==='return_to_department'?'warning':'info'} showIcon message={mode==='return'?'退回后主单进入待重新派发，原任务完整保留。':mode==='return_to_department'?'退回后主办部门可补充材料并重新提交审核。':'操作将写入任务历史。'} style={{marginBottom:16}}/>}
        {mode&&mode!=='create'&&<Form.Item name="remark" label="操作说明" rules={[{required:true},{min:2}]}><Input.TextArea rows={3} maxLength={2000} showCount/></Form.Item>}
      </Form>
    </Modal>
  </Card>
}
