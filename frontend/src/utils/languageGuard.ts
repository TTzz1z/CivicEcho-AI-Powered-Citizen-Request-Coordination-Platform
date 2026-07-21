/** Strict Chinese language check for citizen-facing bot bubbles. */

const FORBIDDEN_ENGLISH = [
  'I can help you open a service request ticket',
  'Open an incident',
  'Help me reset my password',
  "I'm having a issue with my email",
  "What's the status of the ticket I opened",
  'What is your email address',
  'I am a bot, powered by Rasa',
]

const CJK_RE = /[\u4e00-\u9fff]/g
const LATIN_WORD_RE = /[A-Za-z]{3,}/g
const ALLOW_LATIN_RE = /\b(QT\d{12,16}|PDF|API|SLA|RAG|LLM|DeepSeek|HTTP|HTTPS|OK|ID)\b/gi

export const LANGUAGE_FALLBACK =
  '我主要提供政策咨询、办事指南、投诉建议、公共事务求助和工单进度查询。请用中文描述您的需求。'

export function isChineseDominant(text: string): boolean {
  if (!text || !text.trim()) return true
  const lowered = text.toLowerCase()
  if (FORBIDDEN_ENGLISH.some(p => lowered.includes(p.toLowerCase()))) return false
  const scrubbed = text.replace(ALLOW_LATIN_RE, '')
  const cjk = scrubbed.match(CJK_RE)?.length ?? 0
  const latin = scrubbed.match(LATIN_WORD_RE) ?? []
  if (latin.length === 0) return true
  if (cjk === 0 && latin.length >= 3) return false
  if (latin.length >= 5 && cjk < latin.length) return false
  return true
}

export function ensureChineseReply(text: string, fallback = LANGUAGE_FALLBACK): string {
  return isChineseDominant(text) ? text : fallback
}
