import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exportAuditLogsCsv, getAuditLogs } from '../api/admin'
import { ApiError } from '../api/client'
import { renderApp } from '../test/render'
import { AuditPage } from './AuditPage'

vi.mock('../api/admin', async () => {
  const actual = await vi.importActual<typeof import('../api/admin')>('../api/admin')
  return {
    ...actual,
    getAuditLogs: vi.fn().mockResolvedValue({
      items: [{
        id: 1,
        actor_user_id: 4,
        actor_type: 'user',
        action: 'tickets.batch_assign',
        resource_type: 'ticket',
        resource_id: 'QT2026112600000001',
        outcome: 'success',
        details: 'ok',
        request_id: 'req-1',
        created_at: '2026-11-26T05:00:00Z',
      }],
      page: 1,
      page_size: 20,
      total: 1,
    }),
    exportAuditLogsCsv: vi.fn().mockResolvedValue(undefined),
  }
})

describe('AuditPage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders audit logs and searches by action', async () => {
    const user = userEvent.setup()
    renderApp(<AuditPage />)
    expect(await screen.findByText('tickets.batch_assign')).toBeInTheDocument()

    const search = screen.getByLabelText('按动作精确查询')
    await user.type(search, 'login{enter}')
    await waitFor(() => expect(getAuditLogs).toHaveBeenCalledWith(1, 20, 'login'))
  })

  it('exports audit logs CSV preserving active action filter', async () => {
    const user = userEvent.setup()
    renderApp(<AuditPage />)
    await screen.findByText('tickets.batch_assign')

    await user.type(screen.getByLabelText('按动作精确查询'), 'auth.register{enter}')
    await waitFor(() => expect(getAuditLogs).toHaveBeenCalledWith(1, 20, 'auth.register'))

    await user.click(screen.getByRole('button', { name: /导出 CSV/ }))
    await waitFor(() => expect(exportAuditLogsCsv).toHaveBeenCalledWith({ action: 'auth.register' }))
    expect(await screen.findByText('审计日志 CSV 已开始下载')).toBeInTheDocument()
  })

  it('surfaces 429 rate-limit error on audit CSV export', async () => {
    vi.mocked(exportAuditLogsCsv).mockRejectedValueOnce(
      new ApiError(429, 'EXPORT_RATE_LIMITED', '导出请求过于频繁，请稍后重试', { retry_after: 18 }),
    )
    const user = userEvent.setup()
    renderApp(<AuditPage />)
    await screen.findByText('tickets.batch_assign')

    await user.click(screen.getByRole('button', { name: /导出 CSV/ }))
    expect(await screen.findByText('导出请求过于频繁，请稍后重试（约 18 秒后可重试）')).toBeInTheDocument()
  })
})
