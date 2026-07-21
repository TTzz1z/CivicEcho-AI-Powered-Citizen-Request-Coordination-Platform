import { Card, Input, Table, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { getAuditLogs } from '../api/admin'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'

export function AuditPage() {
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const query = useQuery({ queryKey: ['admin', 'audit', page, action], queryFn: () => getAuditLogs(page, 20, action) })
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return <>
    <PageHeader eyebrow="AUDIT TRAIL" title="审计日志" description="关键登录、权限拒绝、敏感信息访问与工单操作均由后端留痕。" extra={<Input.Search allowClear placeholder="按动作精确查询" onSearch={v => { setAction(v); setPage(1) }} style={{ width: 240 }} />} />
    <Card className="surface" styles={{ body: { padding: 0 } }}>
      <Table rowKey="id" loading={query.isLoading} dataSource={query.data?.items} columns={[
        { title: '时间', dataIndex: 'created_at', width: 180, render: v => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
        { title: '动作', dataIndex: 'action', width: 180 },
        { title: '操作者', dataIndex: 'actor_user_id', render: (v, r) => v ? `用户 #${v}` : r.actor_type },
        { title: '资源', render: (_, r) => r.resource_type ? `${r.resource_type} / ${r.resource_id || '—'}` : '—' },
        { title: '结果', dataIndex: 'outcome', render: v => <Tag color={v === 'success' ? 'success' : 'error'}>{v}</Tag> },
        { title: '详情', dataIndex: 'details', ellipsis: true, render: v => v || '—' },
      ]} pagination={{ current: page, pageSize: 20, total: query.data?.total, onChange: setPage, showTotal: t => `共 ${t} 条` }} />
    </Card>
  </>
}
