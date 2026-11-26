import { Alert, Descriptions, List, Popover, Space, Tag, Typography } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import type { AiSuggestion } from '../types'

const levels: Record<string, string> = {
  normal: '一般', expedited: '加急', urgent: '紧急', major: '重大', attention: '需关注', sensitive: '敏感',
}
const object = (value: unknown) => value !== null && typeof value === 'object' && !Array.isArray(value)
  ? value as Record<string, unknown>
  : {}
const strings = (value: unknown) => Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
const display = (value: unknown, fallback = '—') => typeof value === 'string' && value.trim() ? value : fallback

export function triageCandidates(item: AiSuggestion) {
  const raw = item.result.department_candidates ?? item.result.recommended_departments
  return Array.isArray(raw) ? raw.map(object).filter((candidate) => typeof candidate.department_name === 'string') : []
}

export function SuggestionRisk({ level }: { level: AiSuggestion['risk_level'] }) {
  return level === 'none' ? null : <Tag color={level === 'urgent' ? 'error' : 'warning'}>{levels[level]}</Tag>
}

export function LegacySuggestionBody({ item }: { item: AiSuggestion }) {
  const result = item.result
  if (item.suggestion_type === 'summary') return <Typography.Paragraph copyable>{display(result.summary)}</Typography.Paragraph>
  if (item.suggestion_type === 'completeness') return <Descriptions size="small" column={1} items={[
    { key: 'state', label: '结论', children: result.complete ? '信息完整' : '建议补充信息' },
    { key: 'missing', label: '缺失项', children: strings(result.missing_fields).join('、') || '无' },
  ]} />
  if (item.suggestion_type === 'risk') return <Alert showIcon type={result.level === 'urgent' ? 'error' : 'warning'}
    title={display(result.recommendation)} />
  if (item.suggestion_type === 'assignment') return <List size="small" dataSource={triageCandidates(item)}
    locale={{ emptyText: '暂无部门候选' }} renderItem={(candidate) => <List.Item>{display(candidate.department_name)}</List.Item>} />
  if (item.suggestion_type === 'similarity') return <List size="small"
    dataSource={Array.isArray(result.matches) ? result.matches.map(object) : []}
    locale={{ emptyText: '未发现明显相似诉求' }} renderItem={(match) => <List.Item><Space wrap>
      <span className="workspace-reference">{display(match.ticket_id)}</span>
      {typeof match.score === 'number' && <Tag title="按文本重合度估算">相似匹配度 {Math.round(match.score * 100)}%</Tag>}
    </Space></List.Item>} />
  return <pre className="ai-json-result">{JSON.stringify(result, null, 2)}</pre>
}

export function TriageSuggestion({ item }: { item: AiSuggestion }) {
  const result = item.result
  const summary = object(result.case_summary)
  const classification = object(result.classification)
  const urgency = object(result.urgency)
  const completeness = object(result.completeness)
  const sla = object(result.sla_recommendation)
  const edited = object(result.edited_content)
  const fields = strings(completeness.missing_fields)
  const questions = strings(completeness.follow_up_questions)
  const candidates = triageCandidates(item)
  const score = completeness.completeness_score ?? object(result.confidence_labels).completeness_score
  const urgencyLabel = display(urgency.level)

  return (
    <div className="triage-suggestion" role="region" aria-label="分诊建议内容" tabIndex={0}>
      <section>
        <h3>分类与紧急度</h3>
        <div className="triage-classification">
          <strong>{[classification.category, classification.subcategory].filter(Boolean).join(' / ') || '—'}</strong>
          {urgencyLabel !== '—' && <Tag color={urgency.emergency ? 'error' : 'default'}>{levels[urgencyLabel] ?? urgencyLabel}</Tag>}
        </div>
        {typeof classification.request_type === 'string' && <p>诉求类型建议 · {classification.request_type}</p>}
        {typeof classification.reason === 'string' && <p>{classification.reason}</p>}
        {typeof urgency.reason === 'string' && <p>{urgency.reason}</p>}
      </section>
      <section>
        <h3>信息完整性 {typeof score === 'number' && <Popover title="完整度计算" content="根据地址、描述等字段的覆盖情况估算。" trigger={['click']}>
          <button type="button" className="triage-info" aria-label="完整度计算说明"><InfoCircleOutlined /></button>
        </Popover>}</h3>
        <strong>{completeness.complete ? '信息完整' : '建议人工核对'}</strong>
        {typeof score === 'number' && <span className="triage-score">{score}%</span>}
        {fields.length > 0 && <p>待补充 · {fields.join('、')}</p>}
        {questions.length > 0 && <ul>{questions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
      </section>
      <section>
        <h3>责任部门推荐</h3>
        {candidates.length === 0 ? <p>暂无部门候选</p> : candidates.map((candidate, index) => (
          <div className="triage-candidate" key={`${candidate.department_name}-${index}`}>
            <strong>{display(candidate.department_name)}</strong>
            {typeof candidate.reason === 'string' && <p>{candidate.reason}</p>}
          </div>
        ))}
      </section>
      <section>
        <h3>SLA 建议 · 内部参考</h3>
        <Descriptions size="small" column={1} items={[
          { key: 'response', label: '响应', children: display(sla.response_deadline) },
          { key: 'handling', label: '办理', children: display(sla.handling_deadline) },
        ]} />
        {typeof sla.reason === 'string' && <p>{sla.reason}</p>}
      </section>
      {typeof summary.description === 'string' && <section><h3>AI 诉求摘要</h3><p>{summary.description}</p>
        {['location', 'duration', 'affected_scope'].some((key) => typeof summary[key] === 'string' && summary[key])
          && <p>{[summary.location, summary.duration, summary.affected_scope].filter(Boolean).join(' · ')}</p>}
      </section>}
      {typeof result.intake_notice_draft === 'string' && <section>
        <h3>受理告知语草稿</h3>
        <Typography.Paragraph copyable>{result.intake_notice_draft}</Typography.Paragraph>
      </section>}
      {typeof edited.note === 'string' && <section>
        <h3>人工修订记录</h3><p>{edited.note}</p>
        {typeof edited.department_candidate === 'string' && <p>人工记录候选 · {edited.department_candidate}</p>}
      </section>}
    </div>
  )
}
