import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  CHAT_CACHE_TTL_MS,
  clearChatPrivacyOnAccountSwitch,
  clearChatPrivacyStorage,
  loadChatDraft,
  loadChatMessages,
  saveChatDraft,
  saveChatMessages,
  sanitizeDraftForStorage,
} from './chatStorage'

function mockStorage() {
  const store = new Map<string, string>()
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() { return store.size },
    _store: store,
  }
}

describe('chatStorage privacy', () => {
  beforeEach(() => {
    const ls = mockStorage()
    const ss = mockStorage()
    vi.stubGlobal('localStorage', ls)
    vi.stubGlobal('sessionStorage', ss)
  })

  it('sanitizes contact fields before persist', () => {
    const sanitized = sanitizeDraftForStorage({
      request_type: '投诉',
      description: '路灯坏了',
      contact: '13800000000',
      phone: '139',
    })
    expect(sanitized.contact).toBeUndefined()
    expect(sanitized.phone).toBeUndefined()
    expect(sanitized.description).toBe('路灯坏了')
  })

  it('expires legacy unversioned cache and removes it', () => {
    localStorage.setItem('tingting_chat_web-anon-1', JSON.stringify([{ id: '1', text: 'hi' }]))
    expect(loadChatMessages('tingting_chat_web-anon-1')).toEqual([])
    expect(localStorage.getItem('tingting_chat_web-anon-1')).toBeNull()
  })

  it('loads messages within TTL and drops after expiry', () => {
    const key = 'tingting_chat_web-user-1'
    saveChatMessages(key, [{ id: 'a', text: 'ok' }])
    expect(loadChatMessages(key)).toEqual([{ id: 'a', text: 'ok' }])

    const raw = JSON.parse(localStorage.getItem(key)!)
    raw.savedAt = Date.now() - CHAT_CACHE_TTL_MS - 1000
    localStorage.setItem(key, JSON.stringify(raw))
    expect(loadChatMessages(key)).toEqual([])
    expect(localStorage.getItem(key)).toBeNull()
  })

  it('does not persist contact on draft save', () => {
    const key = 'tingting_chat_draft_web-user-1'
    saveChatDraft(key, { description: 'x', contact: '13800000000' })
    const loaded = loadChatDraft<{ description?: string; contact?: string }>(key)
    expect(loaded?.description).toBe('x')
    expect(loaded?.contact).toBeUndefined()
    expect(localStorage.getItem(key)).not.toContain('13800000000')
  })

  it('clears chat privacy keys on logout helper', () => {
    localStorage.setItem('tingting_chat_web-user-9', 'x')
    localStorage.setItem('tingting_chat_draft_web-user-9', 'y')
    localStorage.setItem('tingting_pre_review_draft_9', 'z')
    localStorage.setItem('tingting_sender_id', 'anon')
    sessionStorage.setItem('tingting_session_web-user-9', 's')
    sessionStorage.setItem('tingting_bound_9', '1')
    clearChatPrivacyStorage()
    expect(localStorage.getItem('tingting_chat_web-user-9')).toBeNull()
    expect(localStorage.getItem('tingting_chat_draft_web-user-9')).toBeNull()
    expect(localStorage.getItem('tingting_pre_review_draft_9')).toBeNull()
    expect(localStorage.getItem('tingting_sender_id')).toBeNull()
    expect(sessionStorage.getItem('tingting_session_web-user-9')).toBeNull()
    expect(sessionStorage.getItem('tingting_bound_9')).toBeNull()
  })

  it('clears previous account keys on account switch', () => {
    localStorage.setItem('tingting_chat_web-user-1', 'old')
    localStorage.setItem('tingting_chat_draft_web-user-1', 'old-draft')
    localStorage.setItem('tingting_chat_web-user-1__abc', 'thread')
    localStorage.setItem('tingting_chat_index_web-user-1', 'idx')
    clearChatPrivacyOnAccountSwitch(1, 2)
    expect(localStorage.getItem('tingting_chat_web-user-1')).toBeNull()
    expect(localStorage.getItem('tingting_chat_draft_web-user-1')).toBeNull()
    expect(localStorage.getItem('tingting_chat_web-user-1__abc')).toBeNull()
    expect(localStorage.getItem('tingting_chat_index_web-user-1')).toBeNull()
  })

  it('tracks multiple conversations and migrates legacy single-thread cache', async () => {
    const {
      conversationMessageKey,
      loadChatMessages,
      loadConversationIndex,
      migrateLegacyChatIfNeeded,
      saveChatMessages,
      touchConversationFromMessages,
      removeConversation,
    } = await import('./chatStorage')
    const sender = 'web-user-42'
    const legacy = [{ id: '1', side: 'user', text: '路灯坏了' }]
    saveChatMessages(`tingting_chat_${sender}`, legacy)
    const sessionId = 'sess-legacy'
    migrateLegacyChatIfNeeded(sender, sessionId)
    expect(localStorage.getItem(`tingting_chat_${sender}`)).toBeNull()
    expect(loadChatMessages(conversationMessageKey(sender, sessionId))).toEqual(legacy)
    expect(loadConversationIndex(sender)[0]?.id).toBe(sessionId)

    const second = 'sess-2'
    saveChatMessages(conversationMessageKey(sender, second), [{ id: '2', side: 'user', text: '咨询政策' }])
    touchConversationFromMessages(sender, second, [{ side: 'user', text: '咨询政策' }])
    expect(loadConversationIndex(sender).map((c) => c.id)).toEqual([second, sessionId])
    removeConversation(sender, second)
    expect(loadConversationIndex(sender).map((c) => c.id)).toEqual([sessionId])
    expect(localStorage.getItem(conversationMessageKey(sender, second))).toBeNull()
  })

  it('redacts id card and phone in persisted messages', async () => {
    const { redactSensitiveText, saveChatMessages, loadChatMessages } = await import('./chatStorage')
    expect(redactSensitiveText('身份证110101199001011234 手机13812345678')).toContain('[身份证已脱敏]')
    expect(redactSensitiveText('请联系13812345678')).toContain('[手机号已脱敏]')
    const key = 'tingting_chat_web-user-pii'
    saveChatMessages(key, [{ id: '1', text: '我的手机是13812345678' }])
    const loaded = loadChatMessages<{ id: string; text: string }>(key)
    expect(loaded[0]?.text).toContain('[手机号已脱敏]')
    expect(JSON.stringify(loaded)).not.toContain('13812345678')
  })

  it('broadcasts multi-tab privacy clear via BroadcastChannel', async () => {
    type Handler = (event: MessageEvent) => void
    const channels: Array<{ name: string; handlers: Handler[]; closed: boolean }> = []
    class FakeBroadcastChannel {
      name: string
      handlers: Handler[] = []
      closed = false
      constructor(name: string) {
        this.name = name
        channels.push(this)
      }
      postMessage(data: unknown) {
        for (const ch of channels) {
          if (ch === this || ch.closed || ch.name !== this.name) continue
          for (const handler of ch.handlers) handler({ data } as MessageEvent)
        }
      }
      addEventListener(_type: string, handler: Handler) {
        this.handlers.push(handler)
      }
      removeEventListener(_type: string, handler: Handler) {
        this.handlers = this.handlers.filter((h) => h !== handler)
      }
      close() {
        this.closed = true
      }
    }
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)

    const { clearChatPrivacyStorageAndBroadcast, subscribeChatPrivacyClear, chatStorageKeys } = await import('./chatStorage')
    expect(chatStorageKeys.PRIVACY_CLEAR_SIGNAL).toBe('tingting_privacy_clear')
    expect(chatStorageKeys.PRIVACY_CHANNEL).toBe('tingting-chat-privacy')
    const onClear = vi.fn()
    const unsubscribe = subscribeChatPrivacyClear(onClear)
    localStorage.setItem('tingting_chat_web-user-x', 'keep-until-clear')
    clearChatPrivacyStorageAndBroadcast()
    expect(localStorage.getItem('tingting_chat_web-user-x')).toBeNull()
    expect(onClear).toHaveBeenCalled()
    unsubscribe()
  })
})
