import { useState } from 'react'
import { Badge, Button, Card, Empty, List, Pagination, Segmented, Space, Tag, Typography } from 'antd'
import { BellOutlined, CheckOutlined, ClockCircleOutlined, LinkOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { listNotificationChannels, listNotifications, notificationKeys, readAllNotifications, readNotification } from '../api/aftercare'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/PageHeader'
import { ErrorState } from '../components/ErrorState'

const eventColors:Record<string,string>={ticket_created:'cyan',ticket_accepted:'blue',supplement_required:'orange',ticket_assigned:'geekblue',ticket_due_soon:'red',processing_completed:'green',awaiting_confirmation:'gold',ticket_closed:'default',appeal_submitted:'purple',appeal_approved:'green',appeal_rejected:'red',appeal_completed:'cyan',appeal_prompt:'orange'}
const eventLabels:Record<string,string>={ticket_created:'创建',ticket_accepted:'受理',supplement_required:'补充材料',ticket_assigned:'派发',ticket_due_soon:'时限提醒',processing_completed:'处理完成',awaiting_confirmation:'待确认',ticket_closed:'办结',appeal_submitted:'新申诉',appeal_approved:'申诉通过',appeal_rejected:'申诉结果',appeal_completed:'重办完成',appeal_prompt:'申诉提示'}

export function NotificationsPage(){
  const {user}=useAuth();const nav=useNavigate();const qc=useQueryClient();const [unreadOnly,setUnreadOnly]=useState(false);const [page,setPage]=useState(1)
  const query=useQuery({queryKey:[...notificationKeys.list(unreadOnly),page],queryFn:()=>listNotifications(unreadOnly,page,20),refetchInterval:30_000})
  const channels=useQuery({queryKey:['notifications','channels'],queryFn:listNotificationChannels})
  const readOne=useMutation({mutationFn:readNotification,onSuccess:()=>qc.invalidateQueries({queryKey:notificationKeys.all})})
  const readAll=useMutation({mutationFn:readAllNotifications,onSuccess:()=>qc.invalidateQueries({queryKey:notificationKeys.all})})
  const ticketPath=(id:string)=>`/${user?.role==='department_staff'?'department':user?.role}/tickets/${id}`
  return <div className="notification-page"><PageHeader eyebrow="MESSAGE HUB" title="通知中心" description="集中查看工单进度、时限提醒和申诉结果。" extra={<Space><Badge count={query.data?.unread_count||0} overflowCount={99}/><Button icon={<CheckOutlined/>} disabled={!query.data?.unread_count} loading={readAll.isPending} onClick={()=>readAll.mutate()}>全部已读</Button></Space>}/>
    <div className="notification-toolbar surface"><Segmented aria-label="通知范围" value={unreadOnly?'unread':'all'} options={[{label:'全部通知',value:'all'},{label:'仅未读',value:'unread'}]} onChange={value=>{setUnreadOnly(value==='unread');setPage(1)}}/><Space wrap>{channels.data?.map(channel=><Tag key={channel.channel} color={channel.enabled?'green':'default'}>{channel.label} · {channel.enabled?'已启用':'已预留'}</Tag>)}</Space></div>
    {query.isError?<ErrorState error={query.error} retry={()=>{void query.refetch()}}/>:<Card className="surface notification-list" loading={query.isLoading}><List dataSource={query.data?.items||[]} locale={{emptyText:<Empty description="暂无通知"/>}} renderItem={item=><List.Item className={item.status==='unread'?'notification-unread':''} actions={[item.ticket_id?<Button key="ticket" type="link" icon={<LinkOutlined/>} onClick={()=>{if(item.status==='unread')readOne.mutate(item.id);nav(ticketPath(item.ticket_id!))}}>查看工单</Button>:null,item.status==='unread'?<Button key="read" type="text" onClick={()=>readOne.mutate(item.id)}>标为已读</Button>:null].filter(Boolean)}><List.Item.Meta avatar={<div className="notification-icon"><BellOutlined/></div>} title={<Space wrap><Typography.Text strong={item.status==='unread'}>{item.title}</Typography.Text><Tag color={eventColors[item.event_type]}>{eventLabels[item.event_type]||item.event_type}</Tag>{item.status==='unread'&&<Badge status="processing" text="未读"/>}</Space>} description={<div><Typography.Paragraph>{item.content}</Typography.Paragraph><Typography.Text type="secondary"><ClockCircleOutlined/> {dayjs(item.created_at).format('YYYY-MM-DD HH:mm')}</Typography.Text></div>}/></List.Item>}/>{(query.data?.total||0)>20&&<Pagination current={page} pageSize={20} total={query.data?.total} showSizeChanger={false} onChange={setPage}/>}</Card>}
  </div>
}
