import { BellOutlined } from '@ant-design/icons'
import { App, Badge, Button, Drawer, Empty, List, Space, Typography } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { listNotifications, notificationKeys, readNotification, streamNotifications } from '../api/aftercare'
import { ApiError, tokenStore } from '../api/client'
import type { NotificationPage, User } from '../types'
import { WorkspaceError, WorkspaceLoading } from './WorkspaceState'

export function WorkspaceNotifications({ user }: { user: User }) {
  const [open, setOpen] = useState(false)
  const [sseConnected, setSseConnected] = useState(false)
  const { message } = App.useApp()
  const client = useQueryClient()
  const drawerKey = useMemo(() => [...notificationKeys.list(false), 'drawer', user.id] as const, [user.id])
  const recent = useQuery({
    queryKey: drawerKey,
    queryFn: () => listNotifications(false, 1, 6),
    refetchInterval: sseConnected ? false : 30_000,
  })
  const markRead = useMutation({
    mutationFn: readNotification,
    onSuccess: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  })
  const lastEventIdRef = useRef<string | undefined>(undefined)
  const seenIdsRef = useRef<Set<string>>(new Set())
  const unreadCountRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    lastEventIdRef.current = undefined
    seenIdsRef.current.clear()
    unreadCountRef.current = undefined
    setSseConnected(false)

    if (!tokenStore.get()) {
      return
    }
    let disposed = false
    let attempt = 0
    let reconnectTimer: number | undefined
    let replayTimer: number | undefined
    let activeController: AbortController | null = null

    const clearReplayTimer = () => {
      if (replayTimer !== undefined) {
        window.clearTimeout(replayTimer)
        replayTimer = undefined
      }
    }

    const clearTimers = () => {
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = undefined
      }
      clearReplayTimer()
    }

    const scheduleReconnect = (delayMs: number) => {
      if (disposed) return
      clearTimers()
      reconnectTimer = window.setTimeout(() => {
        if (!disposed) void connect()
      }, delayMs)
    }

    const connect = async () => {
      if (disposed || !tokenStore.get()) return
      const controller = new AbortController()
      activeController = controller
      const isInitialConnect = !lastEventIdRef.current
      let seenFirstUnreadCount = false
      let initialReplayRemaining = 0

      const clearInitialReplay = () => {
        initialReplayRemaining = 0
        seenFirstUnreadCount = true
        clearReplayTimer()
      }

      const armReplayFallbackTimer = () => {
        if (replayTimer !== undefined) return
        replayTimer = window.setTimeout(() => {
          clearInitialReplay()
        }, 2_000)
      }

      try {
        const result = await streamNotifications({
          lastEventId: lastEventIdRef.current,
          signal: controller.signal,
          onOpen: () => {
            if (disposed || controller.signal.aborted) return
            attempt = 0
            setSseConnected(true)
            if (isInitialConnect) {
              armReplayFallbackTimer()
            }
          },
          onUnreadCount: count => {
            if (disposed || controller.signal.aborted) return
            if (isInitialConnect) {
              if (!seenFirstUnreadCount) {
                seenFirstUnreadCount = true
                if (count <= 0) {
                  clearInitialReplay()
                } else {
                  initialReplayRemaining = Math.min(count, 50)
                  armReplayFallbackTimer()
                }
              } else {
                clearInitialReplay()
              }
            }
            client.setQueryData<NotificationPage>(drawerKey, prev => (
              prev
                ? { ...prev, unread_count: count }
                : { items: [], page: 1, page_size: 6, total: count, unread_count: count }
            ))
            if (unreadCountRef.current !== undefined && unreadCountRef.current !== count) {
              void client.invalidateQueries({
                queryKey: notificationKeys.all,
                predicate: query => !query.queryKey.includes('drawer'),
              })
            }
            unreadCountRef.current = count
          },
          onNotification: (item, eventId) => {
            if (disposed || controller.signal.aborted) return
            if (eventId) lastEventIdRef.current = eventId
            const isInitialReplay = initialReplayRemaining > 0
            if (isInitialReplay) {
              initialReplayRemaining -= 1
              if (initialReplayRemaining === 0) {
                clearInitialReplay()
              }
            }
            const isNew = !seenIdsRef.current.has(item.id)
            seenIdsRef.current.add(item.id)
            client.setQueryData<NotificationPage>(drawerKey, prev => {
              const existing = prev?.items ?? []
              const deduped = [item, ...existing.filter(entry => entry.id !== item.id)].slice(0, 6)
              return {
                items: deduped,
                page: 1,
                page_size: 6,
                total: Math.max(prev?.total ?? 0, deduped.length),
                unread_count: prev?.unread_count ?? unreadCountRef.current ?? (item.status === 'unread' ? 1 : 0),
              }
            })
            void client.invalidateQueries({
              queryKey: notificationKeys.all,
              predicate: query => !query.queryKey.includes('drawer'),
            })
            if (isNew && !isInitialReplay) {
              message.info(`新通知：${item.title}`)
            }
          },
          onPing: () => {
            clearInitialReplay()
          },
          onStreamError: () => {
            if (!disposed) setSseConnected(false)
          },
        })

        if (result.lastEventId) lastEventIdRef.current = result.lastEventId
        if (disposed || controller.signal.aborted) return
        setSseConnected(false)
        if (result.reason === 'eof') {
          attempt = 0
          scheduleReconnect(1_000)
        } else {
          const delay = Math.min(30_000, 1_000 * (2 ** Math.min(attempt, 5)))
          attempt += 1
          scheduleReconnect(delay)
        }
      } catch (err) {
        if (disposed || controller.signal.aborted) return
        setSseConnected(false)
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          disposed = true
          clearTimers()
          return
        }
        const delay = Math.min(30_000, 1_000 * (2 ** Math.min(attempt, 5)))
        attempt += 1
        scheduleReconnect(delay)
      }
    }

    const handleUnauthorized = () => {
      disposed = true
      clearTimers()
      activeController?.abort()
      activeController = null
      setSseConnected(false)
    }
    window.addEventListener('tingting:unauthorized', handleUnauthorized)
    void connect()

    return () => {
      disposed = true
      clearTimers()
      activeController?.abort()
      activeController = null
      lastEventIdRef.current = undefined
      seenIdsRef.current.clear()
      unreadCountRef.current = undefined
      setSseConnected(false)
      window.removeEventListener('tingting:unauthorized', handleUnauthorized)
    }
  }, [client, drawerKey, message, user.id])

  useEffect(() => {
    if (!recent.data) return
    unreadCountRef.current = recent.data.unread_count
    for (const item of recent.data.items) {
      seenIdsRef.current.add(item.id)
    }
  }, [recent.data, user.id])

  const rolePath = user.role === 'department_staff' ? 'department' : user.role
  const unread = recent.data?.unread_count ?? 0

  return <>
    <Button type="text" aria-label={unread ? `通知，${unread} 条未读` : '打开通知'} onClick={() => setOpen(true)}
      icon={<Badge count={unread} overflowCount={99}><BellOutlined aria-hidden /></Badge>} />
    <Drawer title="最近通知" open={open} onClose={() => setOpen(false)} size="min(420px, 100vw)"
      extra={<Link to={`/${rolePath}/notifications`} onClick={() => setOpen(false)}>查看全部通知</Link>}>
      {recent.isLoading && <WorkspaceLoading label="正在加载通知" />}
      {recent.isError && <WorkspaceError error={recent.error} retry={() => void recent.refetch()} fallback="通知暂时无法加载" />}
      {markRead.isError && <WorkspaceError error={markRead.error} fallback="未能标为已读，请重试" />}
      {recent.data && <List dataSource={recent.data.items}
        locale={{ emptyText: <Empty description="暂无通知" /> }}
        renderItem={item => <List.Item className="workspace-notification-item">
          <List.Item.Meta title={<Space wrap>{item.title}{item.status === 'unread' && <Badge status="processing" text="未读" />}</Space>}
            description={<Typography.Paragraph ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}>{item.content}</Typography.Paragraph>} />
          <Space wrap>
            {item.ticket_id && <Link to={`/${rolePath}/tickets/${item.ticket_id}`} onClick={() => setOpen(false)}>查看工单</Link>}
            {item.status === 'unread' && <Button size="small" type="text" disabled={markRead.isPending}
              loading={markRead.isPending && markRead.variables === item.id} onClick={() => markRead.mutate(item.id)}>标为已读</Button>}
          </Space>
        </List.Item>} />}
    </Drawer>
  </>
}
