import { Alert, Badge, Button, Card, Drawer, Grid, Input, Space, Spin, Tag, Typography, message } from 'antd'
import { DeleteOutlined, FileTextOutlined, HomeOutlined, LoginOutlined, ReloadOutlined, SafetyCertificateOutlined, SendOutlined } from '@ant-design/icons'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { sendOrchestrator, type OrchestratorResult } from '../api/orchestrator'
import { sendRasaMessage } from '../api/rasa'
import { useAuth } from '../auth/AuthContext'
import { api } from '../api/client'
import type { DraftPayload, KbCitation } from '../types'
import { PageHeader } from '../components/PageHeader'
import { PolicyCitations } from '../components/PolicyCitations'
import { TicketDraftPanel, type DraftState } from '../components/TicketDraftPanel'
import { ensureChineseReply } from '../utils/languageGuard'
import {
  clearChatPrivacyOnAccountSwitch,
  loadChatDraft,
  loadChatMessages,
  saveChatDraft,
  saveChatMessages,
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
  const { user } = useAuth(); const location = useLocation(); const isPublicChat = location.pathname === '/chat'; const isCitizen = user?.role === 'citizen'; const sender = useMemo(() => stableSender(user?.id), [user?.id]); const storageKey = `tingting_chat_${sender}`
  const draftKey = `tingting_chat_draft_${sender}`
  const screens = Grid.useBreakpoint()
  const [messages, setMessages] = useState<ChatItem[]>(() => loadChatMessages<ChatItem>(storageKey))
  const [input, setInput] = useState(''); const [sending, setSending] = useState(false); const [failed, setFailed] = useState<string | null>(null); const messagesViewport = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState<DraftState | null>(() => loadChatDraft<DraftState>(draftKey))
  const [draftMissing, setDraftMissing] = useState<string[]>([])
  const [dynamicFields, setDynamicFields] = useState<Record<string, unknown>[]>([])
  const [currentRoute, setCurrentRoute] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
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

  const prevUserIdRef = useRef<number | undefined>(user?.id)
  useEffect(() => {
    const prev = prevUserIdRef.current
    if (prev !== user?.id) {
      clearChatPrivacyOnAccountSwitch(prev, user?.id)
      prevUserIdRef.current = user?.id
      setBindState('idle')
      setBoundCount(null)
    }
  }, [user?.id])

  useEffect(() => { saveChatMessages(storageKey, messages); const viewport = messagesViewport.current; viewport?.scrollTo?.({ top: viewport.scrollHeight, behavior: 'smooth' }) }, [messages, storageKey])
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
    const text = raw.trim(); if (!text || sending) return
    setFailed(null); setInput(''); setMessages(m => [...m, { id: crypto.randomUUID(), side: 'user', text }]); setSending(true)
    try {
      // Plan C: visitors and logged-in users both use Orchestrator (Chinese routing).
      // Rasa remains as fallback when Orchestrator is unreachable.
      try {
        const result = await sendOrchestrator({ message: text, route_hint: routeHint, session_id: sessionId })
        handleOrchestratorResult(result, text)
      } catch {
        // Fallback to language-guarded Rasa path. Never present Rasa localmode
        // acknowledgements as successful ticket creation without a real QT id.
        const bareTicketId = /^QT\d{12,16}$/i.exec(text)
        const rasaText = bareTicketId ? `/query_request_status{"ticket_id":"${bareTicketId[0].toUpperCase()}"}` : text
        const response = await sendRasaMessage(sender, rasaText)
        const bot: ChatItem[] = []
        for (const r of response) {
          const custom = r.custom as DraftPayload | undefined
          if (custom && custom.type === 'draft_extracted') {
            setDraft(custom.draft); setDraftMissing(custom.missing || []); setCurrentRoute('ticket_intake')
            if (!screens.md) setDrawerOpen(true)
          }
          if (r.text || r.buttons?.length) {
            bot.push({
              id: crypto.randomUUID(),
              side: 'bot',
              text: sanitizeRasaFallbackText(r.text || '请选择下一步操作'),
              buttons: r.buttons,
              degraded: true,
              degradeReason: 'orchestrator_unavailable',
            })
          }
        }
        setMessages(m => [...m, ...(bot.length ? bot : [{ id: crypto.randomUUID(), side: 'bot' as const, text: '智能助手暂时不可用，已切换降级通道。系统不会在此模式下自动创建工单。', degraded: true, degradeReason: 'orchestrator_unavailable' }])])
      }
    } catch { setFailed(text); setMessages(m => [...m, { id: crypto.randomUUID(), side: 'bot', text: '服务暂时无法连接，请稍后重试。' }]) }
    finally { setSending(false) }
  }

  const handleOrchestratorResult = (result: OrchestratorResult, _originalText: string) => {
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

  const clear = () => {
    setMessages([]); setDraft(null); setDraftMissing([]); setDynamicFields([]); setCurrentRoute(null)
    localStorage.removeItem(storageKey); localStorage.removeItem(draftKey)
    // Rotate session so the new conversation does not inherit previous ticket slots / guard counters.
    const newId = crypto.randomUUID()
    sessionStorage.setItem(`tingting_session_${sender}`, newId)
    setSessionId(newId)
  }

  const handleSubmitted = (ticketId: string) => {
    setMessages(m => [...m, { id: crypto.randomUUID(), side: 'bot', text: `工单已创建，编号：${ticketId}。您可以在"我的工单"中查看办理进度。`, route: 'ticket_created' }])
    setDraft(null); setDynamicFields([]); setCurrentRoute(null)
    localStorage.removeItem(draftKey)
  }

  const missingCount = draft ? draftMissing.filter(f => !draft[f as keyof DraftState]).length : 0

  return <div className="chat-page"><PageHeader eyebrow="SMART SERVICE" title="智能对话" description="政策咨询、投诉建议、工单查询——统一入口，智能路由。" extra={isPublicChat?<Space wrap><Link to="/welcome"><Button icon={<HomeOutlined/>}>返回服务首页</Button></Link>{!user&&<Link to="/login"><Button type="primary" icon={<LoginOutlined/>}>账号登录</Button></Link>}</Space>:undefined} /><div className={`chat-shell${draft && screens.md ? ' has-draft' : ''}`}>
    <aside className="chat-aside"><Button block type="primary" onClick={clear}>新建会话</Button><Typography.Title level={5} style={{ marginTop: 28 }}>快捷入口</Typography.Title><Space direction="vertical" style={{ width: '100%' }}>{suggestions.map(s => <Button key={s.hint} block style={{ textAlign: 'left' }} onClick={() => submit(s.title, s.hint)}>{s.title}</Button>)}</Space>{currentRoute && <Tag style={{ marginTop: 16 }} color="cyan">当前场景：{routeLabel(currentRoute)}</Tag>}
      <BindStatusAlert isCitizen={!!isCitizen} hasUser={!!user} bindState={bindState} boundCount={boundCount} onRetry={() => { if (user?.id) sessionStorage.removeItem(`tingting_bound_${user.id}`); void bindAnonymous() }} />
    </aside>
    <section className="chat-main" aria-label="智能对话区"><div ref={messagesViewport} className="messages" aria-live="polite">{messages.length === 0 && <div style={{ margin: 'auto', textAlign: 'center', maxWidth: 480 }}><div className="brand-mark" style={{ margin: '0 auto 18px', color: '#167c72', borderColor: '#82bdb6' }}>倾</div><Typography.Title level={3}>你好，我是倾听助手</Typography.Title><Typography.Paragraph type="secondary">我可以帮您咨询政策、提交投诉建议、查询工单进度。请直接描述您的需求。</Typography.Paragraph><Space wrap style={{ justifyContent: 'center' }}>{suggestions.map(s => <Tag key={s.hint} style={{ cursor: 'pointer', padding: '7px 11px' }} onClick={() => submit(s.title, s.hint)}>{s.title}</Tag>)}</Space></div>}
      {messages.map(m => <div className={`message-row ${m.side}`} key={m.id}><div className="bubble">
        <RouteMessage item={m} />
        {m.buttons && <div className="message-actions">{m.buttons.map(b => <Button size="small" key={b.payload} onClick={() => submit(b.title)}>{b.title}</Button>)}</div>}
        {(m.text.match(ticketPattern) || []).map(id => <div className="ticket-highlight" key={id}><b>工单 {id}</b><div style={{ marginTop: 5 }}>{user ? <Link to={`/citizen/tickets/${id}`}>查看工单详情</Link> : <span>登录市民账号后可查看完整办理进度</span>}</div></div>)}
        {m.side === 'bot' && <MessageMetaTags item={m} />}
      </div></div>)}
      {sending && <div className="message-row bot"><div className="bubble"><Spin size="small" /> 正在分析您的需求…</div></div>}</div>
      {failed && <Alert type="warning" showIcon closable message="消息发送失败" action={<Button size="small" icon={<ReloadOutlined />} onClick={() => submit(failed)}>重试</Button>} />}
      <div className="composer"><Input.TextArea aria-label="输入消息" autoSize={{ minRows: 1, maxRows: 4 }} value={input} onChange={e => setInput(e.target.value)} placeholder="描述您的问题，如：博士家人有哪些福利待遇 / 小区路灯坏了三天…" onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); void submit() } }} /><Button aria-label="发送" type="primary" size="large" icon={<SendOutlined />} loading={sending} disabled={!input.trim()} onClick={() => submit()}>发送</Button><Button aria-label="清空" icon={<DeleteOutlined />} onClick={clear} /></div>
    </section>
    {draft && screens.md && <aside className="chat-draft-aside" aria-label="工单草稿"><TicketDraftPanel draft={draft} missing={draftMissing} onChange={setDraft} onSubmitted={handleSubmitted} /></aside>}
  </div>
  {draft && !screens.md && <>
    <Button className="draft-fab" type="primary" shape="circle" size="large" icon={<Badge count={missingCount} offset={[-4, 4]}><FileTextOutlined /></Badge>} onClick={() => setDrawerOpen(true)} />
    <Drawer title="工单草稿" placement="bottom" height="75vh" open={drawerOpen} onClose={() => setDrawerOpen(false)}><TicketDraftPanel draft={draft} missing={draftMissing} onChange={setDraft} onSubmitted={(id) => { handleSubmitted(id); setDrawerOpen(false) }} /></Drawer>
  </>}
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
        description="未发现可绑定的匿名会话工单；新提交的工单将进入“我的工单”。"
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
        description="请稍候，正在将访客会话中的工单关联到当前账号。"
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
        description={boundCount && boundCount > 0 ? `已关联 ${boundCount} 条匿名会话工单；后续工单将进入“我的工单”。` : '工单将进入“我的工单”。'}
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

