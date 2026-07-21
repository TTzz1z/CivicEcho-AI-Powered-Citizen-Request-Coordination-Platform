import { cleanup, screen, waitFor } from '@testing-library/react'
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
    expect(await screen.findByText(/工单已创建/)).toBeInTheDocument()
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
})
