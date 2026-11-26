import { act, cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { KbRagStreamDone, KbRagStreamHandlers } from '../api/kb'
import { ApiError } from '../api/client'
import { renderApp } from '../test/render'
import { KbRagPanel } from './KbRagPanel'

const kb = vi.hoisted(() => ({ stream: vi.fn(), feedback: vi.fn() }))
vi.mock('../api/kb', () => ({ streamRagQuery: kb.stream, submitKbFeedback: kb.feedback }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: 'citizen' } }) }))

describe('KbRagPanel', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('links feedback to the question that generated the visible answer', async () => {
    const done: KbRagStreamDone = {
      answer: '这是第一条政策回答。',
      citations: [],
      no_evidence: false,
      retrieval_count: 0,
      latency_ms: 10,
      generated_at: '2026-11-26T05:00:00Z',
      provider: 'rules',
    }
    kb.stream.mockImplementation(async (_payload, handlers: KbRagStreamHandlers = {}) => {
      handlers.onDone?.(done)
      return done
    })
    kb.feedback.mockResolvedValue(undefined)

    const user = userEvent.setup()
    renderApp(<KbRagPanel />)
    const input = screen.getByRole('textbox', { name: '政策咨询问题' })
    await user.type(input, '第一条提交的问题')
    await user.click(screen.getByRole('button', { name: '查询政策' }))
    expect(await screen.findByText('这是第一条政策回答。')).toBeVisible()
    await user.clear(input)
    await user.type(input, '未提交的另一个问题')
    await user.click(screen.getByRole('button', { name: '有帮助' }))

    await waitFor(() => expect(kb.feedback).toHaveBeenCalledWith(expect.objectContaining({
      query_text: '第一条提交的问题',
      answer_text: '这是第一条政策回答。',
    })))
  })

  it('streams meta citations and incremental deltas then reconciles with done payload', async () => {
    let capturedHandlers!: KbRagStreamHandlers
    let finish!: (res: KbRagStreamDone) => void
    kb.stream.mockImplementationOnce((_payload, handlers: KbRagStreamHandlers = {}) => {
      capturedHandlers = handlers
      return new Promise(resolve => { finish = resolve })
    })

    const user = userEvent.setup()
    renderApp(<KbRagPanel />)
    await user.type(screen.getByRole('textbox', { name: '政策咨询问题' }), '如何申请住房补贴')
    await user.click(screen.getByRole('button', { name: '查询政策' }))
    await waitFor(() => expect(kb.stream).toHaveBeenCalledTimes(1))

    await act(async () => {
      capturedHandlers.onMeta?.({
        citations: [{
          index: 1,
          doc_id: 9,
          title: '住房保障办法',
          doc_number: '住建〔2025〕1号',
          issuing_authority: '住建局',
          excerpt: '符合条件可按月发放补贴。',
          is_expired: false,
        }],
        no_evidence: false,
        retrieval_count: 1,
        route: 'kb_rag',
      })
      capturedHandlers.onDelta?.('第一步：提交申请材料')
    })

    expect(screen.getByText('正在生成…')).toBeInTheDocument()
    expect(screen.getByText('第一步：提交申请材料')).toBeInTheDocument()
    expect(screen.getByText('住房保障办法')).toBeInTheDocument()
    // Feedback hidden while streaming
    expect(screen.queryByRole('button', { name: '有帮助' })).not.toBeInTheDocument()

    const done: KbRagStreamDone = {
      answer: '完整政策解答：请携带身份证与收入证明前往社区受理点。',
      citations: [{
        index: 1,
        doc_id: 9,
        title: '住房保障办法',
        doc_number: '住建〔2025〕1号',
        issuing_authority: '住建局',
        excerpt: '符合条件可按月发放补贴。',
        is_expired: false,
      }],
      no_evidence: false,
      retrieval_count: 1,
      latency_ms: 42,
      generated_at: '2026-11-26T05:00:00Z',
      provider: 'deepseek',
      model: 'deepseek-chat',
    }
    await act(async () => {
      capturedHandlers.onDone?.(done)
      finish(done)
    })

    expect(screen.getByText('完整政策解答：请携带身份证与收入证明前往社区受理点。')).toBeInTheDocument()
    expect(screen.getByText('耗时 42 ms')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '有帮助' })).toBeEnabled()
  })

  it('supports Stop Generation preserving partial answer and hiding feedback', async () => {
    let capturedHandlers!: KbRagStreamHandlers
    let capturedSignal: AbortSignal | undefined
    kb.stream.mockImplementationOnce((_payload, handlers: KbRagStreamHandlers = {}, signal?: AbortSignal) => {
      capturedHandlers = handlers
      capturedSignal = signal
      return new Promise(() => {})
    })

    const user = userEvent.setup()
    renderApp(<KbRagPanel />)
    await user.type(screen.getByRole('textbox', { name: '政策咨询问题' }), '医保报销比例')
    await user.click(screen.getByRole('button', { name: '查询政策' }))
    await waitFor(() => expect(kb.stream).toHaveBeenCalledTimes(1))

    await act(async () => {
      capturedHandlers.onDelta?.('部分医保报销说明')
    })

    await user.click(screen.getByRole('button', { name: /停止生成/ }))
    expect(capturedSignal?.aborted).toBe(true)
    expect(screen.getByText('已停止生成')).toBeInTheDocument()
    expect(screen.getByText('部分医保报销说明')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '有帮助' })).not.toBeInTheDocument()
  })

  it('displays stream error and supports retry', async () => {
    const done: KbRagStreamDone = {
      answer: '重试后成功返回政策解读。',
      citations: [],
      no_evidence: false,
      retrieval_count: 0,
      latency_ms: 15,
      generated_at: '2026-11-26T05:00:00Z',
      provider: 'rules',
    }
    kb.stream
      .mockRejectedValueOnce(new ApiError(503, 'STREAM_ERROR', '知识库流式服务繁忙'))
      .mockImplementationOnce(async (_payload, handlers: KbRagStreamHandlers = {}) => {
        handlers.onDone?.(done)
        return done
      })

    const user = userEvent.setup()
    renderApp(<KbRagPanel />)
    await user.type(screen.getByRole('textbox', { name: '政策咨询问题' }), '社保转移')
    await user.click(screen.getByRole('button', { name: '查询政策' }))

    expect(await screen.findByText('知识库流式服务繁忙')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(await screen.findByText('重试后成功返回政策解读。')).toBeInTheDocument()
  })

  it('hides stale prior result when a subsequent query fails', async () => {
    const firstDone: KbRagStreamDone = {
      answer: '第一次查询的旧政策回答。',
      citations: [],
      no_evidence: false,
      retrieval_count: 0,
      latency_ms: 12,
      generated_at: '2026-11-26T05:00:00Z',
      provider: 'rules',
    }
    kb.stream
      .mockImplementationOnce(async (_payload, handlers: KbRagStreamHandlers = {}) => {
        handlers.onDone?.(firstDone)
        return firstDone
      })
      .mockRejectedValueOnce(new ApiError(503, 'STREAM_ERROR', '后续检索失败'))

    const user = userEvent.setup({ delay: null })
    renderApp(<KbRagPanel />)
    const input = screen.getByRole('textbox', { name: '政策咨询问题' })
    await user.type(input, '首次政策问题')
    await user.click(screen.getByRole('button', { name: '查询政策' }))
    expect(await screen.findByText('第一次查询的旧政策回答。')).toBeInTheDocument()

    await user.clear(input)
    await user.type(input, '第二次失败问题')
    await user.click(screen.getByRole('button', { name: '查询政策' }))

    expect(await screen.findByText('后续检索失败')).toBeInTheDocument()
    expect(screen.queryByText('第一次查询的旧政策回答。')).not.toBeInTheDocument()
  })
})
