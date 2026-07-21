import { Collapse, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { KbCitation } from '../types'

/** True when a citation has the four required evidence fields (or usable fallbacks). */
export function isCompleteCitation(c: KbCitation): boolean {
  const authority = c.issuing_authority || c.department
  return Boolean(c.title && (c.doc_number || authority) && c.excerpt)
}

/** Drop incomplete / placeholder citations; never invent sources. */
export function filterDisplayCitations(citations: KbCitation[] | undefined | null, noEvidence: boolean): KbCitation[] {
  if (noEvidence || !citations?.length) return []
  return citations.filter(isCompleteCitation)
}

function validityTag(c: KbCitation) {
  if (c.is_expired) return <Tag color="red">已失效</Tag>
  return <Tag color="green">有效</Tag>
}

function CitationDetail({ citation }: { citation: KbCitation }) {
  const authority = citation.issuing_authority || citation.department
  return (
    <div data-testid={`citation-detail-${citation.index}`}>
      {citation.excerpt && (
        <Typography.Paragraph
          style={{
            background: 'rgba(22,124,114,0.05)',
            padding: 12,
            borderRadius: 6,
            whiteSpace: 'pre-wrap',
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
        {citation.expires_at && (
          <Tag color={citation.is_expired ? 'red' : 'default'}>
            失效：{citation.expires_at.slice(0, 10)}
          </Tag>
        )}
        {citation.kb_type && <Tag>{kbTypeLabel(citation.kb_type)}</Tag>}
        {citation.version != null && <Tag>v{citation.version}</Tag>}
        {citation.doc_id > 0 && (
          <Link to={`/citizen/policy?doc=${citation.doc_id}`} data-testid={`citation-link-${citation.index}`}>
            查看详情
          </Link>
        )}
      </Space>
    </div>
  )
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
}: {
  citations?: KbCitation[] | null
  noEvidence?: boolean
  compact?: boolean
}) {
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
                {validityTag(c)}
              </Space>
            ),
            children: <CitationDetail citation={c} />,
          }
        })}
      />
    </div>
  )
}
