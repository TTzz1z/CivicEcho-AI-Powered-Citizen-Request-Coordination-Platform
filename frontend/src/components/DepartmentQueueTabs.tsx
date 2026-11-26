import { Tabs } from 'antd'
import type { TicketFilters } from '../types'

const scopes = [
  { key: 'all', label: '全部可见工单', filters: {} },
  { key: 'assigned', label: '待办理', filters: { status: 'assigned' } },
  { key: 'processing', label: '办理中', filters: { status: 'processing' } },
  { key: 'due_soon', label: '即将超时', filters: { sla_state: 'due_soon' } },
  { key: 'overdue', label: '已超时', filters: { sla_state: 'overdue' } },
  { key: 'returned', label: '被退回', filters: { work_queue: 'returned' } },
] satisfies { key: string; label: string; filters: Pick<TicketFilters, 'status' | 'sla_state' | 'work_queue'> }[]

export function DepartmentQueueTabs({ filters, onChange }: {
  filters: TicketFilters
  onChange: (filters: TicketFilters) => void
}) {
  const active = scopes.find((scope) => {
    const target: Pick<TicketFilters, 'status' | 'sla_state' | 'work_queue'> = scope.filters
    return target.status === filters.status && target.sla_state === filters.sla_state && target.work_queue === filters.work_queue
  })
  return <div className="department-queue-tabs">
    <Tabs aria-label="部门工单队列" activeKey={active?.key ?? 'custom'}
      items={active ? scopes : [...scopes, { key: 'custom', label: '组合筛选' }]}
      onChange={(key) => {
        const scope = scopes.find((entry) => entry.key === key)
        if (scope) onChange({ ...filters, status: undefined, sla_state: undefined, work_queue: undefined, ...scope.filters, page: 1 })
      }} />
  </div>
}
