import { Empty, Grid, Table, Typography } from 'antd'
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table'
import dayjs from 'dayjs'
import { Link, useLocation } from 'react-router-dom'
import type { Ticket, TicketFilters } from '../types'
import { SlaStatus } from './SlaStatus'
import { TicketStatusTag } from './TicketStatusTag'
const priority:Record<string,{label:string;color:string}>={normal:{label:'普通',color:'#52525b'},expedited:{label:'加急',color:'#b45309'},urgent:{label:'紧急',color:'#be123c'},major:{label:'重大事件',color:'#9f1239'}}
export function TicketTable({ items, total, loading, filters, onChange, basePath, selectable = false, selectedRowKeys, onSelectionChange }: {
  items?: Ticket[]
  total?: number
  loading: boolean
  filters: TicketFilters
  onChange: (next: TicketFilters) => void
  basePath: string
  selectable?: boolean
  selectedRowKeys?: string[]
  onSelectionChange?: (keys: string[], rows: Ticket[]) => void
}) {
  const screens = Grid.useBreakpoint()
  const compact = !screens.md
  const { search } = useLocation()
  const columns: ColumnsType<Ticket> = [
    { title: '工单编号', dataIndex: 'ticket_id', width: compact ? undefined : 162, render: (id, row) => <>
      <Link className="ticket-link workspace-reference" to={`${basePath}/${id}`} state={{ ticketListSearch: search }}>{id}</Link>
      {compact && <div className="ticket-compact-description">{row.description}</div>}
    </> },
    { title: '分类', dataIndex: 'category_name', width: 100, render: (value) => value || '待确认' },
    { title: '诉求摘要', dataIndex: 'description', render: (value) => <div className="ticket-summary" title={value}>{value}</div> },
    { title: '状态', dataIndex: 'status', width: compact ? 92 : 112, render: (value, row) => <div className="ticket-compact-state">
      <TicketStatusTag status={value} label={row.status_label} />
      {compact && <SlaStatus state={row.sla_state} remainingSeconds={row.remaining_seconds} />}
    </div> },
    { title: '优先级', dataIndex: 'priority', width: 88, sorter: true, render: (value) => <Typography.Text style={{ color: priority[value]?.color, fontWeight: 600 }}>{priority[value]?.label || value}</Typography.Text> },
    { title: 'SLA', dataIndex: 'sla_state', width: 152, render: (value, row) => <SlaStatus state={value} remainingSeconds={row.remaining_seconds} /> },
    { title: '催办', dataIndex: 'reminder_count', width: 64, render: (value) => value ? `${value} 次` : '—' },
    { title: '责任部门', dataIndex: 'department_name', width: 104, render: (value) => value || '待派发' },
    { title: '创建时间', dataIndex: 'created_at', width: 155, sorter: true, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
  ]
  const change = (page: TablePaginationConfig, _filters: unknown, sorter: unknown) => {
    const sort = sorter as { field?: string; order?: string }
    onChange({ ...filters, page: page.current, page_size: page.pageSize,
      sort: sort.field === 'priority' ? 'priority' : 'created_at', order: sort.order === 'ascend' ? 'asc' : 'desc' })
  }
  return <div onKeyDown={event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return
    if (!(event.target instanceof HTMLAnchorElement) || !event.target.classList.contains('ticket-link')) return
    if (event.key !== 'j' && event.key !== 'k') return
    const links = [...event.currentTarget.querySelectorAll<HTMLAnchorElement>('a.ticket-link')]
    const next = links[links.indexOf(event.target) + (event.key === 'j' ? 1 : -1)]
    if (next) { event.preventDefault(); next.focus() }
  }}>
  <Table rowKey="ticket_id" size={compact ? 'small' : 'middle'} className="workspace-ticket-table"
    rowSelection={selectable ? {
      selectedRowKeys,
      columnWidth: compact ? 36 : 48,
      preserveSelectedRowKeys: false,
      onChange: (keys, rows) => onSelectionChange?.(keys.map(String), rows),
    } : undefined}
    columns={compact ? columns.filter((column) => 'dataIndex' in column && ['ticket_id', 'status'].includes(String(column.dataIndex))) : columns}
    dataSource={items || []} loading={loading} onChange={change} scroll={compact ? undefined : { x: 1050 }}
    locale={{ emptyText: <Empty description="当前条件下暂无工单" /> }}
    pagination={{ current: filters.page || 1, pageSize: filters.page_size || 20, total, showSizeChanger: !compact, showTotal: (count) => `共 ${count} 条` }} />
  </div>
}
