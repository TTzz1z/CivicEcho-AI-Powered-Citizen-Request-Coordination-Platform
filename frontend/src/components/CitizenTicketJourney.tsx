import { Steps } from 'antd'
import type { TicketStatus } from '../types'

const milestones: { status: TicketStatus; title: string }[] = [
  { status: 'pending', title: '登记' }, { status: 'accepted', title: '受理' },
  { status: 'assigned', title: '派发' }, { status: 'processing', title: '部门办理' },
  { status: 'resolved', title: '结果待确认' },
  { status: 'closed', title: '办结' },
]
const stepIndex: Record<TicketStatus, number> = {
  pending: 0, accepted: 1, assigned: 2, processing: 3, resolved: 4, closed: 5, rejected: 1,
}

export function CitizenTicketJourney({ status }: { status: TicketStatus }) {
  const items = milestones.map((item) => ({
    title: status === 'rejected' && item.status === 'accepted' ? '不予受理' : item.title,
  }))
  return <section className="citizen-journey" aria-label="诉求办理进度">
    <Steps current={stepIndex[status]} status={status === 'rejected' ? 'error' : status === 'closed' ? 'finish' : 'process'}
      size="small" items={status === 'rejected' ? items.slice(0, 2) : items} />
  </section>
}
