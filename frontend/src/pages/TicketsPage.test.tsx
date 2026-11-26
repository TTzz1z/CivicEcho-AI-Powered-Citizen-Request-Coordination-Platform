import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { listDepartmentStaff, listDepartments } from '../api/admin'
import { ApiError } from '../api/client'
import { batchAssignTickets, exportTicketsCsv, listTickets } from '../api/tickets'
import { renderApp } from '../test/render'
import type { Role, Ticket } from '../types'
import { TicketsPage } from './TicketsPage'

const authState = vi.hoisted(() => ({
  user: { id: 2, role: 'agent' as Role, display_name: '坐席' },
}))

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: authState.user }) }))

vi.mock('../api/admin', async () => {
  const actual = await vi.importActual<typeof import('../api/admin')>('../api/admin')
  return {
    ...actual,
    listCategories: vi.fn().mockResolvedValue([]),
    listDepartments: vi.fn().mockResolvedValue([
      { id: 10, code: 'URBAN', name: '城管局', is_active: true },
      { id: 20, code: 'WATER', name: '水务局', is_active: true },
    ]),
    listDepartmentStaff: vi.fn().mockImplementation(async (deptId: number) => (
      deptId === 10
        ? [{ id: 101, username: 'staff_urban', display_name: '城管专员', role: 'department_staff', department_id: 10, is_active: true }]
        : [{ id: 201, username: 'staff_water', display_name: '水务专员', role: 'department_staff', department_id: 20, is_active: true }]
    )),
  }
})

vi.mock('../api/tickets', async () => {
  const actual = await vi.importActual<typeof import('../api/tickets')>('../api/tickets')
  return {
    ...actual,
    listTickets: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 }),
    batchAssignTickets: vi.fn(),
    exportTicketsCsv: vi.fn().mockResolvedValue(undefined),
  }
})

function makeTicket(id: string, status: Ticket['status'] = 'accepted', version = 1): Ticket {
  return {
    ticket_id: id,
    request_type: '投诉',
    description: `测试诉求 ${id}`,
    location: '人民路',
    timezone: 'Asia/Shanghai',
    priority: 'normal',
    status,
    source: 'web',
    version,
    created_at: '2026-11-26T02:00:00Z',
    updated_at: '2026-11-26T02:00:00Z',
    needs_supplement: false,
    is_overdue: false,
    sla_state: 'on_track',
    total_paused_seconds: 0,
    reminder_count: 0,
    collaboration_status: 'none',
    handling_round: 1,
    appeal_count: 0,
  }
}

