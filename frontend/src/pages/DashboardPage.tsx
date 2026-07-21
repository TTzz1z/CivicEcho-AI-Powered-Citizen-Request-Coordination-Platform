import { Card, Col, Progress, Row, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { getDashboard } from '../api/admin'
import { ChartPanel } from '../components/ChartPanel'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { TicketStatusTag } from '../components/TicketStatusTag'

export function DashboardPage() {
  const query = useQuery({ queryKey: ['admin', 'dashboard'], queryFn: getDashboard, refetchInterval: 60_000 })
  const statusOption = useMemo<EChartsOption>(() => ({ tooltip: { trigger: 'item' }, legend: { bottom: 0 }, color: ['#e5a72a', '#2a9d8f', '#4776bd', '#7e67b4', '#409c67', '#87949b'], series: [{ type: 'pie', radius: ['44%', '68%'], center: ['50%', '43%'], label: { formatter: '{b}\n{c}' }, data: query.data?.status_distribution || [] }] }), [query.data])
  const typeOption = useMemo<EChartsOption>(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 42, right: 20, top: 25, bottom: 34 }, xAxis: { type: 'category', data: query.data?.request_type_distribution.map(x => x.name) || [] }, yAxis: { type: 'value', minInterval: 1 }, series: [{ type: 'bar', barWidth: 28, data: query.data?.request_type_distribution.map(x => x.value) || [], itemStyle: { color: '#167c72', borderRadius: [5, 5, 0, 0] } }] }), [query.data])
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />
  const placeholders = Array.from({ length: 5 }, (_, i) => ({ key: String(i), label: '加载中', value: 0, unit:'' }))
  return <>
    <PageHeader eyebrow="OPERATIONS OVERVIEW" title="运营总览" description="所有指标均由后端只读聚合接口实时计算，不在浏览器内加载全量工单统计。" />
    <Row gutter={[16, 16]}>{(query.data?.metrics || placeholders).map(m => <Col xs={12} md={8} xl={m.key==='total'?4:5} key={m.key}><Card loading={query.isLoading} className={`metric-card metric-${m.key}`}><div className="metric-label">{m.label}</div><div className="metric-value">{m.value.toLocaleString()} <small>{m.unit}</small></div></Card></Col>)}</Row>
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}><Col xs={24} lg={12}><Card title="工单状态分布" className="surface"><ChartPanel label="工单状态分布饼图" option={statusOption} empty={!query.isLoading&&!query.data?.status_distribution.length} /></Card></Col><Col xs={24} lg={12}><Card title="四类诉求分布" className="surface"><ChartPanel label="四类诉求柱状图" option={typeOption} empty={!query.isLoading&&!query.data?.request_type_distribution.length} /></Card></Col></Row>
    <Card title="最近工单" className="surface" style={{ marginTop: 16 }} styles={{ body: { padding: 0 } }}><Table rowKey="ticket_id" pagination={false} dataSource={query.data?.recent_tickets || []} columns={[
      { title: '工单编号', dataIndex: 'ticket_id', render: v => <Link to={`/admin/tickets/${v}`}>{v}</Link> }, { title: '诉求类型', dataIndex: 'request_type' }, { title: '摘要', dataIndex: 'description', ellipsis: true }, { title: '状态', dataIndex: 'status', render: (v, r) => <TicketStatusTag status={v} label={r.status_label} /> }, { title: '责任部门', dataIndex: 'department_name', render: v => v || '待派发' }, { title: '创建时间', dataIndex: 'created_at', render: v => dayjs(v).format('MM-DD HH:mm') },
    ]} /></Card>
    <Card title="按部门统计超时率" className="surface" style={{marginTop:16}} styles={{body:{padding:0}}}><Table rowKey="department_name" pagination={false} dataSource={query.data?.department_sla||[]} columns={[{title:'责任部门',dataIndex:'department_name'},{title:'纳入统计工单',dataIndex:'total'},{title:'超时工单',dataIndex:'overdue'},{title:'超时率',dataIndex:'overdue_rate',render:v=><Progress percent={v} size="small" status={v>=30?'exception':'normal'}/>}]} /></Card>
  </>
}
