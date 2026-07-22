import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { IntelligencePage } from './IntelligencePage'
import { analyzeTicket, reviewSuggestion } from '../api/intelligence'

const authState = vi.hoisted(() => ({
  user: { id: 2, role: 'agent' as string, display_name: '坐席' },
}))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: authState.user }) }))
vi.mock('../api/intelligence', () => ({
  analyzeTicket: vi.fn(),
  listSuggestions: vi.fn().mockResolvedValue([]),
  listHotspots: vi.fn().mockResolvedValue([]),
  listIntegrationStatuses: vi.fn().mockResolvedValue([]),
  reviewSuggestion: vi.fn().mockResolvedValue({}),
  syncDirectory: vi.fn(),
  syncExternalTicket: vi.fn(),
}))

describe('IntelligencePage role split', () => {
  beforeEach(() => {
    authState.user = { id: 2, role: 'agent', display_name: '坐席' }
    vi.mocked(analyzeTicket).mockResolvedValue([{
      id: 't1',
      ticket_id: 'QT2026071400000001',
      suggestion_type: 'triage_assistant',
      status: 'completed',
      risk_level: 'attention',
      confidence: 0,
      provider: 'rules',
      model_name: 'rules',
      result: {
        case_summary: { description: '路灯损坏', location: '幸福路', duration: '3天', affected_scope: '行人' },
        classification: { request_type: '投诉', category: '路灯', subcategory: '', reason: '设施报修' },
        urgency: { level: 'normal', emergency: false, reason: '一般性诉求' },
        completeness: { complete: false, missing_fields: ['联系方式'], follow_up_questions: ['请补充联系电话'], completeness_score: 70 },
        department_candidates: [{ department_name: '综合受理', recommendation_level: 'high', reason: '统一受理' }],
        sla_recommendation: { response_deadline: '24小时', handling_deadline: '按分类', reason: '内部参考' },
        intake_notice_draft: '您的诉求已受理，平台将根据设施权属派发至相关责任部门。',
      },
      explanation: 'capability=triage_assistant',
      created_at: '2026-07-14T10:00:00Z',
      advisory_only: true,
    }])
  })

  it('agent page shows triage content and not handling document draft', async () => {
    renderApp(<MemoryRouter><IntelligencePage /></MemoryRouter>)
    expect(screen.getByText('智能分诊与派发')).toBeInTheDocument()
    expect(screen.getByText('人机协同边界')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('工单编号'), 'QT2026071400000001')
    await userEvent.click(screen.getByRole('button', { name: '生成分诊建议' }))
    expect(await screen.findByText('责任部门推荐')).toBeInTheDocument()
    expect(screen.getByText('综合受理')).toBeInTheDocument()
    expect(screen.getByText(/受理告知语/)).toBeInTheDocument()
    expect(screen.queryByText('处理文书草稿')).not.toBeInTheDocument()
    expect(screen.queryByText('现场核查清单')).not.toBeInTheDocument()
    expect(analyzeTicket).toHaveBeenCalledWith('QT2026071400000001', ['triage_assistant'], 'triage_assistant')
    expect(screen.getByRole('button', { name: '采纳分派建议' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '有帮助' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '有帮助' }))
    await waitFor(() => expect(reviewSuggestion).toHaveBeenCalledWith('t1', 'helpful'))
  })

  it('department page shows handling checklist and calls handling capability', async () => {
    authState.user = { id: 3, role: 'department_staff', display_name: '部门' }
    vi.mocked(analyzeTicket).mockResolvedValue([{
      id: 'h1',
      ticket_id: 'QT2026071400000001',
      suggestion_type: 'handling_assistant',
      status: 'completed',
      risk_level: 'attention',
      confidence: 0,
      provider: 'rules',
      model_name: 'rules',
      result: {
        case_summary: { description: '路灯', assigned_department: '综合受理', classification: '路灯', known_facts: [] },
        verification_checklist: ['核实杆号'],
        handling_plan: ['现场核查'],
        risk_warnings: ['临近 SLA'],
        policy_references: ['照明管理办法'],
        missing_handling_facts: ['处理措施'],
        reply_draft: '经现场核查，该设施位于【位置】',
        facts_sufficient: false,
      },
      explanation: 'capability=handling_assistant',
      created_at: '2026-07-14T10:00:00Z',
      advisory_only: true,
    }])
    renderApp(<MemoryRouter><IntelligencePage /></MemoryRouter>)
    expect(screen.getByText('AI 办件与文书辅助')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('工单编号'), 'QT2026071400000001')
    await userEvent.click(screen.getByRole('button', { name: '生成办件建议' }))
    expect(await screen.findByText('现场核查清单')).toBeInTheDocument()
    expect(screen.getByText('核实杆号')).toBeInTheDocument()
    expect(screen.getByText('办理方案')).toBeInTheDocument()
    expect(screen.queryByText('处理文书草稿')).not.toBeInTheDocument()
    expect(screen.queryByText(/同步真实工单平台/)).not.toBeInTheDocument()
    expect(analyzeTicket).toHaveBeenCalledWith('QT2026071400000001', ['handling_assistant'], 'handling_assistant')
  })
})
