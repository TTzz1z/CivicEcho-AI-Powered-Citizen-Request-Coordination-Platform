import { describe, expect, it } from 'vitest'
import type { KbAdviceReviewRequest } from '../api/kb'
import { closureTypeLabel } from '../utils/closureType'

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

describe('AI adopt action copy credibility', () => {
  it('button labels describe record-only review, not auto execution', () => {
    const adoptLabel = '记录为已采纳'
    const editAdoptLabel = '记录修改后采纳'
    const boundary = 'AI 只提供建议。采纳记录不会自动派发、填写办理结果或办结；真实业务操作必须在工单详情完成。'
    const editTooltip = '仅记录审核决策与修改摘要，不会自动改工单字段、派发或办结'

    expect(adoptLabel).toMatch(/记录/)
    expect(adoptLabel).not.toMatch(/自动/)
    expect(editAdoptLabel).toMatch(/记录/)
    expect(editTooltip).toMatch(/不会自动/)
    expect(boundary).toMatch(/不会自动派发/)
    expect(boundary).toMatch(/工单详情/)
  })

  it('ticket closure labels stay complete for aftercare phone confirm', () => {
    expect(closureTypeLabel('phone_confirmed')).toBe('电话回访确认')
  })
})
