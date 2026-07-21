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
    clearChatPrivacyOnAccountSwitch(1, 2)
    expect(localStorage.getItem('tingting_chat_web-user-1')).toBeNull()
    expect(localStorage.getItem('tingting_chat_draft_web-user-1')).toBeNull()
  })
})
