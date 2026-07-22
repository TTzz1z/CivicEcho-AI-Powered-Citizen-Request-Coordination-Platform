import { describe, expect, it } from 'vitest'
import { closureTypeLabel } from './closureType'

describe('closureTypeLabel', () => {
  it('covers citizen_confirmed / phone_confirmed / admin_override', () => {
    expect(closureTypeLabel('citizen_confirmed')).toBe('市民确认')
    expect(closureTypeLabel('phone_confirmed')).toBe('电话回访确认')
    expect(closureTypeLabel('admin_override')).toBe('管理员代办结')
  })
})
