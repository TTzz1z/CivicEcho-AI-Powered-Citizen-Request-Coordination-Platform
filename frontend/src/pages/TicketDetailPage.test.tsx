import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { getTicket } from '../api/tickets'
import { renderApp } from '../test/render'
import type { TicketDetail } from '../types'
import { closureTypeLabel } from '../utils/closureType'
import { allowedActions, TicketDetailPage } from './TicketDetailPage'

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 12,
      username: 'agent_local',
      display_name: '演示坐席',
      role: 'agent' as const,
      is_active: true,
    },
  }),
}))

vi.mock('../api/tickets', () => ({
  acceptTicket: vi.fn(),
  assignTicket: vi.fn(),
  closeTicket: vi.fn(),
  getTicket: vi.fn(),
  pauseTicketSla: vi.fn(),
  rejectTicket: vi.fn(),
  remindTicket: vi.fn(),
  requestTicketSupplement: vi.fn(),
  resumeTicketSla: vi.fn(),
  submitTicketFeedback: vi.fn(),
  submitTicketSupplement: vi.fn(),
  ticketAction: vi.fn(),
  ticketKeys: {
    all: ['tickets'],
    detail: (id: string) => ['tickets', id],
  },
  updateContact: vi.fn(),
}))

vi.mock('../api/admin', () => ({
  listCategories: vi.fn().mockResolvedValue([]),
  listDepartments: vi.fn().mockResolvedValue([]),
  listUsers: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 }),
  listDepartmentStaff: vi.fn().mockResolvedValue([]),
}))

vi.mock('../components/AttachmentPanel', () => ({
  AttachmentPanel: () => <div>附件列表占位</div>,
}))

vi.mock('../components/AiCaseAssistant', () => ({
  AiCaseAssistant: () => <div>AI 建议占位</div>,
}))

const mockedGetTicket = vi.mocked(getTicket)

const sampleTicket: TicketDetail = {
  ticket_id: 'T-2026-1125-001',
  request_type: '市政设施',
  description: '建设路与青年路交叉口路灯连续三晚未亮，影响行人夜间通行安全。',
  location: '高新区建设路与青年路交叉口',
  timezone: 'Asia/Shanghai',
  priority: 'expedited',
  status: 'resolved',
  status_label: '已解决待确认',
  department_name: '城市照明管理中心',
  assigned_department_id: 3,
  creator_name: '林市民',
  assignee_name: '王照明',
  source: 'web_chat',
  version: 4,
  created_at: '2026-11-24T09:00:00Z',
  updated_at: '2026-11-25T10:30:00Z',
  accepted_at: '2026-11-24T09:20:00Z',
  resolved_at: '2026-11-25T10:25:00Z',
  is_overdue: false,
  sla_state: 'on_track',
  total_paused_seconds: 0,
  reminder_count: 0,
  collaboration_status: 'completed',
  handling_round: 1,
  appeal_count: 0,
  needs_supplement: false,
  resolution_summary: '已完成路口主电缆接头检修并恢复照明',
  resolution_measures: '1. 现场排查电缆井故障；2. 更换受损防水接线盒；3. 夜间亮灯复测正常。',
  resolution_outcome: 'resolved',
  public_reply: '您好，建设路与青年路交叉口路灯供电故障已于昨晚修复并恢复正常照明。',
  history: [
    {
      operation_type: 'create',
      content: '市民提交路灯故障诉求',
      previous_status: null,
      current_status: 'pending',
      created_at: '2026-11-24T09:00:00Z',
    },
    {
      operation_type: 'review_resolve',
      content: '坐席复核通过并向市民公开答复',
      previous_status: 'processing',
      current_status: 'resolved',
      created_at: '2026-11-25T10:25:00Z',
    },
  ],
  feedbacks: [],
  work_orders: [
    {
      id: 'wo-1',
      work_order_no: 'WO-2026-001',
      ticket_id: 'T-2026-1125-001',
      task_type: 'primary',
      status: 'submitted',
      department_id: 3,
      department_name: '城市照明管理中心',
      assignee_name: '王照明',
      instructions: '请核查交叉口路灯箱变及线路故障并及时修复',
      result_summary: '防水接线盒已更换',
      public_content: '路灯电路恢复正常供电',
      version: 2,
      created_at: '2026-11-24T09:30:00Z',
      updated_at: '2026-11-25T09:50:00Z',
      history: [
        {
          action: 'submit',
          previous_status: 'processing',
          current_status: 'submitted',
          content: '城市照明管理中心提交修复结果',
          created_at: '2026-11-25T09:50:00Z',
        },
      ],
    },
  ],
}

describe('ticket permissions and conflict', () => {
  it('only exposes state-valid actions', () => {
    expect(allowedActions('agent', 'pending')).toEqual(['accept', 'reject', 'contact', 'remind'])
    expect(allowedActions('department_staff', 'assigned')).toEqual(['process', 'pause_sla', 'remind'])
    expect(allowedActions('department_staff', 'processing')).toEqual(['note', 'pause_sla', 'remind'])
    expect(allowedActions('citizen', 'processing')).toEqual(['remind'])
    expect(allowedActions('citizen', 'resolved')).toEqual(['feedback'])
    expect(allowedActions('admin', 'resolved')).toEqual(['close'])
  })

  it('preserves 409 conflict semantics', () => {
    const error = new ApiError(409, 'VERSION_CONFLICT', '工单数据已被其他操作更新')
    expect(error.status).toBe(409)
    expect(error.message).toContain('更新')
  })
})

describe('ticket closure_type display', () => {
  it('shows citizen / phone / admin closure without unknown fallback', () => {
    expect(closureTypeLabel('citizen_confirmed')).toBe('市民确认')
    expect(closureTypeLabel('phone_confirmed')).toBe('电话回访确认')
    expect(closureTypeLabel('admin_override')).toBe('管理员代办结')
  })
})

describe('TicketDetailPage print layout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetTicket.mockResolvedValue(sampleTicket)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders print button and invokes window.print() while keeping summary, timeline, work orders, and public reply visible', async () => {
    const user = userEvent.setup()
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})

    const { container } = renderApp(
      <MemoryRouter initialEntries={['/agent/tickets/T-2026-1125-001']}>
        <Routes>
          <Route path="/agent/tickets/:ticketId" element={<TicketDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const printBtn = await screen.findByRole('button', { name: /打印工单/ })
    expect(printBtn).toHaveClass('print-hide')
    expect(screen.getByRole('button', { name: '返回列表' })).toHaveClass('print-hide')

    const printHeader = container.querySelector('.ticket-print-header')
    expect(printHeader).toBeInTheDocument()
    expect(printHeader).toHaveTextContent('工单编号：T-2026-1125-001')

    expect(screen.getByText('建设路与青年路交叉口路灯连续三晚未亮，影响行人夜间通行安全。')).toBeInTheDocument()
    expect(screen.getByText('您好，建设路与青年路交叉口路灯供电故障已于昨晚修复并恢复正常照明。')).toBeInTheDocument()
    expect(screen.getByText('坐席复核通过并向市民公开答复')).toBeInTheDocument()
    expect(screen.getByText('防水接线盒已更换')).toBeInTheDocument()
    expect(container.querySelector('.ant-collapse.print-hide')).toBeInTheDocument()

    await user.click(printBtn)
    expect(printSpy).toHaveBeenCalledTimes(1)
  })
})
