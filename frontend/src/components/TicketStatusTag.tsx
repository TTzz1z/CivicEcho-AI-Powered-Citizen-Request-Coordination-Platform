import type { TicketStatus } from '../types'

const meta: Record<TicketStatus, { label: string; tone: string }> = {
  pending: { label: '待受理', tone: 'warn' },
  accepted: { label: '已受理', tone: 'accent' },
  assigned: { label: '已派发', tone: 'accent' },
  processing: { label: '处理中', tone: 'accent' },
  resolved: { label: '待市民确认', tone: 'purple' },
  closed: { label: '已办结', tone: 'ok' },
  rejected: { label: '不予受理', tone: 'muted' },
}

export function TicketStatusTag({ status, label }: { status: TicketStatus; label?: string }) {
  const item = meta[status]
  return (
    <span className={`ce-status-pill tone-${item.tone}`}>
      <span className="ce-status-dot" aria-hidden="true" />
      <span>{label || item.label}</span>
    </span>
  )
}

export const statusOptions = Object.entries(meta).map(([value, item]) => ({ value, label: item.label }))
