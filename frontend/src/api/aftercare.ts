import { api } from './client'
import { consumeSseStream, openSseFetch } from './sse'
import { getTicket } from './tickets'
import type { ApiSuccess, Appeal, AppealPage, FollowUpPage, FollowUpTask, NotificationChannel, NotificationItem, NotificationPage } from '../types'

export const notificationKeys={all:['notifications'] as const,list:(unreadOnly=false)=>['notifications','list',unreadOnly] as const}
export async function listNotifications(unreadOnly=false,page=1,pageSize=20){return (await api.get<ApiSuccess<NotificationPage>>('/notifications',{params:{unread_only:unreadOnly,page,page_size:pageSize}})).data.data}
export async function readNotification(id:string){return (await api.post<ApiSuccess<NotificationItem>>(`/notifications/${id}/read`)).data.data}
export async function readAllNotifications(){return (await api.post<ApiSuccess<{read_count:number}>>('/notifications/read-all')).data.data}
export async function listNotificationChannels(){return (await api.get<ApiSuccess<NotificationChannel[]>>('/notifications/channels')).data.data}

export interface NotificationStreamCallbacks {
  lastEventId?: string
  signal?: AbortSignal
  onOpen?: () => void
  onUnreadCount?: (count: number) => void
  onNotification?: (item: NotificationItem, eventId?: string) => void
  onPing?: (ts: string) => void
  onStreamError?: (err: { code: string; message: string }) => void
}

export async function streamNotifications(
  callbacks: NotificationStreamCallbacks,
): Promise<{ lastEventId?: string; reason: 'eof' | 'error_event' }> {
  const { lastEventId, signal, onOpen, onUnreadCount, onNotification, onPing, onStreamError } = callbacks
  const response = await openSseFetch('/api/v1/notifications/stream', {
    method: 'GET',
    headers: lastEventId ? { 'Last-Event-ID': lastEventId } : undefined,
    signal,
    clearAuthOn401: true,
  })
  if (!response.body) {
    return { lastEventId, reason: 'eof' }
  }
  onOpen?.()
  let latestEventId = lastEventId
  let reason: 'eof' | 'error_event' = 'eof'
  await consumeSseStream(
    response.body,
    ev => {
      if (ev.id) latestEventId = ev.id
      if (!ev.data) return
      try {
        const parsed = JSON.parse(ev.data) as Record<string, unknown>
        if (ev.event === 'unread_count' && typeof parsed.unread_count === 'number') {
          onUnreadCount?.(parsed.unread_count)
        } else if (ev.event === 'notification') {
          onNotification?.(parsed as unknown as NotificationItem, ev.id)
        } else if (ev.event === 'ping' && typeof parsed.ts === 'string') {
          onPing?.(parsed.ts)
        } else if (ev.event === 'error') {
          reason = 'error_event'
          onStreamError?.({
            code: typeof parsed.code === 'string' ? parsed.code : 'STREAM_UNAVAILABLE',
            message: typeof parsed.message === 'string' ? parsed.message : '通知流暂时不可用，请回退轮询',
          })
        }
      } catch {
        // Ignore malformed SSE payload frames.
      }
    },
    signal,
  )
  return { lastEventId: latestEventId, reason }
}

export const aftercareKeys={appeals:['aftercare','appeals'] as const,followups:['aftercare','followups'] as const}
export async function listAppeals(status?:string){return (await api.get<ApiSuccess<AppealPage>>('/appeals',{params:{status,page:1,page_size:100}})).data.data}
export async function createAppeal(ticketId:string,payload:{reason:string;desired_resolution:string}){return (await api.post<ApiSuccess<Appeal>>(`/tickets/${ticketId}/appeals`,payload)).data.data}
export async function reviewAppeal(id:string,payload:{decision:'approved'|'rejected';review_comment:string;reprocess_instructions?:string}){return (await api.post<ApiSuccess<Appeal>>(`/appeals/${id}/review`,payload)).data.data}
export async function listFollowUps(status?:string){return (await api.get<ApiSuccess<FollowUpPage>>('/follow-ups',{params:{status,page:1,page_size:100}})).data.data}
export async function recordPhoneFollowUp(task:FollowUpTask,payload:{contact_result:string;satisfaction?:string;outcome:string;notes:string}){const ticket=await getTicket(task.ticket_id);return (await api.post<ApiSuccess<FollowUpTask>>(`/follow-ups/${task.id}/phone-record`,{...payload,ticket_version:ticket.version})).data.data}
