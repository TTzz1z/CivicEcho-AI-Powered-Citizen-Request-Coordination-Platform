import { ApiError, api } from './client'
import { consumeSseStream, openSseFetch } from './sse'
import type {
  ApiSuccess, KbChunkPage, KbCitation, KbDocCreatePayload, KbDocFilters, KbDocPage,
  KbDocUpdatePayload, KbDocument, KbDocumentDetail, KbEvalCase,
  KbEvalCasePayload, KbEvalRunResult, KbFeedbackPage,
  KbFeedbackPayload, KbNoAnswerPage, KbNoAnswerStatus,
  KbRagAnswer, KbRagQuery, KbRetrievalResult, KbTicketAdvice,
  KbUploadPayload,
} from '../types'

const BASE = '/kb'

// ===== Documents =====

export async function listKbDocuments(filters: KbDocFilters = {}): Promise<KbDocPage> {
  return (await api.get<ApiSuccess<KbDocPage>>(`${BASE}/documents`, { params: filters })).data.data
}

export async function getKbDocument(docId: number): Promise<KbDocumentDetail> {
  return (await api.get<ApiSuccess<KbDocumentDetail>>(`${BASE}/documents/${docId}`)).data.data
}

export async function createKbDocument(payload: KbDocCreatePayload): Promise<KbDocument> {
  return (await api.post<ApiSuccess<KbDocument>>(`${BASE}/documents`, payload)).data.data
}

export async function updateKbDocument(docId: number, payload: KbDocUpdatePayload): Promise<KbDocument> {
  return (await api.patch<ApiSuccess<KbDocument>>(`${BASE}/documents/${docId}`, payload)).data.data
}

export async function uploadKbDocument(file: File, payload: KbUploadPayload): Promise<KbDocument> {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(payload)) {
    if (v !== undefined && v !== null) form.append(k, String(v))
  }
  return (await api.post<ApiSuccess<KbDocument>>(`${BASE}/documents/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60_000,
  })).data.data
}

export async function downloadKbDocumentUrl(docId: number): Promise<string> {
  // axios baseURL already includes /api/v1
  return `/api/v1${BASE}/documents/${docId}/download`
}

// ===== Lifecycle =====

export async function submitKbForReview(docId: number): Promise<void> {
  await api.post(`${BASE}/documents/${docId}/submit-review`)
}

export async function reviewKbDocument(docId: number, decision: 'publish' | 'reject', comment = ''): Promise<void> {
  await api.post(`${BASE}/documents/${docId}/review`, { decision, comment })
}

export async function directPublishKbDocument(docId: number, comment = ''): Promise<void> {
  await api.post(`${BASE}/documents/${docId}/publish`, { comment })
}

export async function withdrawKbDocument(docId: number, reason = ''): Promise<void> {
  await api.post(`${BASE}/documents/${docId}/withdraw`, { reason })
}

export async function expireKbDocument(docId: number, reason = ''): Promise<void> {
  await api.post(`${BASE}/documents/${docId}/expire`, { reason })
}

export async function reindexKbDocument(docId: number): Promise<{ id: number; parse_status: string; index_status: string; chunk_count: number; embedding_model?: string }> {
  return (await api.post<ApiSuccess<{ id: number; parse_status: string; index_status: string; chunk_count: number; embedding_model?: string }>>(`${BASE}/documents/${docId}/reindex`)).data.data
}

export async function listKbDocumentVersions(docId: number): Promise<KbDocument[]> {
  return (await api.get<ApiSuccess<KbDocument[]>>(`${BASE}/documents/${docId}/versions`)).data.data
}

export async function listKbChunks(docId: number, page = 1, pageSize = 20): Promise<KbChunkPage> {
  return (await api.get<ApiSuccess<KbChunkPage>>(`${BASE}/documents/${docId}/chunks`, { params: { page, page_size: pageSize } })).data.data
}

// ===== RAG =====

export async function ragQuery(payload: KbRagQuery): Promise<KbRagAnswer> {
  return (await api.post<ApiSuccess<KbRagAnswer>>(`${BASE}/query`, payload, { timeout: 60_000 })).data.data
}

export interface KbRagStreamMeta {
  citations: KbCitation[]
  no_evidence: boolean
  retrieval_count: number
  route: string
  advisory_only?: boolean
}

export interface KbRagStreamDone extends KbRagAnswer {
  usage_unavailable?: boolean
  advisory_only?: boolean
}

export interface KbRagStreamHandlers {
  onMeta?: (meta: KbRagStreamMeta) => void
  onDelta?: (text: string) => void
  onDone?: (done: KbRagStreamDone) => void
  onError?: (err: { code: string; message: string }) => void
}

export async function streamRagQuery(
  payload: KbRagQuery,
  handlers: KbRagStreamHandlers = {},
  signal?: AbortSignal,
): Promise<KbRagStreamDone> {
  const response = await openSseFetch(`/api/v1${BASE}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
    clearAuthOn401: true,
  })
  if (!response.body) {
    throw new ApiError(0, 'STREAM_INCOMPLETE', '知识库流式响应不可用，请重试')
  }

  const state: { done: KbRagStreamDone | null; err: ApiError | null } = {
    done: null,
    err: null,
  }

  await consumeSseStream(
    response.body,
    ev => {
      if (!ev.data) return
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(ev.data) as Record<string, unknown>
      } catch {
        return
      }
      if (ev.event === 'meta') {
        handlers.onMeta?.(parsed as unknown as KbRagStreamMeta)
      } else if (ev.event === 'delta') {
        if (typeof parsed.text === 'string') handlers.onDelta?.(parsed.text)
      } else if (ev.event === 'done') {
        const done = parsed as unknown as KbRagStreamDone
        state.done = done
        handlers.onDone?.(done)
      } else if (ev.event === 'error') {
        const code = typeof parsed.code === 'string' ? parsed.code : 'STREAM_ERROR'
        const message = typeof parsed.message === 'string' ? parsed.message : '知识库流式问答暂时不可用，请重试。'
        handlers.onError?.({ code, message })
        state.err = new ApiError(500, code, message)
      }
    },
    signal,
  )

  if (state.err) throw state.err
  if (!state.done) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    throw new ApiError(0, 'STREAM_INCOMPLETE', '知识库流式响应意外中断，请重试')
  }
  return state.done
}

