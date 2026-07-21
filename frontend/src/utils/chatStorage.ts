/**
 * Chat / draft privacy storage helpers.
 *
 * Goals:
 * - TTL on session messages and drafts (default 24h)
 * - Strip long-lived contact fields from drafts
 * - Clear on logout / account switch
 * - Compatibly purge legacy cache shapes without savedAt
 */

export const CHAT_CACHE_TTL_MS = 24 * 60 * 60 * 1000

const MESSAGE_PREFIX = 'tingting_chat_'
const DRAFT_PREFIX = 'tingting_chat_draft_'
const SESSION_PREFIX = 'tingting_session_'
const BOUND_PREFIX = 'tingting_bound_'
const PRE_REVIEW_PREFIX = 'tingting_pre_review_draft_'
const SENDER_KEY = 'tingting_sender_id'

type Envelope<T> = { v: 1; savedAt: number; data: T }

function now() {
  return Date.now()
}

function isExpired(savedAt: number, ttlMs = CHAT_CACHE_TTL_MS): boolean {
  return !Number.isFinite(savedAt) || now() - savedAt > ttlMs
}

function wrap<T>(data: T): Envelope<T> {
  return { v: 1, savedAt: now(), data }
}

function readEnvelope<T>(raw: string | null): Envelope<T> | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && parsed.v === 1 && 'data' in parsed && typeof parsed.savedAt === 'number') {
      return parsed as Envelope<T>
    }
    // Legacy: bare array/object without envelope → treat as expired so it is purged.
    return null
  } catch {
    return null
  }
}

/** Persist chat messages with TTL envelope. */
export function loadChatMessages<T>(key: string, ttlMs = CHAT_CACHE_TTL_MS): T[] {
  const env = readEnvelope<T[]>(localStorage.getItem(key))
  if (!env || isExpired(env.savedAt, ttlMs) || !Array.isArray(env.data)) {
    localStorage.removeItem(key)
    return []
  }
  return env.data
}

export function saveChatMessages<T>(key: string, messages: T[]): void {
  localStorage.setItem(key, JSON.stringify(wrap(messages.slice(-80))))
}

type DraftLike = object

/** Contact and similar fields must not linger in long-lived browser storage. */
export function sanitizeDraftForStorage<T extends object>(draft: T): T {
  const next = { ...draft } as T & Record<string, unknown>
  delete next.contact
  delete next.phone
  delete next.mobile
  return next
}

export function loadChatDraft<T extends object>(key: string, ttlMs = CHAT_CACHE_TTL_MS): T | null {
  const env = readEnvelope<T>(localStorage.getItem(key))
  if (!env || isExpired(env.savedAt, ttlMs) || !env.data || typeof env.data !== 'object') {
    localStorage.removeItem(key)
    return null
  }
  return sanitizeDraftForStorage(env.data)
}

export function saveChatDraft<T extends object>(key: string, draft: T): void {
  localStorage.setItem(key, JSON.stringify(wrap(sanitizeDraftForStorage(draft))))
}

export function clearKey(storage: Storage, key: string): void {
  storage.removeItem(key)
}

function clearPrefix(storage: Storage, prefix: string): void {
  const keys: string[] = []
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i)
    if (key && key.startsWith(prefix)) keys.push(key)
  }
  keys.forEach((k) => storage.removeItem(k))
}

/** Clear chat privacy data on logout or account switch. */
export function clearChatPrivacyStorage(options?: { keepAnonymousSender?: boolean }): void {
  clearPrefix(localStorage, MESSAGE_PREFIX)
  clearPrefix(localStorage, DRAFT_PREFIX)
  clearPrefix(localStorage, PRE_REVIEW_PREFIX)
  clearPrefix(sessionStorage, SESSION_PREFIX)
  clearPrefix(sessionStorage, BOUND_PREFIX)
  if (!options?.keepAnonymousSender) {
    localStorage.removeItem(SENDER_KEY)
  }
}

/** When switching authenticated users, drop previous user's chat/draft keys. */
export function clearChatPrivacyOnAccountSwitch(previousUserId?: number | null, nextUserId?: number | null): void {
  if (previousUserId && previousUserId !== nextUserId) {
    const prevSender = `web-user-${previousUserId}`
    localStorage.removeItem(`${MESSAGE_PREFIX}${prevSender}`)
    localStorage.removeItem(`${DRAFT_PREFIX}${prevSender}`)
    localStorage.removeItem(`${PRE_REVIEW_PREFIX}${previousUserId}`)
    sessionStorage.removeItem(`${SESSION_PREFIX}${prevSender}`)
    sessionStorage.removeItem(`${BOUND_PREFIX}${previousUserId}`)
  }
  if (previousUserId && nextUserId && previousUserId !== nextUserId) {
    // Also drop anonymous sender caches so the new account does not inherit drafts.
    clearChatPrivacyStorage({ keepAnonymousSender: false })
  }
}

export const chatStorageKeys = {
  MESSAGE_PREFIX,
  DRAFT_PREFIX,
  SESSION_PREFIX,
  BOUND_PREFIX,
  PRE_REVIEW_PREFIX,
  SENDER_KEY,
}
