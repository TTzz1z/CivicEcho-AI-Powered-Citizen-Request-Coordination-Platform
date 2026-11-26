import { Button, Card, Progress, Space, Table } from 'antd'
import { AuditOutlined, ClockCircleOutlined, FileTextOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { getDashboard } from '../api/admin'
import { ChartPanel } from '../components/ChartPanel'
import { OperationsTrend } from '../components/OperationsTrend'
import { PageHeader } from '../components/PageHeader'
import { TicketStatusTag } from '../components/TicketStatusTag'
import { WorkspaceError, WorkspaceLoading } from '../components/WorkspaceState'
import { WorkspaceTableRegion } from '../components/WorkspaceTableRegion'

const metricIcons = { total: FileTextOutlined, due_soon: ClockCircleOutlined, overdue: WarningOutlined }
const metricLinks: Record<string, string> = {
  total: '/admin/tickets', due_soon: '/admin/tickets?sla_state=due_soon', overdue: '/admin/tickets?sla_state=overdue',
}

export function DashboardPage() {
  const query = useQuery({ queryKey: ['admin', 'dashboard'], queryFn: getDashboard, refetchInterval: 60_000 })
  const data = query.data
  const statusOption = useMemo<EChartsOption>(() => ({
    animation: false,
    tooltip: { trigger: 'item' },
    color: ['#09090b', '#2563eb', '#10b981', '#d4d7dd', '#f59e0b', '#e11d48', '#71717a'],
    series: [{ type: 'pie', radius: ['66%', '84%'], center: ['50%', '50%'], label: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 2 }, data: data?.status_distribution ?? [] }],
  }), [data])
  const typeOption = useMemo<EChartsOption>(() => ({
    animation: false,
    tooltip: { trigger: 'axis' }, grid: { left: 44, right: 16, top: 18, bottom: 36 },
    xAxis: { type: 'category', data: data?.request_type_distribution.map((slice) => slice.name) ?? [], axisLabel: { hideOverlap: true, color: '#71717a' }, axisLine: { lineStyle: { color: '#eceef2' } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#8b92a0' }, splitLine: { lineStyle: { color: '#f1f2f5' } } },
    series: [{ type: 'bar', barMaxWidth: 28, data: data?.request_type_distribution.map((slice) => slice.value) ?? [],
      itemStyle: { color: '#09090b', borderRadius: [5, 5, 0, 0] } }],
  }), [data])

  return <div className="ops-page">
    <PageHeader title="运营总览" description="跟踪诉求登记、办理时限与部门处理情况。"
      extra={<Space wrap>
        <Link className="workspace-action-link" to="/admin/audit"><AuditOutlined aria-hidden /> 审计日志</Link>
        <Button icon={<ReloadOutlined aria-hidden />} loading={query.isFetching} onClick={() => void query.refetch()}>刷新数据</Button>
      </Space>} />
    {!data ? query.isError ? <WorkspaceError error={query.error} fallback="运营数据加载失败。" retry={() => void query.refetch()} />
      : <Card className="surface"><WorkspaceLoading label="加载运营数据" /></Card> : <>
      {query.isError && <WorkspaceError error={query.error} fallback="刷新失败，暂时展示上一次加载的数据。" retry={() => void query.refetch()} />}
      <section className="ops-metrics" aria-label="运营指标">
        {data.metrics.map((metric) => {
          const Icon = metricIcons[metric.key as keyof typeof metricIcons] ?? ClockCircleOutlined
          const target = metricLinks[metric.key]
          return <article key={metric.key} className={`ops-metric ops-metric-${metric.key}`}>
            <div className="ops-metric-heading"><span>{metric.label}</span><Icon aria-hidden /></div>
            <div className="ops-metric-value">{metric.has_samples === false ? <span aria-label="暂无样本">—</span> :
              <>{metric.value.toLocaleString('zh-CN')} <small>{metric.unit}</small></>}</div>
            {target && <Link to={target}>查看{metric.key === 'total' ? '工单' : metric.label + '工单'}</Link>}
          </article>
        })}
      </section>
      <div className="ops-primary">
        <OperationsTrend points={data.intake_trend} timezone={data.trend_timezone} />
        <Card title="工单状态分布" className="surface ops-status">
          <ChartPanel label="工单状态分布环形图" option={statusOption} empty={!data.status_distribution.length} />
          <ul className="ops-distribution">{data.status_distribution.map((slice) => (
            <li key={slice.name}><span>{slice.name}</span><strong>{slice.value}</strong></li>
          ))}</ul>
        </Card>
      </div>
      <div className="ops-secondary">
        <Card title="部门办理时限" className="surface" styles={{ body: { padding: 0 } }}>
          <WorkspaceTableRegion label="部门 SLA 统计">
            <Table size="small" rowKey="department_name" pagination={false} dataSource={data.department_sla} scroll={{ x: 450 }} columns={[
              { title: '责任部门', dataIndex: 'department_name', rowScope: 'row' },
              { title: '纳入统计', dataIndex: 'total', align: 'right' },
              { title: '超时工单', dataIndex: 'overdue', align: 'right' },
              { title: '超时率', dataIndex: 'overdue_rate', width: 143, render: (value) =>
                <Progress percent={value} size="small" strokeColor={value > 0 ? '#e11d48' : '#09090b'} /> },
            ]} />
          </WorkspaceTableRegion>
        </Card>
        <Card title="诉求类型分布" className="surface">
          <ChartPanel label="各诉求类型工单柱状图" option={typeOption} empty={!data.request_type_distribution.length} />
          <ul className="ops-distribution">{data.request_type_distribution.map((slice) => (
            <li key={slice.name}><span>{slice.name}</span><strong>{slice.value}</strong></li>
          ))}</ul>
        </Card>
      </div>
      <Card title="最近工单" className="surface" styles={{ body: { padding: 0 } }}>
        <WorkspaceTableRegion label="最近工单列表">
          <Table size="small" rowKey="ticket_id" pagination={false} scroll={{ x: 745 }} dataSource={data.recent_tickets} columns={[
            { title: '工单编号', dataIndex: 'ticket_id', width: 160, render: (id) => <Link className="workspace-reference" to={`/admin/tickets/${id}`}>{id}</Link> },
            { title: '诉求类型', dataIndex: 'request_type', width: 86 },
            { title: '摘要', dataIndex: 'description', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 125, render: (status, row) => <TicketStatusTag status={status} label={row.status_label} /> },
            { title: '责任部门', dataIndex: 'department_name', width: 104, render: (name) => name || '待派发' },
            { title: '创建时间', dataIndex: 'created_at', width: 108, render: (value) => dayjs(value).format('MM-DD HH:mm') },
          ]} />
        </WorkspaceTableRegion>
      </Card>
    </>}
  </div>
}