/** Rewrite legacy Rasa localmode copy that falsely implies a ticket was created. */
export function sanitizeRasaFallbackText(text: string): string {
  const guarded = ensureChineseReply(text)
  const hasRealTicketId = /QT\d{12,16}/i.test(guarded)
  const claimsSuccess = /已收到您的诉求|工单已创建|请前往[“"]?我的工单|后续办理进度/.test(guarded)
  if (claimsSuccess && !hasRealTicketId) {
    return (
      '智能助手暂时不可用，已切换降级通道。系统没有创建真实工单，'
      + '“我的工单”中不会出现新记录。请稍后重试，或登录后在工单页面手动提交诉求。'
    )
  }
  return guarded
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
export function RouteMessage({ item }: { item: ChatItem }) {
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
      <Card size="small" style={{ background: '#f8fffe', border: '1px solid #d9f0ec' }} data-testid="policy-answer-card">
        {banner && <Alert type="warning" showIcon style={{ marginBottom: 10 }} message={banner} />}
        {noEvidence && (
          <Alert type="info" showIcon style={{ marginBottom: 10 }} data-testid="no-evidence-banner" message="未找到可引用政策依据，以下为引导说明，不是政策原文。" />
        )}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{text}</Typography.Paragraph>
        <PolicyCitations citations={citations} noEvidence={noEvidence} compact />
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
