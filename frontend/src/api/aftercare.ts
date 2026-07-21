import { api } from './client'
import { getTicket } from './tickets'
import type { ApiSuccess, Appeal, AppealPage, FollowUpPage, FollowUpTask, NotificationChannel, NotificationItem, NotificationPage } from '../types'

export const notificationKeys={all:['notifications'] as const,list:(unreadOnly=false)=>['notifications','list',unreadOnly] as const}
export async function listNotifications(unreadOnly=false,page=1,pageSize=20){return (await api.get<ApiSuccess<NotificationPage>>('/notifications',{params:{unread_only:unreadOnly,page,page_size:pageSize}})).data.data}
export async function readNotification(id:string){return (await api.post<ApiSuccess<NotificationItem>>(`/notifications/${id}/read`)).data.data}
export async function readAllNotifications(){return (await api.post<ApiSuccess<{read_count:number}>>('/notifications/read-all')).data.data}
export async function listNotificationChannels(){return (await api.get<ApiSuccess<NotificationChannel[]>>('/notifications/channels')).data.data}

export const aftercareKeys={appeals:['aftercare','appeals'] as const,followups:['aftercare','followups'] as const}
export async function listAppeals(status?:string){return (await api.get<ApiSuccess<AppealPage>>('/appeals',{params:{status,page:1,page_size:100}})).data.data}
export async function createAppeal(ticketId:string,payload:{reason:string;desired_resolution:string}){return (await api.post<ApiSuccess<Appeal>>(`/tickets/${ticketId}/appeals`,payload)).data.data}
export async function reviewAppeal(id:string,payload:{decision:'approved'|'rejected';review_comment:string;reprocess_instructions?:string}){return (await api.post<ApiSuccess<Appeal>>(`/appeals/${id}/review`,payload)).data.data}
export async function listFollowUps(status?:string){return (await api.get<ApiSuccess<FollowUpPage>>('/follow-ups',{params:{status,page:1,page_size:100}})).data.data}
export async function recordPhoneFollowUp(task:FollowUpTask,payload:{contact_result:string;satisfaction?:string;outcome:string;notes:string}){const ticket=await getTicket(task.ticket_id);return (await api.post<ApiSuccess<FollowUpTask>>(`/follow-ups/${task.id}/phone-record`,{...payload,ticket_version:ticket.version})).data.data}
