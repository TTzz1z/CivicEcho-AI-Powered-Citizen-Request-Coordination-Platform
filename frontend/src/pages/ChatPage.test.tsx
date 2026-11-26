import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamOrchestratorChat, type OrchestratorStreamDone, type OrchestratorStreamHandlers } from '../api/orchestrator'
import { ApiError } from '../api/client'
import { ChatPage } from './ChatPage'
import { renderApp } from '../test/render'

const authState = vi.hoisted(() => ({
  user: null as { id: number; role: 'citizen'; display_name: string } | null,
}))

const defaultResult: OrchestratorStreamDone = {
  primary_intent: 'complaint', route: 'ticket_intake', confidence: 0.9,
  in_domain: true, requires_llm: false, model_tier: 'rules',
  estimated_cost_level: 'none', rejection_reason: '', urgency: 'normal',
  sensitive_flags: [], routing_reason: 'rule', should_create_ticket: true,
  should_clarify: false, clarify_question: null,
  message: '工单已创建，编号：QT2026071300000001。',
  payload: { draft: { description: '我要投诉' } }, cache_hit: false,
  degraded: false, degrade_reason: '', rate_limited: false, budget_exceeded: false,
}

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: authState.user }) }))
vi.mock('../api/orchestrator', async () => {
  const actual = await vi.importActual<typeof import('../api/orchestrator')>('../api/orchestrator')
  return {
    ...actual,
    streamOrchestratorChat: vi.fn(async (_payload, handlers: OrchestratorStreamHandlers = {}) => {
      handlers.onDone?.(defaultResult)
      return defaultResult
    }),
  }
})

const scrollTo = vi.fn()
const scrollIntoView = vi.fn()

