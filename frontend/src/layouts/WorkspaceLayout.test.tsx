import { describe, expect, it } from 'vitest'
import { menuByRole } from '../layouts/WorkspaceLayout'
import { closureTypeLabel } from '../utils/closureType'

describe('admin menu naming', () => {
  it('keeps distinct governance vs document maintenance entries', () => {
    const labels = menuByRole.admin.map((item) => item.label)
    expect(labels).toContain('知识库治理审核')
    expect(labels).toContain('部门文档维护')
    expect(labels).not.toContain('AI 知识库')
    expect(labels).not.toContain('文档管理')
    const governance = menuByRole.admin.find((item) => item.label === '知识库治理审核')
    const docs = menuByRole.admin.find((item) => item.label === '部门文档维护')
    expect(governance?.key).toBe('/admin/kb')
    expect(docs?.key).toBe('/department/kb')
  })
})

describe('closureTypeLabel', () => {
  it('maps all supported closure types including phone follow-up', () => {
    expect(closureTypeLabel('citizen_confirmed')).toBe('市民确认')
    expect(closureTypeLabel('phone_confirmed')).toBe('电话回访确认')
    expect(closureTypeLabel('admin_override')).toBe('管理员代办结')
    expect(closureTypeLabel(null)).toBe('—')
    expect(closureTypeLabel(undefined)).toBe('—')
  })

  it('does not render phone follow-up closure as unknown', () => {
    expect(closureTypeLabel('phone_confirmed')).not.toMatch(/未知/)
    expect(closureTypeLabel('phone_confirmed')).not.toBe('—')
  })
})
