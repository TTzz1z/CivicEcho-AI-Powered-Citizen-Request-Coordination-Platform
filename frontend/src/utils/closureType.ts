export type ClosureType = 'citizen_confirmed' | 'phone_confirmed' | 'admin_override'

const CLOSURE_TYPE_LABELS: Record<ClosureType, string> = {
  citizen_confirmed: '市民确认',
  phone_confirmed: '电话回访确认',
  admin_override: '管理员代办结',
}

/** 办结/关闭方式完整中文标签；未知值回退原文，空值显示 — */
export function closureTypeLabel(value: string | null | undefined): string {
  if (!value) return '—'
  if (value in CLOSURE_TYPE_LABELS) {
    return CLOSURE_TYPE_LABELS[value as ClosureType]
  }
  return value
}
