import { useState } from 'react'
import { Alert, App, Button, Descriptions, Drawer, Input, List, Pagination, Space, Tabs, Tag, Typography } from 'antd'
import { HistoryOutlined, InboxOutlined, SafetyCertificateOutlined, SearchOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { analyzeTicket, listHotspots, listSuggestions, reviewSuggestion } from '../api/intelligence'
import { getTicket, listTickets, ticketKeys } from '../api/tickets'
import { useAuth } from '../auth/AuthContext'
import { PageHeader } from '../components/PageHeader'
import { SlaStatus } from '../components/SlaStatus'
import { TicketStatusTag } from '../components/TicketStatusTag'
import { AiSourceStatus } from '../components/AiSourceStatus'
import { LegacySuggestionBody, SuggestionRisk, TriageSuggestion } from '../components/TriageSuggestion'
import { TriageReview, type SaveTriageReview } from '../components/TriageReview'
import { WorkspaceEmpty, WorkspaceError, WorkspaceLoading } from '../components/WorkspaceState'
import type { AiSuggestion, Ticket, TicketFilters } from '../types'

type QueueStatus = 'pending' | 'accepted'
const reviewable: AiSuggestion['suggestion_type'][] = ['triage_assistant', 'assignment', 'summary', 'completeness', 'risk', 'similarity']
const PAGE_SIZE = 8

function TicketFacts({ ticket }: { ticket: Ticket }) {
  return <>
    <div className="triage-original"><span>市民原始诉求</span><p>{ticket.description || '未填写'}</p></div>
    <Descriptions className="triage-fact-grid" size="small" layout="vertical" column={{ xs: 1, sm: 2 }} items={[
      { key: 'type', label: '诉求类型', children: ticket.request_type || '未填写' },
      { key: 'category', label: '当前分类', children: ticket.category_path || ticket.category_name || '未确认' },
      { key: 'address', label: '发生地点', children: ticket.location || '未填写' },
      { key: 'when', label: '发生时间', children: ticket.occurred_at_text || '未填写' },
      { key: 'target', label: '反映对象', children: ticket.target || '未填写' },
      { key: 'sla', label: '当前 SLA', children: <SlaStatus state={ticket.sla_state} remainingSeconds={ticket.remaining_seconds} /> },
    ]} />
  </>
}

export function AgentTriagePage() {
  const { user } = useAuth()
  const { message } = App.useApp()
  const cache = useQueryClient()
  const [status, setStatus] = useState<QueueStatus>('pending')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string>()
  const [selectedSuggestions, setSelectedSuggestions] = useState<Record<string, string>>({})
  const [historyOpen, setHistoryOpen] = useState(false)
  const [hotspotsOpen, setHotspotsOpen] = useState(false)
  const [detailTab, setDetailTab] = useState('facts')
  const hotspots = useQuery({ queryKey: ['ai', 'hotspots', user?.id], queryFn: () => listHotspots(30), enabled: hotspotsOpen })
  const filters: TicketFilters = { status, page, page_size: PAGE_SIZE, keyword: keyword || undefined, sort: 'created_at', order: 'asc' }
  const queue = useQuery({ queryKey: [...ticketKeys.list(filters), user?.id], queryFn: () => listTickets(filters) })
  const ticketId = selected ?? queue.data?.items[0]?.ticket_id
  const detail = useQuery({ queryKey: [...ticketKeys.detail(ticketId ?? ''), user?.id], queryFn: () => getTicket(ticketId!), enabled: !!ticketId })
  const ticket = detail.data
  const historyKey = (id: string | undefined) => ['triage-suggestions', user?.id, id] as const
  const suggestionKey = historyKey(ticketId)
  const suggestions = useQuery({ queryKey: suggestionKey, queryFn: () => listSuggestions(ticketId!), enabled: false })
  const entries = [...(suggestions.data ?? [])].filter((item) => reviewable.includes(item.suggestion_type))
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
  const item = entries.find((entry) => entry.id === (ticketId && selectedSuggestions[ticketId])) ?? entries[0]
  const selectSuggestion = (next: AiSuggestion) => setSelectedSuggestions((current) => ({ ...current, [next.ticket_id]: next.id }))
  const updateSuggestions = (id: string, incoming: AiSuggestion[]) => cache.setQueryData<AiSuggestion[]>(historyKey(id), (current = []) => {
    const byId = new Map(current.map((entry) => [entry.id, entry]))
    incoming.forEach((entry) => byId.set(entry.id, entry))
    return [...byId.values()]
  })
  const analyze = useMutation({
    mutationFn: (id: string) => analyzeTicket(id, ['triage_assistant'], 'triage_assistant'),
    onSuccess: (data, id) => {
      updateSuggestions(id, data)
      if (data[0]) {
        selectSuggestion(data[0])
        void message.success('分诊建议已生成')
      }
    },
  })
  const review = useMutation({
    mutationFn: ({ suggestion, decision, comment, editedContent }: {
      suggestion: AiSuggestion
      decision: NonNullable<AiSuggestion['review_decision']>
      comment?: string
      editedContent?: Record<string, unknown>
    }) => reviewSuggestion(suggestion.id, decision, comment, editedContent),
    onSuccess: (saved, { suggestion, decision }) => {
      updateSuggestions(suggestion.ticket_id, [saved])
      void message.success(decision === 'helpful' || decision === 'not_helpful' ? '质量反馈已记录' : '人工审核已记录')
    },
  })
  const save: SaveTriageReview = (decision, comment, editedContent) => {
    if (!item) return Promise.resolve()
    return review.mutateAsync({ suggestion: item, decision, comment, editedContent })
  }
  const resetSelection = (nextPage: number) => {
    setPage(nextPage)
    setSelected(undefined)
    setDetailTab('facts')
    analyze.reset()
    review.reset()
  }
  const busy = analyze.isPending || review.isPending || suggestions.isFetching
  const canAnalyze = ticket?.status === 'pending' || ticket?.status === 'accepted'
  const loadHistory = () => {
    setHistoryOpen(true)
    void suggestions.refetch()
  }

  return (
    <div className="triage-page">
      <PageHeader title="智能分诊与派发" description="从队列选择工单，核对诉求并记录审核意见。"
        extra={<Space wrap>
          <Button icon={<HistoryOutlined aria-hidden />} disabled={!ticket || busy} onClick={loadHistory}>加载历史建议</Button>
          <Button type="primary" icon={<ThunderboltOutlined aria-hidden />} loading={analyze.isPending} disabled={!canAnalyze || busy}
            onClick={() => { if (ticketId) { setDetailTab('advice'); analyze.mutate(ticketId) } }}>生成分诊建议</Button>
        </Space>} />
      <Alert className="triage-boundary" type="info" showIcon icon={<SafetyCertificateOutlined />}
        title={<><strong>人机协同边界</strong><span>采纳仅记审核决策，不会自动派发、受理或办结。实际操作请前往工单详情。</span></>} />
      <div className="triage-grid">
        <section aria-label="待处理队列" className="triage-panel triage-queue">
          <Tabs className="triage-queue-tabs" aria-label="队列状态" size="small" activeKey={status} items={[
            { key: 'pending', label: '待受理', disabled: busy }, { key: 'accepted', label: '已受理', disabled: busy },
          ]} onChange={(value) => { setStatus(value as QueueStatus); resetSelection(1) }}
            tabBarExtraContent={queue.data && <span className="triage-counter">共 {queue.data.total} 件</span>} />
          <div className="triage-search">
            <Input.Search aria-label="搜索工单编号或关键词" placeholder="工单编号 / 关键词" allowClear disabled={busy} maxLength={100}
              enterButton={<SearchOutlined aria-label="搜索" />} onSearch={(value) => { setKeyword(value.trim()); resetSelection(1) }} />
          </div>
          {queue.isPending ? <WorkspaceLoading label="加载待处理工单" /> : queue.isError
            ? <WorkspaceError error={queue.error} fallback="队列加载失败。" retry={() => void queue.refetch()} />
            : queue.data.items.length === 0 ? <WorkspaceEmpty text={keyword ? '没有匹配的工单' : '当前队列暂无工单'} />
            : <div className="triage-table-region" role="region" aria-label="工单列表" tabIndex={0}>
              <table className="triage-queue-table">
                <thead><tr><th scope="col">工单</th><th scope="col" className="triage-summary-column">诉求摘要</th><th scope="col">状态</th></tr></thead>
                <tbody>{queue.data.items.map((row) => (
                  <tr key={row.ticket_id} className={row.ticket_id === ticketId ? 'triage-selected' : undefined}>
                    <th scope="row">
                      <button type="button" className="triage-ticket-button workspace-reference" aria-pressed={row.ticket_id === ticketId} disabled={busy}
                        onClick={() => {
                          setSelected(row.ticket_id)
                          setDetailTab('facts')
                          analyze.reset()
                          review.reset()
                        }}>{row.ticket_id}</button>
                      <span className="triage-summary-mobile">{row.description}</span>
                    </th>
                    <td className="triage-summary-column"><span>{row.description}</span></td>
                    <td><TicketStatusTag status={row.status} label={row.status_label} /></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>}
          {(queue.data?.total ?? 0) > PAGE_SIZE && <Pagination size="small" simple current={page} pageSize={PAGE_SIZE}
            total={queue.data!.total} disabled={busy} onChange={resetSelection} />}
        </section>
        <section aria-label="选中工单" className="triage-panel triage-inspector ce-ai-shimmer">
          {!ticketId ? <WorkspaceEmpty text="选择工单后查看原始诉求" /> : detail.isPending
            ? <WorkspaceLoading label="加载工单事实" /> : detail.isError
              ? <WorkspaceError error={detail.error} fallback="工单事实加载失败。" retry={() => void detail.refetch()} />
              : ticket && <>
                <div className="triage-inspector-head">
                  <h2 className="triage-fact-title">{ticket.description.split(/[。！？\n]/, 1)[0] || ticket.request_type}</h2>
                  <div className="triage-fact-meta"><span className="workspace-reference">{ticket.ticket_id}</span><TicketStatusTag status={ticket.status} label={ticket.status_label} /></div>
                </div>
                <Tabs className="triage-detail-tabs" aria-label="工单详情视图" size="small" activeKey={detailTab} onChange={setDetailTab} items={[
                  { key: 'facts', label: '工单事实', children: <div className="triage-detail-content"><TicketFacts ticket={ticket} /></div> },
                  { key: 'advice', label: 'AI 分诊建议', children: <div className="triage-detail-content ce-ai-shimmer" style={{ background: '#fafafb' }}>
                    {analyze.isError && <WorkspaceError error={analyze.error} fallback="分诊建议生成失败。" retry={() => ticketId && analyze.mutate(ticketId)} />}
                    {analyze.isPending ? <WorkspaceLoading label="正在生成分诊建议" /> : item ? <>
                      <div className="triage-provider">
                        <AiSourceStatus provider={item.provider} model={item.model_name}
                          degraded={item.result.degraded === true}
                          reason={typeof item.result.degrade_reason === 'string' ? item.result.degrade_reason : undefined}
                          latencyMs={typeof item.result.latency_ms === 'number' ? item.result.latency_ms : undefined} />
                        <SuggestionRisk level={item.risk_level} />
                      </div>
                      {item.suggestion_type === 'triage_assistant' ? <TriageSuggestion item={item} /> : <LegacyTriageSuggestion item={item} />}
                    </> : <WorkspaceEmpty text="可生成分诊建议，或查看历史记录" />}
                  </div> },
                ]}/>
                <section aria-labelledby="triage-review-title" className="triage-review">
                  <div className="triage-panel-head"><h3 id="triage-review-title">人工审核</h3></div>
                  <TriageReview key={item?.id ?? ticketId} ticket={ticket} item={item} saving={review.isPending} error={review.error} onSave={save} />
                </section>
              </>}
        </section>
      </div>
      <div className="triage-feedback">
        <span>建议质量反馈</span>
        <Space wrap>{(['helpful', 'not_helpful'] as const).map((decision) => (
          <Button size="small" key={decision} disabled={!item || busy} aria-pressed={item?.review_decision === decision}
            onClick={() => void save(decision).catch(() => undefined)}>{decision === 'helpful' ? '有帮助' : '无帮助'}</Button>
        ))}</Space>
        <Button className="triage-hotspots" type="link" onClick={() => setHotspotsOpen(true)}>近 30 天热点</Button>
      </div>
      <Drawer title="历史分诊建议" open={historyOpen} onClose={() => setHistoryOpen(false)} size="min(440px, 100vw)">
        {suggestions.isFetching ? <WorkspaceLoading label="加载历史分诊建议" /> : suggestions.isError
          ? <WorkspaceError error={suggestions.error} fallback="历史建议加载失败。" retry={() => void suggestions.refetch()} />
          : entries.length === 0 ? <WorkspaceEmpty text="该工单暂无历史分诊建议" /> : <div className="triage-history">
            {entries.map((entry) => <Button key={entry.id} block icon={<InboxOutlined />} onClick={() => {
              review.reset()
              selectSuggestion(entry)
              setDetailTab('advice')
              setHistoryOpen(false)
            }}>{dayjs(entry.created_at).format('YYYY-MM-DD HH:mm')} · {historyLabels[entry.suggestion_type] ?? entry.suggestion_type}</Button>)}
          </div>}
      </Drawer>
      <Drawer title="近 30 天热点问题聚类" open={hotspotsOpen} onClose={() => setHotspotsOpen(false)} size="min(440px, 100vw)">
        {hotspots.isPending ? <WorkspaceLoading label="加载热点问题" /> : hotspots.isError
          ? <WorkspaceError error={hotspots.error} fallback="热点加载失败。" retry={() => void hotspots.refetch()} />
          : <List dataSource={hotspots.data} locale={{ emptyText: '当前可见范围内暂无热点聚类' }} renderItem={(entry) => (
            <List.Item><List.Item.Meta title={<Space wrap>{entry.label}<Tag>{entry.count} 件</Tag>
              {entry.urgent_count > 0 && <Tag color="error">紧急 {entry.urgent_count}</Tag>}</Space>}
              description={entry.sample_ticket_ids.join('、')} /></List.Item>
          )} />}
      </Drawer>
    </div>
  )
}

const historyLabels: Partial<Record<AiSuggestion['suggestion_type'], string>> = {
  triage_assistant: '分诊建议', assignment: '派发建议', summary: '诉求摘要',
  completeness: '完整性检查', risk: '风险提示', similarity: '相似诉求',
}

function LegacyTriageSuggestion({ item }: { item: AiSuggestion }) {
  return <div className="triage-suggestion"><section>
    <h3>{historyLabels[item.suggestion_type]}</h3>
    {item.explanation && <Typography.Paragraph>{item.explanation}</Typography.Paragraph>}
    <LegacySuggestionBody item={item} />
  </section></div>
}