describe('ChatPage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    authState.user = { id: 7, role: 'citizen', display_name: '测试市民' }
    localStorage.clear()
    sessionStorage.clear()
    vi.clearAllMocks()
    vi.mocked(streamOrchestratorChat).mockImplementation(async (_payload, handlers = {}) => {
      handlers.onDone?.(defaultResult)
      return defaultResult
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  })

  it('renders orchestrator response and ticket detail entry safely for logged-in citizen', async () => {
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '我要投诉')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/工单已创建/)).toBeInTheDocument()
    expect(streamOrchestratorChat).toHaveBeenCalledWith(
      expect.objectContaining({ message: '我要投诉', route_hint: undefined }),
      expect.any(Object),
      expect.any(AbortSignal),
    )
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

  it('visitor chat uses orchestrator stream', async () => {
    authState.user = null
    renderApp(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '你能干啥')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    await waitFor(() => {
      expect(streamOrchestratorChat).toHaveBeenCalledWith(
        expect.objectContaining({ message: '你能干啥' }),
        expect.any(Object),
        expect.any(AbortSignal),
      )
    })
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/工单已创建/)).toBeInTheDocument()
  })

  it('discards delayed stream chunks and done payload after clearing the conversation', async () => {
    let capturedHandlers!: OrchestratorStreamHandlers
    let finish!: (result: OrchestratorStreamDone) => void
    vi.mocked(streamOrchestratorChat).mockImplementationOnce((_payload, handlers = {}) => {
      capturedHandlers = handlers
      return new Promise(resolve => { finish = resolve })
    })
    renderApp(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '请说明社区服务')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    await waitFor(() => expect(streamOrchestratorChat).toHaveBeenCalledTimes(1))

    const signal = vi.mocked(streamOrchestratorChat).mock.calls[0][2]
    await userEvent.click(screen.getByRole('button', { name: /^清空$/ }))
    expect(signal?.aborted).toBe(true)

    const delayedDone = {
      ...defaultResult,
      route: 'general_chat',
      message: '前一会话才应该显示的答复',
      payload: {},
      should_create_ticket: false,
      should_clarify: false,
    }
    await act(async () => {
      capturedHandlers.onDelta?.('前一会话碎片')
      capturedHandlers.onDone?.(delayedDone)
      finish(delayedDone)
    })

    expect(screen.queryByText('前一会话碎片')).not.toBeInTheDocument()
    expect(screen.queryByText('前一会话才应该显示的答复')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '您好，需要办理什么？' })).toBeVisible()
  })

  it('streams incremental deltas and reconciles authoritative done text', async () => {
    let capturedHandlers!: OrchestratorStreamHandlers
    let finish!: (result: OrchestratorStreamDone) => void
    vi.mocked(streamOrchestratorChat).mockImplementationOnce((_payload, handlers = {}) => {
      capturedHandlers = handlers
      return new Promise(resolve => { finish = resolve })
    })
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '如何办理低保')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    await waitFor(() => expect(streamOrchestratorChat).toHaveBeenCalledTimes(1))

    await act(async () => {
      capturedHandlers.onMeta?.({
        primary_intent: 'policy_rag', route: 'policy_rag', confidence: 0.9,
        in_domain: true, requires_llm: true, model_tier: 'llm_lite',
        estimated_cost_level: 'low', rejection_reason: '', urgency: 'normal',
        sensitive_flags: [], routing_reason: 'rag', should_create_ticket: false,
        should_clarify: false, payload: { no_evidence: false, citations: [] },
      })
      capturedHandlers.onDelta?.('请携带身份证')
    })

    expect(screen.getByTestId('streaming-message')).toHaveTextContent('请携带身份证')

    await act(async () => {
      capturedHandlers.onDelta?.('前往社区窗口')
    })
    expect(screen.getByTestId('streaming-message')).toHaveTextContent('请携带身份证前往社区窗口')

    const finalDone: OrchestratorStreamDone = {
      ...defaultResult,
      route: 'policy_rag',
      should_create_ticket: false,
      requires_llm: true,
      model_tier: 'llm_lite',
      payload: { no_evidence: false, citations: [] },
      message: '经核对，请携带身份证与户口本前往街道窗口申请。',
    }
    await act(async () => {
      capturedHandlers.onDone?.(finalDone)
      finish(finalDone)
    })

    expect(screen.queryByTestId('streaming-message')).not.toBeInTheDocument()
    expect(screen.getByText('经核对，请携带身份证与户口本前往街道窗口申请。')).toBeInTheDocument()
  })

  it('supports Stop Generation mid-stream preserving partial reply without error alert', async () => {
    let capturedHandlers!: OrchestratorStreamHandlers
    vi.mocked(streamOrchestratorChat).mockImplementationOnce((_payload, handlers = {}) => {
      capturedHandlers = handlers
      return new Promise(() => {})
    })
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '政策咨询')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    await waitFor(() => expect(streamOrchestratorChat).toHaveBeenCalledTimes(1))

    const signal = vi.mocked(streamOrchestratorChat).mock.calls[0][2]
    await act(async () => {
      capturedHandlers.onDelta?.('已输出的部分建议内容')
    })
    expect(screen.getByTestId('streaming-message')).toHaveTextContent('已输出的部分建议内容')

    await userEvent.click(screen.getByRole('button', { name: /停止生成/ }))
    expect(signal?.aborted).toBe(true)
    expect(screen.queryByTestId('streaming-message')).not.toBeInTheDocument()
    expect(screen.getByText('已输出的部分建议内容')).toBeInTheDocument()
    expect(screen.queryByText('消息发送失败')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^发送$/ })).toBeInTheDocument()
  })

  it('shows degraded fallback alert and retries successfully when orchestrator fails with 5xx', async () => {
    vi.mocked(streamOrchestratorChat)
      .mockRejectedValueOnce(new ApiError(503, 'UNAVAILABLE', 'orchestrator down'))
      .mockImplementationOnce(async (_payload, handlers = {}) => {
        const res: OrchestratorStreamDone = {
          primary_intent: 'general_chat', route: 'general_chat', confidence: 0.9,
          in_domain: true, requires_llm: false, model_tier: 'rules',
          estimated_cost_level: 'none', rejection_reason: '', urgency: 'normal',
          sensitive_flags: [], routing_reason: 'rule', should_create_ticket: false,
          should_clarify: false, clarify_question: null,
          message: '重试成功，已为您接通智能助手。',
          payload: {}, cache_hit: false,
          degraded: false, degrade_reason: '', rate_limited: false, budget_exceeded: false,
        }
        handlers.onDone?.(res)
        return res
      })
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '路灯坏了')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))

    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText(/智能编排服务暂时不可用/)).toBeInTheDocument()
    expect(within(main).getByText('智能编排暂时不可用')).toBeInTheDocument()
    expect(within(main).queryByText(/QT\d{16}/)).not.toBeInTheDocument()
    expect(within(main).getByRole('alert')).toHaveTextContent('消息发送失败')

    await userEvent.click(within(main).getByRole('button', { name: /重\s*试/ }))
    expect(await within(main).findByText('重试成功，已为您接通智能助手。')).toBeInTheDocument()
    expect(streamOrchestratorChat).toHaveBeenCalledTimes(2)
  })

  it('shows client or rate-limit error message without degraded tag', async () => {
    vi.mocked(streamOrchestratorChat).mockRejectedValueOnce(new ApiError(429, 'RATE_LIMITED', '稍后重试'))
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '路灯坏了')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    const main = screen.getByLabelText('智能对话区')
    expect(await within(main).findByText('稍后重试')).toBeInTheDocument()
    expect(within(main).getByRole('alert')).toHaveTextContent('消息发送失败')
    expect(within(main).queryByText('智能编排暂时不可用')).not.toBeInTheDocument()
  })

  it('renders TicketDraftPanel when orchestrator returns should_create_ticket with draft', async () => {
    vi.mocked(streamOrchestratorChat).mockImplementationOnce(async (_payload, handlers = {}) => {
      const res: OrchestratorStreamDone = {
        primary_intent: 'complaint', route: 'ticket_intake', confidence: 0.95,
        in_domain: true, requires_llm: false, model_tier: 'rules',
        estimated_cost_level: 'none', rejection_reason: '', urgency: 'normal',
        sensitive_flags: [], routing_reason: 'rule', should_create_ticket: true,
        should_clarify: false, clarify_question: null,
        message: '已为您整理工单草稿，请核对后提交。',
        payload: { draft: { request_type: '投诉', description: '人民路路灯不亮', location: '人民路' } },
        cache_hit: false, degraded: false, degrade_reason: '', rate_limited: false, budget_exceeded: false,
      }
      handlers.onDone?.(res)
      return res
    })
    renderApp(<MemoryRouter><ChatPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('输入消息'), '人民路路灯不亮')
    await userEvent.click(screen.getByRole('button', { name: /^发送$/ }))
    expect(await screen.findByText('已为您整理工单草稿，请核对后提交。')).toBeInTheDocument()
    const draftTitle = await screen.findByText('工单草稿')
    const draftPanel = draftTitle.closest('.draft-panel') as HTMLElement
    expect(within(draftPanel).getByText('人民路路灯不亮')).toBeInTheDocument()
    expect(within(draftPanel).getByText('人民路')).toBeInTheDocument()
    expect(within(draftPanel).getByRole('button', { name: /确认提交工单/ })).toBeEnabled()
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
    expect(screen.getByText(/匿名工单仅可在原设备关联/)).toBeInTheDocument()
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
