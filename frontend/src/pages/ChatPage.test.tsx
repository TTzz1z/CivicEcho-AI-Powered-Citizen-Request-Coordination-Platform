import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { sendRasaMessage } from '../api/rasa'
import { sendOrchestrator } from '../api/orchestrator'
import { ChatPage } from './ChatPage'

const authState = vi.hoisted(() => ({
  user: null as { id: number; role: 'citizen'; display_name: string } | null,
}))

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: authState.user }) }))
vi.mock('../api/rasa', () => ({ sendRasaMessage: vi.fn().mockResolvedValue([{ text: '工单已创建，编号：QT2026071300000001。', buttons: [{ title: '查询进度', payload: '查询进度' }] }]) }))
vi.mock('../api/orchestrator', () => ({
  sendOrchestrator: vi.fn().mockResolvedValue({
    primary_intent: 'complaint', route: 'ticket_intake', confidence: 0.9,
    in_domain: true, requires_llm: false, model_tier: 'rules',
    estimated_cost_level: 'none', rejection_reason: '', urgency: 'normal',
    sensitive_flags: [], routing_reason: 'rule', should_create_ticket: true,
    should_clarify: false, clarify_question: null,
    message: '工单已创建，编号：QT2026071300000001。',
    payload: { draft: { description: '我要投诉' } }, cache_hit: false,
    degraded: false, degrade_reason: '', rate_limited: false, budget_exceeded: false,
  }),
}))

const scrollTo = vi.fn()
const scrollIntoView = vi.fn()

describe('ChatPage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    authState.user = { id: 7, role: 'citizen', display_name: '测试市民' }
    localStorage.clear()
    vi.clearAllMocks()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  })

  it('renders orchestrator response and ticket detail entry safely for logged-in citizen', async () => {
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '我要投诉')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/工单已创建/)).toBeInTheDocument()
    expect(sendOrchestrator).toHaveBeenCalledWith(expect.objectContaining({ message: '我要投诉', route_hint: undefined }))
  })

  it('keeps automatic scrolling inside the message viewport', async () => {
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    expect(screen.getByLabelText('智能对话区').querySelector('.messages')).toHaveClass('messages')
    await waitFor(() => expect(scrollTo).toHaveBeenCalled())
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('explains anonymous ticket ownership and provides public navigation', () => {
    authState.user = null
    renderApp(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>)

    expect(screen.getByRole('link', { name: /返回服务首页/ })).toHaveAttribute('href', '/welcome')
    expect(screen.getByRole('link', { name: /账号登录/ })).toHaveAttribute('href', '/login')
    expect(screen.getByText('访客模式')).toBeInTheDocument()
    expect(screen.getByText(/登录市民账号后可提交工单/)).toBeInTheDocument()
  })

  it('visitor chat uses orchestrator instead of rasa', async () => {
    authState.user = null
    renderApp(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '你能干啥')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    await waitFor(() => {
      expect(sendOrchestrator).toHaveBeenCalledWith(expect.objectContaining({ message: '你能干啥' }))
    })
    expect(sendRasaMessage).not.toHaveBeenCalled()
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/工单已创建/)).toBeInTheDocument()
  })

  it('sanitizes rasa fallback that falsely claims ticket creation', async () => {
    vi.mocked(sendOrchestrator).mockRejectedValueOnce(new Error('orchestrator down'))
    vi.mocked(sendRasaMessage).mockResolvedValueOnce([{
      text: '已收到您的诉求信息（本地演示模式）：请前往“我的工单”查看后续办理进度。',
    }])
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '路灯坏了')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/系统没有创建真实工单/)).toBeInTheDocument()
    expect(within(main).queryByText(/请前往.“我的工单”.查看后续办理进度/)).not.toBeInTheDocument()
    expect(within(main).getByText(/智能编排暂时不可用|orchestrator_unavailable|当前回答已降级/)).toBeInTheDocument()
  })

  it('sanitizes rasa fallback that invents Incident IDs without QT ticket', async () => {
    const { sanitizeRasaFallbackText } = await import('./ChatPage')
    const text = sanitizeRasaFallbackText('Incident INC0012345 has been created. 请前往“我的工单”查看后续办理进度。')
    expect(text).toMatch(/系统没有创建真实工单/)
    expect(text).not.toMatch(/INC0012345/)
  })

  it('keeps rasa text that already contains a real QT id', async () => {
    const { sanitizeRasaFallbackText } = await import('./ChatPage')
    const text = sanitizeRasaFallbackText('工单已创建，编号：QT2026072200000099。')
    expect(text).toContain('QT2026072200000099')
  })

  it('bind alert shows success / empty / failed three states', async () => {
    const { BindStatusAlert } = await import('./ChatPage')
    const { renderApp: render } = await import('../test/render')
    const retry = vi.fn()

    const { unmount: u1 } = render(
      <MemoryRouter>
        <BindStatusAlert isCitizen hasUser bindState="success" boundCount={2} onRetry={retry} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('bind-success')).toBeInTheDocument()
    expect(screen.getByText(/已关联 2 条/)).toBeInTheDocument()
    expect(screen.getByText(/非跨设备账号找回/)).toBeInTheDocument()
    u1()

    const { unmount: u2 } = render(
      <MemoryRouter>
        <BindStatusAlert isCitizen hasUser bindState="empty" boundCount={0} onRetry={retry} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('bind-empty')).toBeInTheDocument()
    expect(screen.queryByText(/已绑定市民账号/)).not.toBeInTheDocument()
    u2()

    render(
      <MemoryRouter>
        <BindStatusAlert isCitizen hasUser bindState="failed" boundCount={null} onRetry={retry} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('bind-failed')).toBeInTheDocument()
    expect(screen.queryByTestId('bind-success')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重试绑定' }))
    expect(retry).toHaveBeenCalled()
  })

  it('renders policy citations and hides them on no_evidence', async () => {
    const { RouteMessage } = await import('./ChatPage')
    const { renderApp: render } = await import('../test/render')
    const withCite = {
      id: '1', side: 'bot' as const, text: '根据政策…', route: 'policy_rag',
      payload: {
        no_evidence: false,
        citations: [{
          index: 1, doc_id: 3, title: '补贴办法', doc_number: '民发〔2024〕2号',
          issuing_authority: '民政局', excerpt: '符合条件可申请补贴。', is_expired: false,
        }],
      },
    }
    const { unmount } = render(<MemoryRouter><RouteMessage item={withCite} /></MemoryRouter>)
    expect(await screen.findByTestId('policy-citations')).toBeInTheDocument()
    expect(screen.getByText('补贴办法')).toBeInTheDocument()
    unmount()

    render(<MemoryRouter><RouteMessage item={{
      ...withCite,
      payload: { no_evidence: true, citations: withCite.payload.citations },
    }} /></MemoryRouter>)
    expect(screen.getByTestId('no-evidence-banner')).toBeInTheDocument()
    expect(screen.queryByTestId('policy-citations')).not.toBeInTheDocument()
  })
})
