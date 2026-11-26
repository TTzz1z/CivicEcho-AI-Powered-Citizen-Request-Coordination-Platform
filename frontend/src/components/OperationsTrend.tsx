import { Card, Collapse, Table } from 'antd'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import type { Dashboard } from '../types'
import { ChartPanel } from './ChartPanel'
import { WorkspaceTableRegion } from './WorkspaceTableRegion'

export function OperationsTrend({ points, timezone }: {
  points: Dashboard['intake_trend']
  timezone?: string
}) {
  const option = useMemo<EChartsOption>(() => ({
    animation: false,
    color: ['#2563eb'],
    grid: { left: 44, right: 16, top: 24, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', boundaryGap: false, data: points?.map((point) => point.day) ?? [],
      axisLabel: { formatter: (date: string) => date.slice(5), hideOverlap: true, color: '#626a79' },
      axisLine: { lineStyle: { color: '#eceef2' } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#626a79' }, splitLine: { lineStyle: { color: '#f1f2f5' } } },
    series: [{ name: '登记工单', type: 'line', data: points?.map((point) => point.count) ?? [],
      symbolSize: 6,
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(37,99,235,0.16)' }, { offset: 1, color: 'rgba(37,99,235,0)' }] } },
      lineStyle: { width: 2 } }],
  }), [points])

  return <Card title="诉求登记趋势" className="surface ops-trend">
    <p className="ops-chart-note">按工单创建日期统计近 14 天，含今天{timezone ? ` · ${timezone}` : ''}</p>
    <ChartPanel label="近 14 天每日新增工单折线图" option={option} empty={!points?.length} />
    {!!points?.length && <Collapse bordered={false} items={[{ key: 'data', label: '查看每日数据', children:
      <WorkspaceTableRegion label="每日新增工单">
        <Table size="small" rowKey="day" dataSource={points} pagination={false}
          columns={[{ title: '日期', dataIndex: 'day' }, { title: '新增工单', dataIndex: 'count', align: 'right' }]} />
      </WorkspaceTableRegion>,
    }]} />}
  </Card>
}
