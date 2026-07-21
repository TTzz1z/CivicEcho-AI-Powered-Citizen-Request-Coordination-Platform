import { describe, expect, it } from 'vitest'
import type { KbAdviceReviewRequest } from '../api/kb'

describe('AiCaseAssistant advice_id contract', () => {
  it('requires advice_id on review payload type', () => {
    const payload: KbAdviceReviewRequest = {
      advice_id: '11111111-2222-3333-4444-555555555555',
      decision: 'adopted',
    }
    expect(payload.advice_id).toHaveLength(36)
    expect(payload.decision).toBe('adopted')
  })
})
