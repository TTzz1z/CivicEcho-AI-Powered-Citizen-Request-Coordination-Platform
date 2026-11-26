const labels = { on_track: '时限正常', due_soon: '即将超时', overdue: '已超时', paused: '计时暂停' } as const
const tones = { on_track: 'ok', due_soon: 'warn', overdue: 'err', paused: 'muted' } as const

export function SlaStatus({ state, remainingSeconds }: { state: keyof typeof labels; remainingSeconds?: number | null }) {
  const minutes = remainingSeconds == null ? null : Math.ceil(Math.abs(remainingSeconds) / 60)
  const duration = minutes == null ? '' : minutes < 60 ? `${minutes} 分钟` : `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
  const label = minutes != null && state !== 'paused'
    ? `${labels[state]} · ${(remainingSeconds ?? 0) < 0 ? '超出' : '剩余'} ${duration}`
    : labels[state]
  return (
    <span className={`ce-status-pill ce-sla-pill tone-${tones[state]}`} aria-label={`SLA ${label}`}>
      <span className="ce-status-dot" aria-hidden="true" />
      <span>{label}</span>
    </span>
  )
}
