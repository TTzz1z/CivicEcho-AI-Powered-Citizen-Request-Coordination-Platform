import { Alert, Button, Card, Collapse, Descriptions, Divider, Form, Input, Modal, Select, Space, Switch, Timeline, Typography, message } from 'antd'
import { BellOutlined, CheckOutlined, ClockCircleOutlined, CloseOutlined, EditOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  acceptTicket, assignTicket, closeTicket, getTicket, pauseTicketSla, rejectTicket, remindTicket,
  requestTicketSupplement, resumeTicketSla, submitTicketFeedback, submitTicketSupplement, ticketAction, ticketKeys, updateContact,
} from '../api/tickets'
import { listCategories, listDepartments, listUsers } from '../api/admin'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { TicketStatusTag } from '../components/TicketStatusTag'
import { AttachmentPanel } from '../components/AttachmentPanel'
import { WorkOrderPanel } from '../components/WorkOrderPanel'
import { AiCaseAssistant } from '../components/AiCaseAssistant'
import type { FeedbackRating, Priority } from '../types'

type Action = 'accept'|'reject'|'assign'|'process'|'note'|'close'|'contact'|'feedback'|'pause_sla'|'resume_sla'|'remind'|'request_supplement'|'submit_supplement'
type ActionFormValues = {
  remark?:string; department_id?:number; assigned_user_id?:number; contact?:string;
  resolution_summary?:string; resolution_measures?:string; resolution_outcome?:string;
  public_reply?:string; internal_note?:string; reason_code?:string; rejection_detail?:string;
  suggested_channel?:string; needs_supplement?:boolean; override_reason?:string;
  rating?:FeedbackRating; comment?:string;
  category_id?:number; priority?:Priority; reason?:string;
  supplement_reason?:string; supplement_content?:string;
}

const labels:Record<Action,string> = {
  accept:'受理工单', reject:'不予受理', assign:'派发部门', process:'开始处理',
  note:'添加内部处理记录', close:'管理员代办结',
  contact:'修改联系方式', feedback:'确认结果并评价',
  pause_sla:'暂停 SLA 计时',resume_sla:'恢复 SLA 计时',remind:'催办工单',
  request_supplement:'退回市民补充材料',submit_supplement:'提交补充材料',
}
const outcomeLabels:Record<string,string> = {resolved:'已解决',partially_resolved:'部分解决',unresolved:'暂未解决'}
const ratingLabels:Record<string,string> = {satisfied:'满意',mostly_satisfied:'基本满意',dissatisfied:'不满意'}
const reasonLabels:Record<string,string> = {
  out_of_scope:'不属于受理范围', out_of_jurisdiction:'不属于本辖区', duplicate:'重复诉求',
  insufficient_information:'信息不足', handled_elsewhere:'已通过其他渠道处理',
  legal_or_review:'涉及司法或行政复议', other:'其他',
}

export function allowedActions(role:string|undefined,status:string):Action[] {
  // Admin handles exceptions (close/force paths); normal resolve stays with agent/department flow.
  if(role==='admin') return status==='pending'?['accept','reject','remind']:status==='accepted'?['assign','pause_sla','remind']:status==='assigned'?['process','pause_sla','remind']:status==='processing'?['pause_sla','remind']:status==='resolved'?['close','process']:[]
  if(role==='agent') return status==='pending'?['accept','reject','contact','remind']:status==='accepted'?['assign','contact','remind']:[]
  // Department staff submit results via WorkOrderPanel; they do not self-resolve the parent ticket.
  if(role==='department_staff') return status==='assigned'?['process','pause_sla','remind']:status==='processing'?['note','pause_sla','remind']:[]
  if(role==='citizen') return ['pending','accepted','assigned','processing'].includes(status)?(['pending','accepted'].includes(status)?['contact','remind']:['remind']):status==='resolved'?['feedback']:[]
  return []
}