export async function ragRetrieve(payload: KbRagQuery): Promise<KbRetrievalResult> {
  return (await api.post<ApiSuccess<KbRetrievalResult>>(`${BASE}/retrieve`, payload, { timeout: 30_000 })).data.data
}

// ===== Feedback =====

export async function submitKbFeedback(payload: KbFeedbackPayload): Promise<void> {
  await api.post(`${BASE}/feedback`, payload)
}

export async function listKbFeedback(page = 1, pageSize = 20, feedbackType?: string): Promise<KbFeedbackPage> {
  return (await api.get<ApiSuccess<KbFeedbackPage>>(`${BASE}/feedback`, {
    params: { page, page_size: pageSize, feedback_type: feedbackType },
  })).data.data
}

// ===== No-answer questions (admin) =====

export async function listKbNoAnswer(page = 1, pageSize = 20, status?: KbNoAnswerStatus): Promise<KbNoAnswerPage> {
  return (await api.get<ApiSuccess<KbNoAnswerPage>>(`${BASE}/no-answer`, {
    params: { page, page_size: pageSize, status },
  })).data.data
}

export async function resolveKbNoAnswer(naId: number, status: KbNoAnswerStatus, note = ''): Promise<void> {
  await api.post(`${BASE}/no-answer/${naId}/resolve`, { status, note })
}

// ===== Evaluation (admin) =====

export async function listKbEvalCases(scenario?: string, activeOnly = true): Promise<KbEvalCase[]> {
  return (await api.get<ApiSuccess<KbEvalCase[]>>(`${BASE}/eval/cases`, {
    params: { scenario, active_only: activeOnly },
  })).data.data
}

export async function createKbEvalCase(payload: KbEvalCasePayload): Promise<KbEvalCase> {
  return (await api.post<ApiSuccess<KbEvalCase>>(`${BASE}/eval/cases`, payload)).data.data
}

export async function runKbEval(scenario?: string, role = 'citizen'): Promise<KbEvalRunResult> {
  return (await api.post<ApiSuccess<KbEvalRunResult>>(`${BASE}/eval/run`, { scenario, role }, { timeout: 120_000 })).data.data
}

// ===== Department AI ticket advice =====

export type KbAdviceReviewDecision = 'adopted' | 'adopted_with_edits' | 'rejected'

export interface KbAdviceReviewRequest {
  /** Required evidence-chain id from ticket_advice response. */
  advice_id: string
  decision: KbAdviceReviewDecision
  edit_summary?: string
  advice_snapshot?: Record<string, unknown>
}

export interface KbAdviceReviewRecord {
  id: number
  ticket_id: string
  decision: KbAdviceReviewDecision
  edit_summary: string | null
  advice_snapshot: Record<string, unknown> | null
  advice_id?: string | null
  suggestion_version?: number | string | null
  operator_user_id: number | null
  operator_role: string | null
  operator_name: string | null
  operated_at: string
  advisory_only: boolean
}

export interface KbAdviceReviewResult {
  ticket_id: string
  advice_id?: string | null
  decision: KbAdviceReviewDecision
  edit_summary: string | null
  operator_user_id: number | null
  operator_role: string | null
  operated_at: string
  advisory_only: boolean
  status_changed: boolean
}

export async function getKbTicketAdvice(ticketId: string): Promise<KbTicketAdvice> {
  return (await api.post<ApiSuccess<KbTicketAdvice>>(`${BASE}/tickets/${encodeURIComponent(ticketId)}/advice`, {}, { timeout: 60_000 })).data.data
}

export async function reviewKbTicketAdvice(ticketId: string, payload: KbAdviceReviewRequest): Promise<KbAdviceReviewResult> {
  return (await api.post<ApiSuccess<KbAdviceReviewResult>>(`${BASE}/tickets/${encodeURIComponent(ticketId)}/advice/review`, payload)).data.data
}

export async function listKbTicketAdviceReviews(ticketId: string): Promise<KbAdviceReviewRecord[]> {
  return (await api.get<ApiSuccess<KbAdviceReviewRecord[]>>(`${BASE}/tickets/${encodeURIComponent(ticketId)}/advice/reviews`)).data.data
}
