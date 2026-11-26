import { Alert, Button, Collapse, Drawer, Skeleton, Space, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getKbDocument } from '../api/kb'
import type { KbCitation } from '../types'

/** True when a citation has the four required evidence fields (or usable fallbacks). */
export function isCompleteCitation(c: KbCitation): boolean {
  const authority = c.issuing_authority || c.department
  return Boolean(c.title && (c.doc_number || authority) && c.excerpt)
}

/** Drop incomplete / placeholder citations; never invent sources. */
export function filterDisplayCitations(citations: KbCitation[] | undefined | null, noEvidence: boolean): KbCitation[] {
  if (noEvidence || !citations?.length) return []
  const now = Date.now()
  return citations.filter(citation => {
    const expired = citation.expires_at && Date.parse(citation.expires_at) <= now
    return !citation.is_expired && !expired && (!citation.status || citation.status === 'PUBLISHED')
      && isCompleteCitation(citation)
  })
}

function officialLink(value?: string | null) {
  if (!value) return undefined
  try {
    const url = new URL(value)
    if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return url.href
  } catch {
    return undefined
  }
}

function CitationDetail({ citation }: { citation: KbCitation }) {
  const authority = citation.issuing_authority || citation.department
  return (
    <div data-testid={`citation-detail-${citation.index}`}>
      {citation.excerpt && (
        <Typography.Paragraph
          style={{
            background: 'var(--ce-soft)',
            border: '1px solid var(--ce-line)',
            padding: 12,
            borderRadius: 8,
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            marginBottom: 12,
          }}
        >
          {citation.excerpt}
        </Typography.Paragraph>
      )}
      <Space wrap>
        {authority && <Tag>发布单位：{authority}</Tag>}
        {citation.doc_number && <Tag>文号：{citation.doc_number}</Tag>}
        {citation.published_at && <Tag>发布：{citation.published_at.slice(0, 10)}</Tag>}
        {citation.effective_at && <Tag>生效：{citation.effective_at.slice(0, 10)}</Tag>}
        {citation.expires_at && <Tag>有效至：{citation.expires_at.slice(0, 10)}</Tag>}
        {citation.kb_type && <Tag>{kbTypeLabel(citation.kb_type)}</Tag>}
        {citation.version != null && <Tag>v{citation.version}</Tag>}
      </Space>
    </div>
  )
}

function CitationDocument({ citation }: { citation: KbCitation }) {
  const document = useQuery({
    queryKey: ['citation-document', citation.doc_id],
    queryFn: () => getKbDocument(citation.doc_id),
    retry: false,
  })
  if (document.isPending) return <Skeleton active paragraph={{ rows: 2 }} />
  if (document.isError) return <Alert type="warning" showIcon title="暂时无法查看文档详情，仍可阅读本次回答的引用摘录。" />
  if (document.data.status !== 'PUBLISHED' || (document.data.expires_at && Date.parse(document.data.expires_at) <= Date.now())) {
    return <Alert type="warning" showIcon title="该引用的发布状态已变化，请重新查询政策。" />
  }
  const source = officialLink(document.data.source_url)
  return <Space wrap>
    {document.data.region && <Tag>地区：{document.data.region}</Tag>}
    {document.data.domain && <Tag>领域：{document.data.domain}</Tag>}
    {source && <a href={source} target="_blank" rel="noopener noreferrer">查看发布来源（新窗口）</a>}
  </Space>
}

function kbTypeLabel(t: string) {
  const map: Record<string, string> = {
    policy: '公开政策', guide: '办事指南', faq: '常见问题',
    internal: '内部制度', procedure: '办理流程', case: '历史案例',
  }
  return map[t] || t
}

/**
 * RAG citation list for policy / service-guide answers.
 * When no_evidence is true, renders nothing (no fake sources).
 */
export function PolicyCitations({
  citations,
  noEvidence = false,
  compact = false,
  canReadDocument = false,
}: {
  citations?: KbCitation[] | null
  noEvidence?: boolean
  compact?: boolean
  canReadDocument?: boolean
}) {
  const [selected, setSelected] = useState<KbCitation | null>(null)
  const items = filterDisplayCitations(citations, noEvidence)
  if (!items.length) return null

  return (
    <div data-testid="policy-citations" style={{ marginTop: compact ? 8 : 12 }}>
      {!compact && (
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          引用来源
        </Typography.Text>
      )}
      <Collapse
        size="small"
        items={items.map(c => {
          const authority = c.issuing_authority || c.department
          return {
            key: String(c.index),
            label: (
              <Space wrap>
                <Tag color="blue">来源{c.index}</Tag>
                <Typography.Text strong>{c.title}</Typography.Text>
                {c.doc_number && <Typography.Text type="secondary">{c.doc_number}</Typography.Text>}
                {authority && <Tag>{authority}</Tag>}
                <Tag color="green">有效</Tag>
              </Space>
            ),
            children: <>
              <CitationDetail citation={c} />
              <Button type="link" onClick={() => setSelected(c)} aria-label={`查看详情：${c.title}`} style={{ paddingInline: 0 }}>查看详情</Button>
            </>,
          }
        })}
      />
      <Drawer title={selected?.title ?? '引用详情'} open={Boolean(selected)} size="min(480px, 100vw)" onClose={() => setSelected(null)}>
        {selected && <>
          <CitationDetail citation={selected} />
          {canReadDocument && selected.doc_id > 0 && <CitationDocument citation={selected} />}
        </>}
      </Drawer>
    </div>
  )
}
