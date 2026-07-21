import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { renderApp } from '../test/render'
import { WorkOrderPanel } from './WorkOrderPanel'
import type { TicketDetail, User } from '../types'

const startWorkOrder = vi.fn()
const onChanged = vi.fn()

vi.mock('../api/admin', () => ({
  listDepartments: vi.fn().mockResolvedValue([{ id: 1, name: '市政', is_active: true }]),
  listDepartmentStaff: vi.fn().mockResolvedValue([]),
}))

vi.mock('../api/tickets', async () => {
  const actual = await vi.importActual<typeof import('../api/tickets')>('../api/tickets')
  return {
    ...actual,
    startWorkOrder: (...args: unknown[]) => startWorkOrder(...args),
    createWorkOrder: vi.fn(),
    assignWorkOrder: vi.fn(),
    returnWorkOrder: vi.fn(),
    transferWorkOrder: vi.fn(),
    submitWorkOrderResult: vi.fn(),
    summarizeTicket: vi.fn(),
    reviewResolveTicket: vi.fn(),
    returnTicketToDepartment: vi.fn(),
    openTicketDispute: vi.fn(),
    resolveTicketDispute: vi.fn(),
  }
})

const staff: User = {
  id: 3, username: 'staff', display_name: '部门员', role: 'department_staff',
  department_id: 1, is_active: true,
} as User

const ticket = {
  ticket_id: 'QT2026072200000001',
  version: 4,
  status: 'processing',
  collaboration_status: 'in_progress',
  work_orders: [{
    id: 'wo-1',
    work_order_no: 'QT2026072200000001-M-1',
    ticket_id: 'QT2026072200000001',
    task_type: 'primary',
    status: 'pending',
    department_id: 1,
    department_name: '市政',
    assignee_user_id: 3,
    assignee_name: '部门员',
    instructions: '尽快处理',
    version: 1,
    updated_at: new Date().toISOString(),
    history: [],
  }],
} as unknown as TicketDetail

describe('WorkOrderPanel 409', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('warns and refreshes on VERSION_CONFLICT', async () => {
    startWorkOrder.mockRejectedValueOnce(new ApiError(409, 'VERSION_CONFLICT', '工单数据已被其他操作更新'))
    renderApp(<WorkOrderPanel ticket={ticket} user={staff} onChanged={onChanged} />)
    await userEvent.click(screen.getByRole('button', { name: '开始办理' }))
    await userEvent.type(screen.getByLabelText('操作说明'), '开始处理')
    await userEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await vi.waitFor(() => expect(startWorkOrder).toHaveBeenCalled())
    expect(onChanged).toHaveBeenCalled()
  })
})
