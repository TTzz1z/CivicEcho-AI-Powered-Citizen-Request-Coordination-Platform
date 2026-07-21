import { api, createRequestId } from './client'
import type { RasaMessage } from '../types'
import { ensureChineseReply } from '../utils/languageGuard'

/** Prefer backend proxy (language-guarded). Falls back to nginx /rasa/ only if proxy fails. */
export async function sendRasaMessage(sender: string, message: string): Promise<RasaMessage[]> {
  const requestId = createRequestId()
  try {
    const { data } = await api.post<RasaMessage[]>('/chat/rasa', {
      sender,
      message,
      metadata: { request_id: requestId },
    }, { timeout: 20_000, headers: { 'X-Request-ID': requestId } })
    return (data || []).map(m => ({
      ...m,
      text: m.text ? ensureChineseReply(m.text) : m.text,
    }))
  } catch {
    // Direct Rasa (nginx) fallback — still apply client-side language guard
    const axios = (await import('axios')).default
    const { data } = await axios.post<RasaMessage[]>(
      '/rasa/webhooks/rest/webhook',
      { sender, message, metadata: { request_id: requestId } },
      { timeout: 20_000, headers: { 'X-Request-ID': requestId } },
    )
    return (data || []).map(m => ({
      ...m,
      text: m.text ? ensureChineseReply(m.text) : m.text,
    }))
  }
}
