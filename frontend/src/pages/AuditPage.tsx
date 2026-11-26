import { App, Button, Card, Descriptions, Drawer, Input, Space, Table, Tag } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { exportAuditLogsCsv, getAuditLogs } from '../api/admin'
import { formatApiErrorMessage } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { WorkspaceTableRegion } from '../components/WorkspaceTableRegion'
import type { AuditLog } from '../types'

export function AuditPage() {
  const { message } = App.useApp()
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [selected, setSelected] = useState<AuditLog>()
  const [exporting, setExporting] = useState(false)
  const query = useQuery({ queryKey: ['admin', 'audit', page, action], queryFn: () => getAuditLogs(page, 20, action) })
  const handleExport = async () => {
    if (exporting) return
    setExporting(true)
    try {
      await exportAuditLogsCsv({ action: action || undefined })
      message.success('审计日志 CSV 已开始下载')
    } catch (err) {
      message.error(formatApiErrorMessage(err, '审计日志导出失败，请稍后重试'))
    } finally {
      setExporting(false)
    }
  }
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return <>
    <PageHeader
      eyebrow="AUDIT TRAIL"
      title="审计日志"
      description="按操作名称检索审计记录，查看涉及资源、执行结果和请求编号。"
      extra={
        <Space wrap>
          <Input.Search
            className="audit-search"
            aria-label="按动作精确查询"
            allowClear
            placeholder="按动作精确查询（如 login / logout）"
            value={searchValue}
            onChange={e => {
              const next = e.target.value
              setSearchValue(next)
              if (!next.trim() && action) {
                setAction('')
                setPage(1)
              }
            }}
            onSearch={v => {
              setAction(v.trim())
              setPage(1)
            }}
          />
          {action && <Button onClick={() => { setSearchValue(''); setAction(''); setPage(1) }}>重置</Button>}
          <Button icon={<DownloadOutlined />} loading={exporting} disabled={exporting} onClick={() => void handleExport()}>导出 CSV</Button>
        </Space>
      }
    />
    <Card className="surface" styles={{ body: { padding: 0 } }}>
      <WorkspaceTableRegion label="审计记录">
        <Table
          size="small"
          rowKey="id"
          loading={query.isLoading}
          dataSource={query.data?.items}
          locale={{ emptyText: '暂无匹配的审计记录' }}
          scroll={{ x: 560 }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 168, render: v => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
            { title: '动作', dataIndex: 'action', width: 170, ellipsis: true },
            { title: '操作者', dataIndex: 'actor_user_id', responsive: ['md'], render: (v, r) => v ? `用户 #${v}` : r.actor_type },
            { title: '资源', responsive: ['md'], ellipsis: true, render: (_, r) => r.resource_type ? `${r.resource_type} / ${r.resource_id || '—'}` : '—' },
            { title: '结果', dataIndex: 'outcome', width: 88, render: v => <Tag color={v === 'success' ? 'success' : 'error'}>{v}</Tag> },
            { title: '详情', width: 88, render: (_, row) => <Button type="link" size="small" aria-label={`查看记录 ${row.id}`} onClick={() => setSelected(row)}>查看记录</Button> },
          ]}
          pagination={{ current: page, pageSize: 20, total: query.data?.total, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        />
      </WorkspaceTableRegion>
    </Card>
    <Drawer title="审计记录详情" open={!!selected} onClose={() => setSelected(undefined)} size="min(480px, 100vw)">
      {selected && <>
        <Descriptions size="small" column={1} bordered items={[
          { key: 'action', label: '动作', children: selected.action },
          { key: 'actor', label: '操作者', children: selected.actor_user_id ? `用户 #${selected.actor_user_id}` : selected.actor_type },
          { key: 'resource', label: '涉及资源', children: selected.resource_type ? `${selected.resource_type} / ${selected.resource_id || '—'}` : '—' },
          { key: 'outcome', label: '执行结果', children: <Tag color={selected.outcome === 'success' ? 'success' : 'error'}>{selected.outcome}</Tag> },
          { key: 'request', label: '请求编号', children: <span className="workspace-reference">{selected.request_id || '—'}</span> },
          { key: 'time', label: '发生时间', children: dayjs(selected.created_at).format('YYYY-MM-DD HH:mm:ss') },
        ]} />
        <pre className="audit-detail" style={{ marginTop: 14 }}>{selected.details || '暂无附加详情'}</pre>
      </>}
    </Drawer>
  </>
}