export function TicketDetailPage(){
  const {ticketId=''}=useParams(); const {user}=useAuth(); const nav=useNavigate(); const qc=useQueryClient()
  const [active,setActive]=useState<Action|null>(null); const [form]=Form.useForm<ActionFormValues>()
  const query=useQuery({queryKey:ticketKeys.detail(ticketId),queryFn:()=>getTicket(ticketId)})
  const departments=useQuery({queryKey:['departments'],queryFn:listDepartments,enabled:active==='assign'})
  const categories=useQuery({queryKey:['categories'],queryFn:listCategories})
  const users=useQuery({queryKey:['users','assignable'],queryFn:listUsers,enabled:active==='assign'&&user?.role==='admin'})
  const mutation=useMutation({
    mutationFn:async(v:ActionFormValues)=>{
      const t=query.data!; const remark=v.remark||''
      if(active==='accept') return acceptTicket(t.ticket_id,{version:t.version,remark,category_id:v.category_id,priority:v.priority!})
      if(active==='assign') return assignTicket(t.ticket_id,{version:t.version,remark,department_id:v.department_id!,assigned_user_id:v.assigned_user_id})
      if(active==='contact') return updateContact(t.ticket_id,{version:t.version,remark,contact:v.contact})
      if(active==='reject') return rejectTicket(t.ticket_id,{version:t.version,remark,reason_code:v.reason_code!,rejection_detail:v.rejection_detail!,suggested_channel:v.suggested_channel,needs_supplement:v.needs_supplement||false})
      if(active==='close') return closeTicket(t.ticket_id,{version:t.version,remark,override_reason:v.override_reason!})
      if(active==='feedback') return submitTicketFeedback(t.ticket_id,{version:t.version,rating:v.rating!,comment:v.comment})
      if(active==='pause_sla') return pauseTicketSla(t.ticket_id,{version:t.version,remark,reason:v.reason!})
      if(active==='resume_sla') return resumeTicketSla(t.ticket_id,{version:t.version,remark})
      if(active==='remind') return remindTicket(t.ticket_id,{version:t.version,remark})
      if(active==='request_supplement') return requestTicketSupplement(t.ticket_id,{version:t.version,remark,supplement_reason:v.supplement_reason!})
      if(active==='submit_supplement') return submitTicketSupplement(t.ticket_id,{version:t.version,remark,supplement_content:v.supplement_content!})
      return ticketAction(t.ticket_id,active as 'process'|'note',t.version,remark)
    },
    onSuccess:()=>{message.success('操作已完成，工单数据已刷新');setActive(null);form.resetFields();void qc.invalidateQueries({queryKey:ticketKeys.all});void qc.invalidateQueries({queryKey:ticketKeys.detail(ticketId)})},
    onError:e=>{if(e instanceof ApiError&&e.status===409){message.warning('数据已被他人更新，已为你加载最新工单');void qc.invalidateQueries({queryKey:ticketKeys.detail(ticketId)})}else message.error(e instanceof Error?e.message:'操作失败')},
  })
  if(query.isLoading)return <Card loading/>
  if(query.isError||!query.data)return <ErrorState error={query.error} retry={()=>query.refetch()}/>
  const t=query.data; let actions=allowedActions(user?.role,t.status);if(t.sla_paused_at)actions=actions.map(a=>a==='pause_sla'?'resume_sla':a)
  const isMultiDepartment=t.work_orders.length>1||t.work_orders.some(order=>order.task_type!=='primary')
  if(isMultiDepartment&&['department_staff','admin'].includes(user?.role||''))actions=actions.filter(a=>!['process','note'].includes(a))
  if(['agent','admin'].includes(user?.role||'')&&['pending','accepted'].includes(t.status)&&t.collaboration_status!=='awaiting_citizen')actions.push('request_supplement')
  if(user?.role==='citizen'&&t.collaboration_status==='awaiting_citizen')actions=['submit_supplement',...actions.filter(a=>a!=='contact')]
  const openAction=(action:Action)=>{form.resetFields();if(action==='feedback')form.setFieldsValue({rating:'satisfied'});if(action==='reject')form.setFieldsValue({needs_supplement:false});if(action==='accept')form.setFieldsValue({priority:'normal'});if(action==='assign'){const category=categories.data?.find(c=>c.id===t.category_id);form.setFieldsValue({department_id:category?.default_department_id||undefined})}setActive(action)}
  const actionLabel=(action:Action)=>action==='process'&&t.status==='resolved'?'退回重新办理':labels[action]
  const latestHistory=[...t.history].sort((a,b)=>dayjs(b.created_at).valueOf()-dayjs(a.created_at).valueOf())[0]
  const slaMessage=({overdue:'已超时',due_soon:'即将超时',paused:'计时已暂停',on_track:'时限正常'} as Record<string,string>)[t.sla_state]
  const slaDetail=t.sla_paused_at?`暂停原因：${t.sla_pause_reason}`:t.remaining_seconds!=null?`${t.remaining_seconds<0?'超出':'剩余'} ${Math.floor(Math.abs(t.remaining_seconds)/3600)} 小时 ${Math.floor(Math.abs(t.remaining_seconds)%3600/60)} 分钟`:'暂无截止时间'
  return <>
    <PageHeader eyebrow="TICKET DETAIL" title={t.ticket_id} description={`版本 ${t.version} · 最后更新 ${dayjs(t.updated_at).format('YYYY-MM-DD HH:mm')}`} extra={<Space><Button onClick={()=>nav(-1)}>返回列表</Button><TicketStatusTag status={t.status} label={t.status_label}/></Space>}/>
    {t.collaboration_status==='awaiting_citizen'&&<Alert showIcon type="warning" message="工单正在等待市民补充材料" description={t.supplement_reason} style={{marginBottom:20}}/>}

    <Card className="surface detail-card" style={{marginBottom:20}} title="办理焦点">
      <Descriptions column={{xs:1,sm:2,md:3}} items={[
        {key:'status',label:'当前状态',children:<TicketStatusTag status={t.status} label={t.status_label}/>},
        {key:'department',label:'责任部门',children:t.department_name||'待派发'},
        {key:'assignee',label:'承办坐席/人员',children:t.assignee_name||'未指定'},
        {key:'sla',label:'SLA',children:<span>{slaMessage} · {slaDetail}</span>},
        {key:'round',label:'当前办理轮次',children:t.handling_round>1?`第 ${t.handling_round} 轮（重新办理）`:'第 1 轮'},
        {key:'latest',label:'最新办理结果',children:t.resolution_summary||t.public_reply||latestHistory?.content||latestHistory?.remark||'暂无结果'},
      ]}/>
      {actions.length>0&&<>
        <Divider style={{margin:'16px 0'}}/>
        <Typography.Text type="secondary" style={{display:'block',marginBottom:8}}>下一步可执行操作</Typography.Text>
        <div className="action-bar">{actions.map(a=><Button key={a} type={['accept','assign','process','close','feedback'].includes(a)?'primary':'default'} danger={a==='reject'} icon={a==='assign'?<SendOutlined/>:a==='contact'?<EditOutlined/>:a==='reject'?<CloseOutlined/>:a==='remind'?<BellOutlined/>:['pause_sla','resume_sla'].includes(a)?<ClockCircleOutlined/>:<CheckOutlined/>} onClick={()=>openAction(a)}>{actionLabel(a)}</Button>)}</div>
      </>}
    </Card>

    <div className="detail-grid"><div>
      <Card title="诉求内容" className="surface detail-card"><div className="description-block">{t.description}</div><Divider/><Descriptions column={{xs:1,sm:2}} items={[
        {key:'type',label:'诉求类型',children:t.request_type},{key:'category',label:'三级分类',children:t.category_path||'待坐席确认'},
        {key:'priority',label:'确认优先级',children:({normal:'普通',expedited:'加急',urgent:'紧急',major:'重大事件'} as Record<string,string>)[t.priority]||t.priority},{key:'requested',label:'市民紧急程度参考',children:t.requested_priority||'未提出'},
        {key:'location',label:'地点',children:t.location},{key:'time',label:'发生时间',children:t.occurred_at_text||'未提供'},
        {key:'target',label:'涉及对象',children:t.target||'未提供'},{key:'contact',label:'联系方式',children:t.contact||'未提供'},
        {key:'creator',label:'创建人',children:t.creator_name||'会话用户'},{key:'source',label:'来源',children:t.source},
      ]}/></Card>
      {t.resolution_summary&&<Card title="部门处理结果" className="surface detail-card" style={{marginTop:20}}><Descriptions column={1} items={[
        {key:'summary',label:'结果摘要',children:t.resolution_summary},
        {key:'measures',label:'处理措施',children:<Typography.Paragraph style={{whiteSpace:'pre-wrap',margin:0}}>{t.resolution_measures}</Typography.Paragraph>},
        {key:'outcome',label:'解决情况',children:outcomeLabels[t.resolution_outcome||'']||t.resolution_outcome},
        {key:'reply',label:'对市民公开答复',children:<Typography.Paragraph style={{whiteSpace:'pre-wrap',margin:0}}>{t.public_reply}</Typography.Paragraph>},
        ...(t.internal_note?[{key:'internal',label:'内部备注',children:<Alert type="warning" showIcon message={t.internal_note}/>}]:[]),
      ]}/></Card>}
      {t.rejection_reason_code&&<Card title="不予受理说明" className="surface detail-card" style={{marginTop:20}}><Descriptions column={1} items={[
        {key:'reason',label:'标准原因',children:reasonLabels[t.rejection_reason_code]||t.rejection_reason_code},
        {key:'detail',label:'详细说明',children:t.rejection_detail},{key:'channel',label:'建议办理渠道',children:t.suggested_channel||'未提供'},
        {key:'supplement',label:'需要补充材料',children:t.needs_supplement?'是':'否'},
      ]}/></Card>}
      {t.feedbacks.length>0&&<Card title="市民反馈" className="surface detail-card" style={{marginTop:20}}><Timeline items={t.feedbacks.slice().reverse().map(f=>({color:f.result==='closed'?'green':'orange',children:<div><b>{ratingLabels[f.rating]} · {f.result==='closed'?'确认办结':'申请重办'}</b>{f.comment&&<div style={{marginTop:4}}>{f.comment}</div>}<div style={{color:'#647680',fontSize:13,marginTop:4}}>{dayjs(f.created_at).format('YYYY-MM-DD HH:mm:ss')}</div></div>}))}/></Card>}

      <WorkOrderPanel ticket={t} user={user!} onChanged={()=>{void qc.invalidateQueries({queryKey:ticketKeys.all});void qc.invalidateQueries({queryKey:ticketKeys.detail(ticketId)})}} collapseCompleted/>

      <Collapse
        className="surface detail-card"
        style={{marginTop:20,background:'#fff'}}
        items={[
          {
            key:'history',
            label:'完整状态历史',
            children: t.history.length
              ? <Timeline items={t.history.slice().reverse().map(h=>({color:h.current_status==='closed'?'green':'blue',children:<div><b>{h.content||h.remark||h.operation_type}</b><div style={{color:'#647680',fontSize:13,marginTop:4}}>{dayjs(h.created_at).format('YYYY-MM-DD HH:mm:ss')} · {h.previous_status?`${h.previous_status} → `:''}{h.current_status}</div></div>}))}/>
              : <Alert type="info" message="暂无办理记录"/>,
          },
          {
            key:'audit',
            label:'审计记录（办理轨迹）',
            children: <Alert type="info" showIcon message="工单级审计以状态历史与操作备注为准；系统级审计日志请在管理后台“审计”中按工单号检索。"/>,
          },
          {
            key:'attachments',
            label:'附件材料',
            children: <AttachmentPanel ticketId={t.ticket_id} status={t.status} user={user}/>,
          },
          ...(user && ['department_staff','agent','admin'].includes(user.role) ? [{
            key:'ai',
            label:'AI 调用与办件建议',
            children: <AiCaseAssistant ticket={t} />,
          }] : []),
        ]}
      />
    </div><aside><Card title="SLA 时限" className={`surface detail-card sla-card ${t.sla_state}`}><Alert showIcon type={t.sla_state==='overdue'?'error':t.sla_state==='due_soon'?'warning':t.sla_state==='paused'?'info':'success'} message={slaMessage} description={slaDetail}/><Descriptions style={{marginTop:16}} column={1} items={[
      {key:'accept_due',label:'应受理时间',children:t.accept_due_at?dayjs(t.accept_due_at).format('YYYY-MM-DD HH:mm'):'—'},{key:'resolve_due',label:'应办结时间',children:t.resolve_due_at?dayjs(t.resolve_due_at).format('YYYY-MM-DD HH:mm'):'—'},{key:'actual_accept',label:'实际受理时间',children:t.accepted_at?dayjs(t.accepted_at).format('YYYY-MM-DD HH:mm'):'—'},{key:'actual_close',label:'实际办结时间',children:t.closed_at?dayjs(t.closed_at).format('YYYY-MM-DD HH:mm'):'—'},{key:'paused',label:'累计暂停',children:`${Math.floor(t.total_paused_seconds/60)} 分钟`},{key:'reminders',label:'催办次数',children:`${t.reminder_count} 次`},
    ]}/></Card><Card title="办理信息" className="surface detail-card" style={{marginTop:20}}><Descriptions column={1} items={[
      {key:'status',label:'当前状态',children:<TicketStatusTag status={t.status}/>},{key:'department',label:'责任部门',children:t.department_name||'待派发'},
      {key:'assignee',label:'承办人',children:t.assignee_name||'未指定'},{key:'created',label:'创建时间',children:dayjs(t.created_at).format('YYYY-MM-DD HH:mm')},
      {key:'accepted',label:'受理时间',children:t.accepted_at?dayjs(t.accepted_at).format('YYYY-MM-DD HH:mm'):'—'},
      {key:'resolved',label:'解决时间',children:t.resolved_at?dayjs(t.resolved_at).format('YYYY-MM-DD HH:mm'):'—'},
      {key:'closed',label:'办结方式',children:t.closure_type==='citizen_confirmed'?'市民确认':t.closure_type==='admin_override'?'管理员代办结':'—'},
      {key:'round',label:'处理轮次',children:t.handling_round>1?`第 ${t.handling_round} 轮（重新办理）`:'第 1 轮'},
    ]}/></Card></aside></div>
    <Modal title={active?actionLabel(active):''} open={!!active} onCancel={()=>setActive(null)} onOk={()=>form.submit()} confirmLoading={mutation.isPending} okText="确认提交" cancelText="取消" destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={v=>mutation.mutate(v)}>
        {active==='accept'&&<><Alert type="info" showIcon message="市民填写的紧急程度仅作参考；分类和最终优先级由坐席确认，并据此生成 SLA。" style={{marginBottom:16}}/><Form.Item name="category_id" label="末级诉求分类" rules={[{required:true,message:'请选择末级诉求分类'}]}><Select showSearch optionFilterProp="label" options={categories.data?.filter(c=>c.is_active&&!categories.data?.some(child=>child.parent_id===c.id&&child.is_active)).map(c=>({value:c.id,label:`${c.name} · ${c.code}`}))}/></Form.Item><Form.Item name="priority" label="确认优先级" rules={[{required:true}]}><Select options={[{value:'normal',label:'普通'},{value:'expedited',label:'加急'},{value:'urgent',label:'紧急'},{value:'major',label:'重大事件'}]}/></Form.Item></>}
        {active==='assign'&&<><Form.Item name="department_id" label="责任部门" rules={[{required:true,message:'请选择责任部门'}]}><Select options={departments.data?.filter(d=>d.is_active).map(d=>({value:d.id,label:d.name}))}/></Form.Item><Form.Item name="assigned_user_id" label="承办人（可选）"><Select allowClear options={users.data?.filter(u=>u.role==='department_staff'&&u.is_active).map(u=>({value:u.id,label:u.display_name}))}/></Form.Item></>}
        {active==='contact'&&<Form.Item name="contact" label="新联系方式"><Input placeholder="手机号或其他有效联系方式"/></Form.Item>}
        {active==='reject'&&<><Form.Item name="reason_code" label="不予受理标准原因" rules={[{required:true,message:'请选择标准原因'}]}><Select options={Object.entries(reasonLabels).map(([value,label])=>({value,label}))}/></Form.Item><Form.Item name="rejection_detail" label="对市民的详细说明" rules={[{required:true,message:'请填写详细说明'},{min:2}]}><Input.TextArea rows={4} maxLength={2000} showCount/></Form.Item><Form.Item name="suggested_channel" label="建议办理渠道（可选）"><Input maxLength={500} showCount/></Form.Item><Form.Item name="needs_supplement" label="需要市民补充材料" valuePropName="checked"><Switch/></Form.Item></>}
        {active==='close'&&<><Alert type="warning" showIcon message="市民尚未确认。管理员代办结必须说明依据，原因将对市民公开。" style={{marginBottom:16}}/><Form.Item name="override_reason" label="代办结原因" rules={[{required:true,message:'请填写管理员代办结原因'},{min:2}]}><Input.TextArea rows={4} maxLength={2000} showCount/></Form.Item></>}
        {active==='feedback'&&<><Alert type="info" showIcon message="满意或基本满意将直接办结；不满意将记录意见，如需重新办理请提交申诉。" style={{marginBottom:16}}/><Form.Item name="rating" label="满意度" rules={[{required:true,message:'请选择满意度'}]}><Select options={Object.entries(ratingLabels).map(([value,label])=>({value,label}))}/></Form.Item><Form.Item noStyle dependencies={['rating']}>{({getFieldValue})=><Form.Item name="comment" label={getFieldValue('rating')==='dissatisfied'?'不满意原因':'评价内容（可选）'} rules={getFieldValue('rating')==='dissatisfied'?[{required:true,message:'请说明不满意的原因'},{min:2}]:[]}><Input.TextArea rows={4} maxLength={2000} showCount/></Form.Item>}</Form.Item></>}
        {active==='pause_sla'&&<><Alert type="warning" showIcon message="暂停期间截止时间会冻结；恢复时会按实际暂停时长顺延。" style={{marginBottom:16}}/><Form.Item name="reason" label="暂停原因" rules={[{required:true,message:'请填写暂停原因'},{min:2}]}><Input.TextArea rows={3} maxLength={500} showCount/></Form.Item></>}
        {active==='resume_sla'&&<Alert type="info" showIcon message="恢复后系统会自动顺延应受理/应办结时间。" style={{marginBottom:16}}/>}
        {active==='remind'&&<Alert type="info" showIcon message="本次催办将计入次数并写入公开办理记录和审计日志。" style={{marginBottom:16}}/>}
        {active==='request_supplement'&&<><Alert type="warning" showIcon message="市民可在此工单上传附件并填写补充说明；提交后回到坐席继续受理。" style={{marginBottom:16}}/><Form.Item name="supplement_reason" label="需要补充的材料或信息" rules={[{required:true,message:'请说明需要补充的内容'},{min:2}]}><Input.TextArea rows={4} maxLength={2000} showCount/></Form.Item></>}
        {active==='submit_supplement'&&<><Alert type="info" showIcon message="如需上传文件，请先在页面的“附件材料”区域完成上传，再提交此说明。" style={{marginBottom:16}}/><Form.Item name="supplement_content" label="补充说明" rules={[{required:true,message:'请填写补充说明'},{min:2}]}><Input.TextArea rows={4} maxLength={5000} showCount/></Form.Item></>}
        {active!=='feedback'&&<Form.Item name="remark" label="操作备注" rules={[{required:true,message:'请填写操作备注'},{min:2,message:'备注至少 2 个字符'}]}><Input.TextArea rows={4} maxLength={2000} showCount placeholder="说明本次操作原因或内部处理意见"/></Form.Item>}
      </Form>
    </Modal>
  </>
}
