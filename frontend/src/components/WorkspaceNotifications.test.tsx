import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { listNotifications, streamNotifications, type NotificationStreamCallbacks } from '../api/aftercare'
import { ApiError, tokenStore } from '../api/client'
import { renderApp } from '../test/render'
import type { NotificationItem, User } from '../types'
import { WorkspaceNotifications } from './WorkspaceNotifications'

vi.mock('../api/aftercare', async () => {
  const actual = await vi.importActual<typeof import('../api/aftercare')>('../api/aftercare')
  return {
    ...actual,
    listNotifications: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 6, total: 0, unread_count: 0 }),
    streamNotifications: vi.fn(),
  }
})

const citizenUser: User = {
  id: 1,
  username: 'citizen_local',
  display_name: '测试市民',
  role: 'citizen',
  is_active: true,
}

const sampleNotification = (id: string, title: string): NotificationItem => ({
  id,
  ticket_id: 'QT2026112600000001',
  event_type: 'ticket_assigned',
  channel: 'in_app',
  title,
  content: '工单已派发至相关职能部门。',
  status: 'unread',
  delivery_status: 'delivered',
  created_at: '2026-11-26T05:00:00Z',
})

describe('WorkspaceNotifications', () => {
  afterEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.useRealTimers()
    vi.mocked(streamNotifications).mockReset()
    vi.clearAllMocks()
  })

  beforeEach(() => {
    tokenStore.set('valid-token')
    vi.mocked(listNotifications).mockResolvedValue({ items: [], page: 1, page_size: 6, total: 0, unread_count: 0 })
  })

  it('updates unread badge via SSE, suppresses initial replay toast, and toasts post-sync notifications', async () => {
    let callbacks!: NotificationStreamCallbacks
    let resolveStream!: (value: { lastEventId?: string; reason: 'eof' | 'error_event' }) => void
    vi.mocked(streamNotifications).mockImplementation(cb => {
      callbacks = cb
      return new Promise(resolve => {
        resolveStream = resolve
      })
    })

    renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))

    await act(async () => {
      callbacks.onOpen?.()
      callbacks.onUnreadCount?.(2)
      // Initial replay notification should not spam toast
      callbacks.onNotification?.(sampleNotification('n-initial', '历史未读通知'), '2026-11-26T04:50:00Z|n-initial')
    })

    expect(screen.getByRole('button', { name: '通知，2 条未读' })).toBeInTheDocument()
    expect(screen.queryByText('新通知：历史未读通知')).not.toBeInTheDocument()

    // Ping marks initial sync complete -> next notification should show toast
    await act(async () => {
      callbacks.onPing?.('2026-11-26T05:00:20Z')
      callbacks.onUnreadCount?.(3)
      callbacks.onNotification?.(sampleNotification('n-new', '工单处理完成'), '2026-11-26T05:00:21Z|n-new')
    })

    expect(screen.getByRole('button', { name: '通知，3 条未读' })).toBeInTheDocument()
    expect(await screen.findByText('新通知：工单处理完成')).toBeInTheDocument()

    await act(async () => {
      resolveStream({ lastEventId: '2026-11-26T05:00:21Z|n-new', reason: 'eof' })
    })
  })

  it('reconnects with Last-Event-ID after clean 240s EOF rotation', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let firstCallbacks!: NotificationStreamCallbacks
    vi.mocked(streamNotifications)
      .mockImplementationOnce(async cb => {
        firstCallbacks = cb
        cb.onOpen?.()
        cb.onNotification?.(sampleNotification('n-1', '首条通知'), '2026-11-26T05:00:00Z|n-1')
        return { lastEventId: '2026-11-26T05:00:00Z|n-1', reason: 'eof' as const }
      })
      .mockImplementationOnce(() => new Promise(() => {}))

    renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))
    expect(firstCallbacks.lastEventId).toBeUndefined()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_100)
    })

    expect(streamNotifications).toHaveBeenCalledTimes(2)
    expect(vi.mocked(streamNotifications).mock.calls[1][0].lastEventId).toBe('2026-11-26T05:00:00Z|n-1')
  })

  it('uses exponential backoff on stream errors and stops retrying on 401', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(streamNotifications)
      .mockRejectedValueOnce(new ApiError(503, 'STREAM_UNAVAILABLE', 'unavailable'))
      .mockRejectedValueOnce(new ApiError(401, 'AUTH_EXPIRED', 'unauthorized'))

    renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_050)
    })
    expect(streamNotifications).toHaveBeenCalledTimes(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    // Stopped cleanly after 401
    expect(streamNotifications).toHaveBeenCalledTimes(2)
  })

  it('aborts active SSE stream on unmount and on tingting:unauthorized', async () => {
    let capturedSignal: AbortSignal | undefined
    vi.mocked(streamNotifications).mockImplementation(cb => {
      capturedSignal = cb.signal
      cb.onOpen?.()
      return new Promise(() => {})
    })

    const { unmount } = renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(capturedSignal).toBeDefined())
    expect(capturedSignal?.aborted).toBe(false)

    act(() => {
      window.dispatchEvent(new Event('tingting:unauthorized'))
    })
    expect(capturedSignal?.aborted).toBe(true)

    unmount()
  })

  it('resets Last-Event-ID and seen IDs when user.id changes without unmounting', async () => {
    const secondUser: User = {
      id: 2,
      username: 'agent_local',
      display_name: '测试坐席',
      role: 'agent',
      is_active: true,
    }
    let user1Callbacks!: NotificationStreamCallbacks
    let user2Callbacks!: NotificationStreamCallbacks
    vi.mocked(streamNotifications)
      .mockImplementationOnce(cb => {
        user1Callbacks = cb
        return new Promise(() => {})
      })
      .mockImplementationOnce(cb => {
        user2Callbacks = cb
        return new Promise(() => {})
      })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const wrap = (targetUser: User) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <WorkspaceNotifications user={targetUser} />
            </MemoryRouter>
          </QueryClientProvider>
        </App>
      </ConfigProvider>
    )

    const { rerender } = render(wrap(citizenUser))
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))

    await act(async () => {
      user1Callbacks.onOpen?.()
      user1Callbacks.onUnreadCount?.(1)
      user1Callbacks.onNotification?.(sampleNotification('n-shared-or-u1', '用户1通知'), '2026-11-26T05:00:00Z|n-u1')
    })

    rerender(wrap(secondUser))
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(2))

    expect(vi.mocked(streamNotifications).mock.calls[1][0].lastEventId).toBeUndefined()

    await act(async () => {
      user2Callbacks.onOpen?.()
      user2Callbacks.onUnreadCount?.(0)
      user2Callbacks.onUnreadCount?.(1)
      user2Callbacks.onNotification?.(sampleNotification('n-shared-or-u1', '用户2新通知'), '2026-11-26T05:01:00Z|n-u2')
    })
    expect(await screen.findByText('新通知：用户2新通知')).toBeInTheDocument()
  })

  it('suppresses delayed (>50ms) initial replay notifications without ping', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let callbacks!: NotificationStreamCallbacks
    vi.mocked(streamNotifications).mockImplementationOnce(cb => {
      callbacks = cb
      return new Promise(() => {})
    })

    renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))

    await act(async () => {
      callbacks.onOpen?.()
      callbacks.onUnreadCount?.(1)
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80)
      callbacks.onNotification?.(sampleNotification('n-slow-replay', '慢速历史回放通知'), '2026-11-26T04:55:00Z|n-slow-replay')
    })

    expect(screen.getByRole('button', { name: '通知，1 条未读' })).toBeInTheDocument()
    expect(screen.queryByText('新通知：慢速历史回放通知')).not.toBeInTheDocument()
  })

  it('toasts early real-time notification arriving shortly after unread_count 0', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let callbacks!: NotificationStreamCallbacks
    vi.mocked(streamNotifications).mockImplementationOnce(cb => {
      callbacks = cb
      return new Promise(() => {})
    })

    renderApp(<MemoryRouter><WorkspaceNotifications user={citizenUser} /></MemoryRouter>)
    await waitFor(() => expect(streamNotifications).toHaveBeenCalledTimes(1))

    await act(async () => {
      callbacks.onOpen?.()
      callbacks.onUnreadCount?.(0)
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20)
      callbacks.onUnreadCount?.(1)
      callbacks.onNotification?.(sampleNotification('n-fast-live', '实时到达的新通知'), '2026-11-26T05:00:01Z|n-fast-live')
    })

    expect(screen.getByRole('button', { name: '通知，1 条未读' })).toBeInTheDocument()
    expect(await screen.findByText('新通知：实时到达的新通知')).toBeInTheDocument()
  })
})
