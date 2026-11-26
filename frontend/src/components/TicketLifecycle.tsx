import dayjs from 'dayjs'
import type { TicketDetail } from '../types'
import { TicketStatusTag } from './TicketStatusTag'

const eventLabels: Record<string, string> = {
  create: '诉求登记', accept: '受理', assign: '派发部门', process: '开始办理',
  reject: '不予受理', close: '办结', feedback: '市民评价',
  submit_appeal: '提交申诉', approve_appeal: '批准申诉并重办',
  appeal_rejected: '申诉审核未通过', appeal_completed: '申诉重新办理完成', follow_up: '回访完成',
  phone_follow_up_close: '电话回访并办结', request_supplement: '通知补充材料',
  submit_supplement: '提交补充材料', review_resolve: '坐席复核并发布结果',
  submit_for_review: '主办部门汇总待审核', return_to_department: '坐席退回部门',
  open_dispute: '发起归属争议', resolve_dispute: '归属争议已协调',
}

const feedbackLabels = { satisfied: '满意', mostly_satisfied: '基本满意', dissatisfied: '不满意' }
const orderLabels = { primary: '主办', support: '协办', review: '复核' }

export function TicketLifecycle({ ticket, showWorkOrders }: { ticket: TicketDetail; showWorkOrders: boolean }) {
  const restarted = ticket.history.filter(event => event.operation_type === 'approve_appeal')
  const firstRound = Math.max(1, ticket.handling_round - restarted.length)
  const roundAt = (date: string) => firstRound + restarted.filter(event => Date.parse(event.created_at) <= Date.parse(date)).length
  const events = [
    ...ticket.history.filter(event => event.operation_type !== 'citizen_feedback').map((event, index) => ({
      id: `history-${index}`, date: event.created_at, round: roundAt(event.created_at),
      title: eventLabels[event.operation_type] ?? '办理记录',
      content: event.content || event.remark, status: event.current_status,
    })),
    ...(showWorkOrders ? ticket.work_orders.flatMap(order => order.history.map((event, index) => ({
      id: `order-${order.id}-${index}`, date: event.created_at, round: roundAt(event.created_at),
      title: `${orderLabels[order.task_type]} · ${order.department_name || order.work_order_no}`,
      content: event.content, status: undefined,
    }))) : []),
    ...ticket.feedbacks.map((feedback, index) => ({
      id: `feedback-${index}`, date: feedback.created_at, round: roundAt(feedback.created_at),
      title: `市民评价 · ${feedbackLabels[feedback.rating]}${feedback.result === 'closed' ? ' · 确认办结' : ''}`, content: feedback.comment, status: undefined,
    })),
    ...(ticket.aftercare_events ?? []).map((event, index) => ({
      id: `aftercare-${index}`, date: event.created_at, round: event.handling_round ?? roundAt(event.created_at),
      title: eventLabels[event.kind], content: null, status: undefined,
    })),
  ].sort((left, right) => Date.parse(right.date) - Date.parse(left.date))

  if (!events.length) return <p className="ticket-event-empty">暂无办理记录</p>
  const groups = new Map<number, typeof events>()
  for (const event of events) {
    const group = groups.get(event.round) ?? []
    group.push(event)
    groups.set(event.round, group)
  }

  return <div className="ticket-lifecycle">
    {[...groups].map(([round, entries]) => (
      <details key={round} open={round === events[0].round}>
        <summary>第 {round} 轮办理 · {entries.length} 条</summary>
        <ol className="ticket-event-list">
          {entries.map(event => <li key={event.id}>
            <div className="ticket-event-title">
              <strong>{event.title}</strong>
              {event.status && <TicketStatusTag status={event.status} />}
            </div>
            <time dateTime={event.date}>{dayjs(event.date).format('YYYY-MM-DD HH:mm')}</time>
            {event.content && <p>{event.content}</p>}
          </li>)}
        </ol>
      </details>
    ))}
  </div>
}
