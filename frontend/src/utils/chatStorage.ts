/**
 * Chat / draft privacy storage helpers.
 *
 * Goals:
 * - TTL on session messages and drafts (default 24h)
 * - Strip long-lived contact fields from drafts
 * - Redact ID / phone / address-like PII in persisted text
 * - Clear on logout / account switch
 * - Multi-tab logout sync via BroadcastChannel + storage event
 * - Compatibly purge legacy cache shapes without savedAt
 */

export const CHAT_CACHE_TTL_MS = 24 * 60 * 60 * 1000

const MESSAGE_PREFIX = 'tingting_chat_'
const DRAFT_PREFIX = 'tingting_chat_draft_'
const SESSION_PREFIX = 'tingting_session_'
const BOUND_PREFIX = 'tingting_bound_'
const PRE_REVIEW_PREFIX = 'tingting_pre_review_draft_'
const SENDER_KEY = 'tingting_sender_id'
const PRIVACY_CLEAR_SIGNAL = 'tingting_privacy_clear'
const PRIVACY_CHANNEL = 'tingting-chat-privacy'

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

/** Redact mainland ID card / mobile / address-like spans before persist. */
export function redactSensitiveText(text: string): string {
  if (!text) return text
  return text
    .replace(/[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]/g, '[身份证已脱敏]')
    .replace(/(?<![0-9])1[3-9]\d{9}(?![0-9])/g, '[手机号已脱敏]')
    .replace(
      /[\u4e00-\u9fa5]{1,12}(?:省|市|自治区|特别行政区)?[\u4e00-\u9fa5]{0,12}(?:市|州|盟|地区)?[\u4e00-\u9fa5]{1,12}(?:区|县|旗|市)[\u4e00-\u9fa5\d\-号楼室单元栋门弄巷街路]{2,48}/g,
      '[地址已脱敏]',
    )
}

function redactValue(value: unknown): unknown {
  if (typeof value === 'string') return redactSensitiveText(value)
  if (Array.isArray(value)) return value.map(redactValue)
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = redactValue(v)
    }
    return out
  }
  return value
}

/** Persist chat messages with TTL envelope and PII redaction. */
export function loadChatMessages<T>(key: string, ttlMs = CHAT_CACHE_TTL_MS): T[] {
  const env = readEnvelope<T[]>(localStorage.getItem(key))
  if (!env || isExpired(env.savedAt, ttlMs) || !Array.isArray(env.data)) {
    localStorage.removeItem(key)
    return []
  }
  return env.data
}

export function saveChatMessages<T>(key: string, messages: T[]): void {
  const redacted = redactValue(messages.slice(-80)) as T[]
  localStorage.setItem(key, JSON.stringify(wrap(redacted)))
}

type DraftLike = object

/** Contact and similar fields must not linger in long-lived browser storage. */
export function sanitizeDraftForStorage<T extends object>(draft: T): T {
  const next: Record<string, unknown> = { ...(draft as Record<string, unknown>) }
  delete next.contact
  delete next.phone
  delete next.mobile
  for (const [k, v] of Object.entries(next)) {
    if (typeof v === 'string') next[k] = redactSensitiveText(v)
  }
  return next as T
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

/**
 * Notify other tabs to clear chat privacy caches.
 * Prefer BroadcastChannel; also poke a localStorage signal for storage-event fallback.
 */
export function broadcastChatPrivacyClear(): void {
  try {
    const channel = new BroadcastChannel(PRIVACY_CHANNEL)
    channel.postMessage({ type: 'clear', at: now() })
    channel.close()
  } catch {
    // BroadcastChannel unavailable — storage signal still helps other tabs.
  }
  try {
    localStorage.setItem(PRIVACY_CLEAR_SIGNAL, String(now()))
    localStorage.removeItem(PRIVACY_CLEAR_SIGNAL)
  } catch {
    // ignore quota / private mode
  }
}

/** Subscribe to multi-tab privacy clear (BroadcastChannel + storage event). */
export function subscribeChatPrivacyClear(onClear: () => void): () => void {
  let channel: BroadcastChannel | null = null
  const handleMessage = (event: MessageEvent) => {
    if (event?.data?.type === 'clear') onClear()
  }
  try {
    channel = new BroadcastChannel(PRIVACY_CHANNEL)
    channel.addEventListener('message', handleMessage)
  } catch {
    channel = null
  }
  const handleStorage = (event: StorageEvent) => {
    if (event.key === PRIVACY_CLEAR_SIGNAL) onClear()
  }
  window.addEventListener('storage', handleStorage)
  return () => {
    channel?.removeEventListener('message', handleMessage)
    channel?.close()
    window.removeEventListener('storage', handleStorage)
  }
}

/** Clear local privacy data and broadcast to other tabs. */
export function clearChatPrivacyStorageAndBroadcast(options?: { keepAnonymousSender?: boolean }): void {
  clearChatPrivacyStorage(options)
  broadcastChatPrivacyClear()
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
  PRIVACY_CLEAR_SIGNAL,
  PRIVACY_CHANNEL,
}