describe('TicketsPage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    authState.user = { id: 2, role: 'agent', display_name: '坐席' }
    vi.clearAllMocks()
    vi.mocked(listTickets).mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 })
  })

  it('restores filters from the URL and sends them to backend', async () => {
    renderApp(<MemoryRouter initialEntries={['/agent/tickets?status=pending&keyword=%E8%B7%AF%E7%81%AF']}><TicketsPage /></MemoryRouter>)
    await waitFor(() => expect(listTickets).toHaveBeenCalledWith(expect.objectContaining({ status: 'pending', keyword: '路灯' })))
    expect(screen.getByText('当前条件下暂无工单')).toBeInTheDocument()
  })

  it('hides batch-assign checkboxes for citizen and department_staff', async () => {
    vi.mocked(listTickets).mockResolvedValue({
      items: [makeTicket('QT2026112600000001')],
      page: 1,
      page_size: 20,
      total: 1,
    })

    authState.user = { id: 1, role: 'citizen', display_name: '市民' }
    const { unmount } = renderApp(<MemoryRouter initialEntries={['/citizen/tickets']}><TicketsPage /></MemoryRouter>)
    await screen.findByText('QT2026112600000001')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    unmount()

    authState.user = { id: 3, role: 'department_staff', display_name: '部门专员' }
    renderApp(<MemoryRouter initialEntries={['/department/tickets']}><TicketsPage /></MemoryRouter>)
    await screen.findByText('QT2026112600000001')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('allows agent to batch-assign selected tickets with versions map and renders per-ticket result modal', async () => {
    vi.mocked(listTickets).mockResolvedValue({
      items: [
        makeTicket('QT2026112600000001', 'accepted', 2),
        makeTicket('QT2026112600000002', 'pending', 1),
      ],
      page: 1,
      page_size: 20,
      total: 2,
    })
    vi.mocked(batchAssignTickets).mockResolvedValue({
      succeeded: [{ ticket_id: 'QT2026112600000001', status: 'assigned', version: 3, work_order_no: 'WO-001' }],
      failed: [{ ticket_id: 'QT2026112600000002', code: 'INVALID_STATUS_TRANSITION', message: '仅已受理状态的工单可派发' }],
    })

    const user = userEvent.setup({ delay: null })
    renderApp(<MemoryRouter initialEntries={['/agent/tickets']}><TicketsPage /></MemoryRouter>)
    await screen.findByText('QT2026112600000001')

    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[0]) // select all

    const bar = await screen.findByRole('region', { name: '批量派发操作栏' })
    expect(within(bar).getByText('已选 2 条')).toBeInTheDocument()
    await user.click(within(bar).getByRole('button', { name: /批量派发/ }))

    const modal = await screen.findByRole('dialog', { name: /批量派发/ })
    await waitFor(() => expect(listDepartments).toHaveBeenCalled())

    await user.click(within(modal).getByRole('combobox', { name: '责任部门' }))
    await user.click(await screen.findByText('水务局'))
    await waitFor(() => expect(listDepartmentStaff).toHaveBeenCalledWith(20))

    fireEvent.change(within(modal).getByLabelText('派发备注（可选）'), { target: { value: '加急联合处置' } })
    await user.click(within(modal).getByRole('button', { name: /确认派发/ }))

    await waitFor(() => expect(batchAssignTickets).toHaveBeenCalledWith({
      ticket_ids: ['QT2026112600000001', 'QT2026112600000002'],
      department_id: 20,
      assigned_user_id: undefined,
      note: '加急联合处置',
      versions: {
        QT2026112600000001: 2,
        QT2026112600000002: 1,
      },
    }))

    const resultModal = await screen.findByRole('dialog', { name: '批量派发结果' })
    expect(within(resultModal).getByText('成功 1 条，失败 1 条')).toBeInTheDocument()
    expect(within(resultModal).getByText('WO-001')).toBeInTheDocument()
    expect(within(resultModal).getByText('INVALID_STATUS_TRANSITION')).toBeInTheDocument()
    expect(within(resultModal).getByText('仅已受理状态的工单可派发')).toBeInTheDocument()
  })

  it('clears selected assignee when batch-assign department changes', async () => {
    vi.mocked(listTickets).mockResolvedValue({
      items: [makeTicket('QT2026112600000001', 'accepted', 2)],
      page: 1,
      page_size: 20,
      total: 1,
    })
    vi.mocked(batchAssignTickets).mockResolvedValue({
      succeeded: [{ ticket_id: 'QT2026112600000001', status: 'assigned', version: 3, work_order_no: 'WO-001' }],
      failed: [],
    })

    renderApp(<MemoryRouter initialEntries={['/agent/tickets']}><TicketsPage /></MemoryRouter>)
    await screen.findByText('QT2026112600000001')

    fireEvent.click(screen.getAllByRole('checkbox')[0])
    const bar = await screen.findByRole('region', { name: '批量派发操作栏' })
    fireEvent.click(within(bar).getByRole('button', { name: /批量派发/ }))

    const modal = await screen.findByRole('dialog', { name: /批量派发/ })
    fireEvent.mouseDown(within(modal).getByRole('combobox', { name: '责任部门' }))
    fireEvent.click(await screen.findByText('城管局'))
    await waitFor(() => expect(listDepartmentStaff).toHaveBeenCalledWith(10))

    fireEvent.mouseDown(within(modal).getByRole('combobox', { name: '承办人（可选）' }))
    fireEvent.click(await screen.findByText('城管专员'))

    fireEvent.mouseDown(within(modal).getByRole('combobox', { name: '责任部门' }))
    fireEvent.click(await screen.findByText('水务局'))
    await waitFor(() => expect(listDepartmentStaff).toHaveBeenCalledWith(20))

    fireEvent.click(within(modal).getByRole('button', { name: /确认派发/ }))
    await waitFor(() => expect(batchAssignTickets).toHaveBeenCalledWith(expect.objectContaining({
      department_id: 20,
      assigned_user_id: undefined,
    })))
  })

  it('blocks batch assign when more than 50 tickets are selected', async () => {
    const fiftyOne = Array.from({ length: 51 }, (_, idx) => makeTicket(`QT20261126000000${String(idx + 1).padStart(2, '0')}`))
    vi.mocked(listTickets).mockResolvedValue({ items: fiftyOne, page: 1, page_size: 100, total: 51 })

    const { container } = renderApp(<MemoryRouter initialEntries={['/agent/tickets?page_size=100']}><TicketsPage /></MemoryRouter>)
    await screen.findByText('QT2026112600000001')

    const selectAllCheckbox = container.querySelector('.ant-table-thead input[type="checkbox"]') as HTMLInputElement
    fireEvent.click(selectAllCheckbox)
    const bar = await screen.findByRole('region', { name: '批量派发操作栏' })
    expect(within(bar).getByText('已选 51 条')).toBeInTheDocument()
    expect(within(bar).getByText('单次最多批量派发 50 条工单')).toBeInTheDocument()
    expect(within(bar).getByRole('button', { name: /批量派发/ })).toBeDisabled()
  })

  it('exports tickets CSV with active filters and strips pagination', async () => {
    const user = userEvent.setup()
    renderApp(<MemoryRouter initialEntries={['/agent/tickets?page=2&page_size=20&status=accepted&keyword=%E7%A7%AF%E6%B0%B4']}><TicketsPage /></MemoryRouter>)
    await waitFor(() => expect(listTickets).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: /导出 CSV/ }))
    await waitFor(() => expect(exportTicketsCsv).toHaveBeenCalledWith(expect.objectContaining({
      status: 'accepted',
      keyword: '积水',
    })))
    expect(await screen.findByText('工单 CSV 已开始下载')).toBeInTheDocument()
  })

  it('surfaces 429 rate limit retry_after on ticket CSV export', async () => {
    vi.mocked(exportTicketsCsv).mockRejectedValueOnce(
      new ApiError(429, 'EXPORT_RATE_LIMITED', '导出请求过于频繁，请稍后重试', { retry_after: 30 }),
    )
    const user = userEvent.setup()
    renderApp(<MemoryRouter initialEntries={['/agent/tickets']}><TicketsPage /></MemoryRouter>)
    await waitFor(() => expect(listTickets).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: /导出 CSV/ }))
    expect(await screen.findByText('导出请求过于频繁，请稍后重试（约 30 秒后可重试）')).toBeInTheDocument()
  })
})
