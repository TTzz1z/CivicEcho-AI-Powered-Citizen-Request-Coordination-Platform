import { describe, expect, it } from 'vitest'
import { ensureChineseReply, isChineseDominant, LANGUAGE_FALLBACK } from './languageGuard'

describe('languageGuard', () => {
  it('passes Chinese help text', () => {
    const text = '我可以帮您：\n- 提交投诉、建议、咨询或求助事项'
    expect(isChineseDominant(text)).toBe(true)
    expect(ensureChineseReply(text)).toBe(text)
  })

  it('blocks English helpdesk residue', () => {
    const text = 'I can help you open a service request ticket, or check the status of your open incidents.'
    expect(isChineseDominant(text)).toBe(false)
    expect(ensureChineseReply(text)).toBe(LANGUAGE_FALLBACK)
  })
})
