import { Alert, Badge, Button, Card, Drawer, Grid, Input, Space, Spin, Tag, Typography, message } from 'antd'
import { CommentOutlined, DeleteOutlined, FileTextOutlined, HistoryOutlined, HomeOutlined, LoginOutlined, ReloadOutlined, SafetyCertificateOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { streamOrchestratorChat, type OrchestratorResult, type OrchestratorStreamMeta } from '../api/orchestrator'
import { useAuth } from '../auth/AuthContext'
import { api, ApiError } from '../api/client'
import type { KbCitation } from '../types'
import { PageHeader } from '../components/PageHeader'
import { PolicyCitations } from '../components/PolicyCitations'
import { TicketDraftPanel, type DraftState } from '../components/TicketDraftPanel'
import { ensureChineseReply } from '../utils/languageGuard'
import {
  conversationDraftKey,
  conversationMessageKey,
  loadChatDraft,
  loadChatMessages,
  loadConversationIndex,
  migrateLegacyChatIfNeeded,
  removeConversation,
  saveChatDraft,
  saveChatMessages,
  touchConversationFromMessages,
  type ChatConversationMeta,
} from '../utils/chatStorage'

type ChatItem = { id: string; side: 'user' | 'bot'; text: string; route?: string; payload?: Record<string, unknown>; buttons?: { title: string; payload: string }[]; cacheHit?: boolean; degraded?: boolean; degradeReason?: string; rateLimited?: boolean; budgetExceeded?: boolean; requiresLlm?: boolean; modelTier?: string }
type BindState = 'idle' | 'binding' | 'success' | 'empty' | 'failed'
const suggestions = [
  { title: '我要提交一条投诉', hint: 'ticket_intake' },
  { title: '我想提出建议', hint: 'suggestion_intake' },
  { title: '咨询政策', hint: 'policy_rag' },
  { title: '查询工单进度', hint: 'ticket_progress' },
]
const ticketPattern = /QT\d{16}/g
function stableSender(userId?: number) { if (userId) return `web-user-${userId}`; let id = localStorage.getItem('tingting_sender_id'); if (!id) { id = `web-anon-${crypto.randomUUID()}`; localStorage.setItem('tingting_sender_id', id) } return id }

export function ChatPage() {
  const { user } = useAuth()
  const sender = useMemo(() => stableSender(user?.id), [user?.id])
  return <ChatConversation key={sender} sender={sender} />
}

function ChatConversation({ sender }: { sender: string }) {
  const { user } = useAuth(); const location = useLocation(); const isPublicChat = location.pathname === '/chat'; const isCitizen = user?.role === 'citizen'
  const screens = Grid.useBreakpoint()
  const [bindState, setBindState] = useState<BindState>('idle')
  const [boundCount, setBoundCount] = useState<number | null>(null)
  // Per-conversation id: rotate on "新建会话" so turn counters / guards / ai_usage_logs stay isolated.
  // Kept in sessionStorage so a refresh continues the same conversation.
  const [sessionId, setSessionId] = useState<string>(() => {
    const key = `tingting_session_${sender}`
    const existing = sessionStorage.getItem(key)
    if (existing) return existing
    const id = crypto.randomUUID()
    sessionStorage.setItem(key, id)
    return id
  })
  const storageKey = conversationMessageKey(sender, sessionId)
  const draftKey = conversationDraftKey(sender, sessionId)
  const [messages, setMessages] = useState<ChatItem[]>(() => {
    migrateLegacyChatIfNeeded(sender, sessionId)
    return loadChatMessages<ChatItem>(conversationMessageKey(sender, sessionId))
  })
  const [input, setInput] = useState(''); const [sending, setSending] = useState(false); const [failed, setFailed] = useState<string | null>(null); const messagesViewport = useRef<HTMLDivElement>(null)
  const [streamingMsg, setStreamingMsg] = useState<ChatItem | null>(null)
  const activeRequest = useRef<AbortController | null>(null)
  const activeSession = useRef(sessionId)
  const streamingTextRef = useRef('')
  const streamingMetaRef = useRef<OrchestratorStreamMeta | null>(null)
  const [draft, setDraft] = useState<DraftState | null>(() => loadChatDraft<DraftState>(conversationDraftKey(sender, sessionId)))
  const [draftMissing, setDraftMissing] = useState<string[]>([])
  const [dynamicFields, setDynamicFields] = useState<Record<string, unknown>[]>([])
  const [currentRoute, setCurrentRoute] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [conversations, setConversations] = useState<ChatConversationMeta[]>(() => {
    migrateLegacyChatIfNeeded(sender, sessionId)
    return loadConversationIndex(sender)
  })

  useEffect(() => () => {
    activeRequest.current?.abort()
    activeRequest.current = null
  }, [])

  useEffect(() => {
    saveChatMessages(storageKey, messages)
    if (messages.length) {
      setConversations(touchConversationFromMessages(sender, sessionId, messages))
    }
  }, [messages, storageKey, sender, sessionId])

  useEffect(() => {
    const viewport = messagesViewport.current
    viewport?.scrollTo?.({ top: viewport.scrollHeight, behavior: 'smooth' })
  }, [messages, streamingMsg])
  useEffect(() => { if (draft) saveChatDraft(draftKey, draft); else localStorage.removeItem(draftKey) }, [draft, draftKey])

  const bindAnonymous = useCallback(async () => {
    if (!isCitizen || !user?.id) return
    const anonId = localStorage.getItem('tingting_sender_id')
    if (!anonId || anonId.startsWith('web-user-')) {
      setBindState('success')
      setBoundCount(0)
      return
    }
    const boundKey = `tingting_bound_${user.id}`
    if (sessionStorage.getItem(boundKey) === '1') {
      setBindState('success')
      return
    }
    if (sessionStorage.getItem(boundKey) === 'empty') {
      setBindState('empty')
      setBoundCount(0)
      return
    }
    setBindState('binding')
    try {
      const res = await api.post<{ data?: { bound_count?: number }; bound_count?: number }>('/tickets/bind-anonymous', { sender_id: anonId })
      const count = Number(res.data?.data?.bound_count ?? res.data?.bound_count ?? 0)
      setBoundCount(count)
      if (count > 0) {
        sessionStorage.setItem(boundKey, '1')
        setBindState('success')
        message.success(`已绑定 ${count} 条匿名会话工单到当前账号`)
      } else {
        sessionStorage.setItem(boundKey, 'empty')
        setBindState('empty')
        message.info('当前账号已登录；未发现可绑定的匿名会话工单')
      }
    } catch {
      setBindState('failed')
      setBoundCount(null)
      message.error('匿名工单绑定失败，请重试')
    }
  }, [isCitizen, user?.id])

  useEffect(() => { void bindAnonymous() }, [bindAnonymous])

  const submit = async (raw = input, routeHint?: string) => {
    const text = raw.trim()
    if (!text || activeRequest.current) return
    const requestSessionId = sessionId
    const request = new AbortController()
    activeRequest.current = request
    streamingTextRef.current = ''
    streamingMetaRef.current = null
    const streamingId = crypto.randomUUID()
    const isCurrent = () => (
      activeRequest.current === request
      && activeSession.current === requestSessionId
      && !request.signal.aborted
    )
    setFailed(null); setInput(''); setStreamingMsg(null); setMessages(m => [...m, { id: crypto.randomUUID(), side: 'user', text }]); setSending(true)
    try {
      let receivedDone = false
      const result = await streamOrchestratorChat(
        { message: text, route_hint: routeHint, session_id: requestSessionId },
        {
          onMeta: meta => {
            if (!isCurrent()) return
            streamingMetaRef.current = meta
            setCurrentRoute(meta.route)
            setStreamingMsg({
              id: streamingId,
              side: 'bot',
              text: streamingTextRef.current,
              route: meta.route,
              payload: meta.payload,
              requiresLlm: meta.requires_llm,
              modelTier: meta.model_tier,
            })
          },
          onDelta: chunk => {
            if (!isCurrent()) return
            streamingTextRef.current += chunk
            const meta = streamingMetaRef.current
            setStreamingMsg({
              id: streamingId,
              side: 'bot',
              text: streamingTextRef.current,
              route: meta?.route,
              payload: meta?.payload,
              requiresLlm: meta?.requires_llm,
              modelTier: meta?.model_tier,
            })
          },
          onDone: done => {
            if (!isCurrent()) return
            receivedDone = true
            streamingTextRef.current = ''
            streamingMetaRef.current = null
            setStreamingMsg(null)
            handleOrchestratorResult(done)
          },
        },
        request.signal,
      )
      if (!receivedDone && isCurrent() && result) {
        streamingTextRef.current = ''
        streamingMetaRef.current = null
        setStreamingMsg(null)
        handleOrchestratorResult(result)
      }
    } catch (error) {
      if ((error instanceof DOMException && error.name === 'AbortError') || request.signal.aborted) {
        return
      }
      if (isCurrent()) {
        streamingTextRef.current = ''
        streamingMetaRef.current = null
        setStreamingMsg(null)
        setFailed(text)
        const isClientError = error instanceof ApiError && error.status >= 400 && error.status < 500
        setMessages(m => [...m, {
          id: crypto.randomUUID(),
          side: 'bot',
          text: isClientError ? error.message : '智能编排服务暂时不可用，请稍后点击重试，或前往工单页面手动提交诉求。',
          ...(isClientError ? {} : { degraded: true, degradeReason: 'orchestrator_unavailable' }),
        }])
      }
    } finally {
      if (activeRequest.current === request) {
        activeRequest.current = null
        setSending(false)
      }
    }
  }

  const stopGeneration = () => {
    const request = activeRequest.current
    if (!request) return
    const partial = streamingTextRef.current.trim()
    const meta = streamingMetaRef.current
    activeRequest.current = null
    request.abort()
    streamingTextRef.current = ''
    streamingMetaRef.current = null
    setStreamingMsg(null)
    setSending(false)
    if (partial) {
      setMessages(m => [...m, {
        id: crypto.randomUUID(),
        side: 'bot',
        text: partial,
        route: meta?.route,
        payload: meta?.payload,
        requiresLlm: meta?.requires_llm,
        modelTier: meta?.model_tier,
      }])
    }
  }

  const handleOrchestratorResult = (result: OrchestratorResult) => {
    setCurrentRoute(result.route)

    // Handle ticket draft routes
    if (result.should_create_ticket && result.payload.draft) {
      const d = result.payload.draft as DraftState
      setDraft(d)
      setDraftMissing(Object.entries(d).filter(([, v]) => !v).map(([k]) => k))
      setDynamicFields((result.payload.dynamic_fields as Record<string, unknown>[]) || [])
      if (!screens.md) setDrawerOpen(true)
    }

    // Scene switch: clear old draft if route is not ticket-related
    if (!result.should_create_ticket && draft && result.route !== 'ticket_intake' && result.route !== 'suggestion_intake') {
      // Stash draft but don't clear - user might come back
      setCurrentRoute(result.route)
    }

    // Add bot message (language-guarded client-side as last resort)
    setMessages(m => [...m, {
      id: crypto.randomUUID(), side: 'bot', text: ensureChineseReply(result.message),
      route: result.route, payload: result.payload,
      cacheHit: result.cache_hit,
      degraded: result.degraded,
      degradeReason: result.degrade_reason,
      rateLimited: result.rate_limited,
      budgetExceeded: result.budget_exceeded,
      requiresLlm: result.requires_llm,
      modelTier: result.model_tier,
    }])

    // If clarify, add clarification question
    if (result.should_clarify && result.clarify_question) {
      setMessages(m => [...m, { id: crypto.randomUUID(), side: 'bot', text: ensureChineseReply(result.clarify_question!), route: 'clarify' }])
    }

    // Budget exceeded: prompt visitor to login
    if (result.budget_exceeded && !user) {
      setMessages(m => [...m, { id: crypto.randomUUID(), side: 'bot', text: '当前为访客模式，登录市民账号后可继续咨询并提交工单。', route: 'login_prompt' }])
    }
  }

  const openConversation = (id: string) => {
    activeRequest.current?.abort()
    activeRequest.current = null
    activeSession.current = id
    streamingTextRef.current = ''
    streamingMetaRef.current = null
    setStreamingMsg(null)
    sessionStorage.setItem(`tingting_session_${sender}`, id)
    setSessionId(id)
    setSending(false)
    setInput('')
    setMessages(loadChatMessages<ChatItem>(conversationMessageKey(sender, id)))
    setDraft(loadChatDraft<DraftState>(conversationDraftKey(sender, id)))
    setDraftMissing([]); setDynamicFields([]); setCurrentRoute(null); setFailed(null); setDrawerOpen(false)
  }

  const clear = () => openConversation(crypto.randomUUID())

  const switchConversation = (id: string) => {
    if (id === sessionId) return
    if (messages.length) {
      saveChatMessages(storageKey, messages)
      setConversations(touchConversationFromMessages(sender, sessionId, messages))
    }
    if (draft) saveChatDraft(draftKey, draft)
    openConversation(id)
  }

  const deleteConversation = (id: string, event: React.MouseEvent) => {
    event.stopPropagation()
    const next = removeConversation(sender, id)
    setConversations(next)
    if (id !== sessionId) return
    openConversation(next[0]?.id ?? crypto.randomUUID())
  }

  const handleSubmitted = (ticketId: string) => {
    if (activeSession.current !== sessionId) return
    setMessages(m => [...m, { id: crypto.randomUUID(), side: 'bot', text: `工单已创建，编号：${ticketId}。您可以在"我的工单"中查看办理进度。`, route: 'ticket_created' }])
    setDraft(null); setDynamicFields([]); setCurrentRoute(null)
    setDrawerOpen(false)
    localStorage.removeItem(draftKey)
  }

  const missingCount = draft ? draftMissing.filter(f => !draft[f as keyof DraftState]).length : 0

  const conversationNavigation = <>
    <Button block type="primary" onClick={() => { clear(); setHistoryOpen(false) }}>新建会话</Button>
      {conversations.length > 0 && (
        <div className="chat-history" aria-label="聊天记录">
          <Typography.Title level={5} style={{ marginTop: 20, marginBottom: 8 }}>聊天记录</Typography.Title>
          <div className="chat-history-list">
            {conversations.map((item) => (
              <div key={item.id} className={`chat-history-item${item.id === sessionId ? ' active' : ''}`}>
                <button type="button" className="chat-history-select" aria-pressed={item.id === sessionId}
                  onClick={() => { switchConversation(item.id); setHistoryOpen(false) }}>
                <span className="chat-history-title">{item.title}</span>
                {item.preview && item.preview !== item.title && (
                  <span className="chat-history-preview">{item.preview}</span>
                )}
                </button>
                <button type="button"
                  className="chat-history-delete"
                  aria-label={`删除会话 ${item.title}`}
                  onClick={(e) => deleteConversation(item.id, e)}
                >
                  <DeleteOutlined aria-hidden />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      <Typography.Title level={5} style={{ marginTop: 28 }}>快捷入口</Typography.Title><Space direction="vertical" style={{ width: '100%' }}>{suggestions.map(s => <Button key={s.hint} block style={{ textAlign: 'left' }} onClick={() => { setHistoryOpen(false); void submit(s.title, s.hint) }}>{s.title}</Button>)}</Space>{currentRoute && <Tag style={{ marginTop: 16 }} color="cyan">当前场景：{routeLabel(currentRoute)}</Tag>}
  </>
  return <div className="chat-page civic-chat">
    <PageHeader title="智能对话" description="描述您遇到的问题。登记诉求前，您可以核对和编辑工单草稿。"
      extra={<Space wrap>
        {!screens.lg && <Button icon={<HistoryOutlined aria-hidden />} onClick={() => setHistoryOpen(true)}>会话与快捷入口</Button>}
        {isPublicChat && <><Link to="/welcome"><Button icon={<HomeOutlined/>}>返回服务首页</Button></Link>{!user && <Link to="/login"><Button type="primary" icon={<LoginOutlined/>}>账号登录</Button></Link>}</>}
      </Space>} />
    <BindStatusAlert isCitizen={!!isCitizen} hasUser={!!user} bindState={bindState} boundCount={boundCount} onRetry={() => { if (user?.id) sessionStorage.removeItem(`tingting_bound_${user.id}`); void bindAnonymous() }} />
    <div className={`chat-shell${draft && screens.xl ? ' has-draft' : ''}`}>
    {screens.lg && <aside className="chat-aside" aria-label="会话导航">{conversationNavigation}</aside>}
    <section className="chat-main" aria-label="智能对话区"><div ref={messagesViewport} className="messages" role="log" aria-label="对话记录" aria-live="polite">
      {messages.length === 0 && <div className="citizen-chat-intro">
        <span className="citizen-chat-symbol" aria-hidden="true"><CommentOutlined /></span>
        <Typography.Title level={2}>您好，需要办理什么？</Typography.Title>
        <Typography.Paragraph type="secondary">可以直接输入诉求，也可以从常用服务开始。</Typography.Paragraph>
        <div className="citizen-chat-options">{suggestions.map(s => <Button key={s.hint} onClick={() => submit(s.title, s.hint)}>{s.title}</Button>)}</div>
      </div>}
      {messages.map(m => <div className={`message-row ${m.side}`} key={m.id}><div className="bubble">
        <RouteMessage item={m} canReadDocument={Boolean(user)} />
        {m.buttons && <div className="message-actions">{m.buttons.map(b => <Button size="small" key={b.payload} onClick={() => submit(b.title)}>{b.title}</Button>)}</div>}
        {(m.text.match(ticketPattern) || []).map(id => <div className="ticket-highlight" key={id}><b>工单 {id}</b><div style={{ marginTop: 5 }}>{user ? <Link to={`/citizen/tickets/${id}`}>查看工单详情</Link> : <span>登录市民账号后可查看完整办理进度</span>}</div></div>)}
        {m.side === 'bot' && <MessageMetaTags item={m} />}
      </div></div>)}
      {streamingMsg ? (
        <div className="message-row bot" data-testid="streaming-message">
          <div className="bubble">
            <RouteMessage item={streamingMsg} canReadDocument={Boolean(user)} />
            <span className="ce-streaming-cursor" aria-hidden="true" />
          </div>
        </div>
      ) : (
        sending && <div className="message-row bot"><div className="bubble"><Spin size="small" /> 正在分析您的需求…</div></div>
      )}</div>
      {failed && <Alert type="warning" showIcon closable message="消息发送失败" action={<Button size="small" icon={<ReloadOutlined />} onClick={() => submit(failed)}>重试</Button>} />}
      <div className="composer"><Input.TextArea aria-label="输入消息" autoSize={{ minRows: 1, maxRows: 4 }} value={input} onChange={e => setInput(e.target.value)} placeholder="输入您的问题或诉求…" onPressEnter={e => { if (!e.shiftKey && !e.nativeEvent.isComposing && !sending) { e.preventDefault(); void submit() } }} />{sending ? <Button danger icon={<StopOutlined aria-hidden />} onClick={stopGeneration}>停止生成</Button> : <Button aria-label="发送" type="primary" icon={<SendOutlined aria-hidden />} disabled={!input.trim()} onClick={() => submit()}>发送</Button>}<Button aria-label="清空" icon={<DeleteOutlined />} onClick={clear} /></div>
    </section>
    {draft && screens.xl && <aside className="chat-draft-aside" aria-label="工单草稿"><TicketDraftPanel draft={draft} missing={draftMissing} onChange={setDraft} onSubmitted={handleSubmitted} /></aside>}
  </div>
  {draft && !screens.xl && <>
    <Button className="citizen-draft-trigger" type="primary" icon={<Badge count={missingCount} offset={[-4, 4]}><FileTextOutlined aria-hidden /></Badge>} onClick={() => setDrawerOpen(true)}>核对工单草稿</Button>
    <Drawer title="核对并确认诉求" placement="bottom" size="80dvh" open={drawerOpen} onClose={() => setDrawerOpen(false)}><TicketDraftPanel draft={draft} missing={draftMissing} onChange={setDraft} onSubmitted={handleSubmitted} /></Drawer>
  </>}
  {!screens.lg && <Drawer title="会话与快捷入口" placement="left" size={280} open={historyOpen} onClose={() => setHistoryOpen(false)}>{conversationNavigation}</Drawer>}
  </div>
}

export function BindStatusAlert({
  isCitizen, hasUser, bindState, boundCount, onRetry,
}: {
  isCitizen: boolean
  hasUser: boolean
  bindState: BindState
  boundCount: number | null
  onRetry: () => void
}) {
  if (!isCitizen) {
    return (
      <Alert
        style={{ marginTop: 16 }}
        type="warning"
        showIcon
        message={hasUser ? '当前不是市民角色' : '访客模式'}
        description={hasUser ? '请切换市民账号提交工单。' : <span>登录市民账号后可提交工单。<Link to="/login">去登录</Link></span>}
      />
    )
  }
  if (bindState === 'failed') {
    return (
      <Alert
        style={{ marginTop: 16 }}
        type="error"
        showIcon
        data-testid="bind-failed"
        message="匿名工单绑定失败"
        description={
          <Space direction="vertical" size={8}>
            <span>绑定未完成，请重试。失败时不会标记为已绑定。</span>
            <Button size="small" onClick={onRetry}>重试绑定</Button>
          </Space>
        }
      />
    )
  }
  if (bindState === 'empty') {
    return (
      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        data-testid="bind-empty"
        message="市民账号已登录"
        description="未发现可绑定的匿名会话工单；新提交的工单将进入“我的工单”。匿名绑定依赖本机会话标识，换设备或清除数据后无法自动找回，请勿分享该标识。"
      />
    )
  }
  if (bindState === 'binding') {
    return (
      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        data-testid="bind-binding"
        message="正在绑定匿名会话…"
        description="请稍候，正在将访客会话中的工单关联到当前账号。此绑定依赖本机会话标识，不是跨设备账号找回。"
      />
    )
  }
  if (bindState === 'success') {
    return (
      <Alert
        style={{ marginTop: 16 }}
        type="success"
        showIcon
        data-testid="bind-success"
        message="已绑定市民账号"
        description={boundCount && boundCount > 0 ? `已关联 ${boundCount} 条匿名会话工单；后续工单将进入“我的工单”。匿名工单仅可在原设备关联。` : '提交后，可在“我的工单”查看进度。匿名工单仅可在原设备关联。'}
      />
    )
  }
  return (
    <Alert
      style={{ marginTop: 16 }}
      type="info"
      showIcon
      data-testid="bind-idle"
      message="市民账号已登录"
      description="正在检查是否需要绑定匿名会话工单…"
    />
  )
}

function routeLabel(route: string): string {
  const map: Record<string, string> = { policy_rag: '政策咨询', service_guide: '办事指南', ticket_intake: '投诉/报修', suggestion_intake: '意见建议', ticket_progress: '工单查询', department_navigation: '部门导航', emergency_route: '紧急事项', general_chat: '日常对话', human_handoff: '人工服务', clarify: '信息确认' }
  return map[route] || route
}

const DEGRADE_LABELS: Record<string, string> = {
  llm_unavailable: '当前未使用外部大模型',
  embedding_fallback: '当前未使用外部向量模型（关键词/伪向量回退）',
  budget_exceeded: '当日调用额度已用尽',
  rate_limited: '请求过于频繁',
  orchestrator_unavailable: '智能编排暂时不可用',
  rag_failed: '检索链路异常，已降级回答',
}

function degradeBannerText(reason?: string): string | null {
  if (!reason) return '当前回答已降级'
  return DEGRADE_LABELS[reason] || `当前回答已降级：${reason}`
}

function asCitations(payload?: Record<string, unknown>): KbCitation[] {
  const raw = payload?.citations
  return Array.isArray(raw) ? (raw as KbCitation[]) : []
}

/** Route-specific message rendering */
export function RouteMessage({ item, canReadDocument = false }: { item: ChatItem; canReadDocument?: boolean }) {
  const { route, payload, text } = item

  // Emergency: show alert style
  if (route === 'emergency_route') {
    return <Alert type="error" showIcon icon={<SafetyCertificateOutlined />} message="紧急提示" description={<span style={{ whiteSpace: 'pre-wrap' }}>{text}</span>} />
  }

  // Policy / Service guide: show structured card + citations (never invent sources on no_evidence)
  if (route === 'policy_rag' || route === 'service_guide') {
    const banner = item.degraded ? degradeBannerText(item.degradeReason) : null
    const noEvidence = payload?.no_evidence === true
    const citations = asCitations(payload)
    return (
      <Card size="small" className="ce-ai-shimmer" style={{ background: '#ffffff', border: '1px solid var(--ce-line)' }} data-testid="policy-answer-card">
        {banner && <Alert type="warning" showIcon style={{ marginBottom: 10 }} message={banner} />}
        {noEvidence && (
          <Alert type="info" showIcon style={{ marginBottom: 10 }} data-testid="no-evidence-banner" message="未找到可引用政策依据，以下为引导说明，不是政策原文。" />
        )}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{text}</Typography.Paragraph>
        <PolicyCitations citations={citations} noEvidence={noEvidence} compact canReadDocument={canReadDocument} />
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>以上为 AI 参考解答，具体以官方政策为准。如需进一步处理，可说明"我要投诉"转为工单。</Typography.Text>
      </Card>
    )
  }

  // Ticket progress: show timeline style
  if (route === 'ticket_progress' && payload) {
    return <span style={{ whiteSpace: 'pre-wrap' }}>{text}</span>
  }

  // Default: plain text
  return <span style={{ whiteSpace: 'pre-wrap' }}>{text}</span>
}

/** Audit / status tags rendered below a bot message */
function MessageMetaTags({ item }: { item: ChatItem }) {
  const tags: React.ReactNode[] = []
  if (item.cacheHit) tags.push(<Tag key="cache" color="green" style={{ fontSize: 11 }}>缓存命中</Tag>)
  if (item.degraded) {
    tags.push(
      <Tag key="deg" color="orange" style={{ fontSize: 11 }}>
        {degradeBannerText(item.degradeReason)}
      </Tag>,
    )
  }
  if (item.rateLimited) tags.push(<Tag key="rl" color="red" style={{ fontSize: 11 }}>已限流</Tag>)
  if (item.budgetExceeded) tags.push(<Tag key="bud" color="volcano" style={{ fontSize: 11 }}>额度已满</Tag>)
  if (item.requiresLlm && item.modelTier && item.modelTier !== 'rules') {
    const tierLabel = item.modelTier === 'llm_full' ? 'LLM 全量' : item.modelTier === 'llm_lite' ? 'LLM 轻量' : item.modelTier
    tags.push(<Tag key="tier" color="blue" style={{ fontSize: 11 }}>{tierLabel}</Tag>)
  }
  if (!tags.length) return null
  return <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>{tags}</div>
}
