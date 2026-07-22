export type Role = 'citizen' | 'agent' | 'department_staff' | 'admin'
export type TicketStatus = 'pending' | 'accepted' | 'assigned' | 'processing' | 'resolved' | 'closed' | 'rejected'
export type Priority = 'normal' | 'expedited' | 'urgent' | 'major'
export type CollaborationStatus = 'none'|'awaiting_citizen'|'awaiting_dispatch'|'in_progress'|'awaiting_summary'|'awaiting_review'|'disputed'|'completed'
export type WorkOrderType = 'primary'|'support'|'review'
export type WorkOrderStatus = 'pending'|'processing'|'returned'|'transferred'|'submitted'|'cancelled'

export interface ApiSuccess<T> { success: true; data: T }
export interface ApiErrorBody { code: string; message: string; details?: Array<{ loc?: (string | number)[]; msg?: string }> | Record<string, unknown> | null }
export interface User { id: number; username: string; display_name: string; role: Role; department_id?: number | null; is_active: boolean }
export interface UserPage { items: User[]; page: number; page_size: number; total: number }
export interface UserFilters { page?:number; page_size?:number; keyword?:string; role?:Role; is_active?:boolean; department_id?:number; sort?:'username'|'display_name'|'role'|'created_at'; order?:'asc'|'desc' }
export interface Department { id: number; code: string; name: string; description?: string | null; is_active: boolean }
export interface Category { id:number; code:string; name:string; parent_id?:number|null; level:number; default_department_id?:number|null; default_department_name?:string|null; accept_sla_minutes:number; resolve_sla_minutes:number; is_active:boolean }
export interface TicketHistory { operation_type: string; content?: string | null; previous_status?: TicketStatus | null; current_status: TicketStatus; remark?: string | null; created_at: string }
export type FeedbackRating = 'satisfied' | 'mostly_satisfied' | 'dissatisfied'
export interface TicketFeedback { resolution_version:number; rating:FeedbackRating; comment?:string|null; result:'closed'|'reopened'; created_at:string }
export interface Ticket {
  ticket_id: string; request_type: string; description: string; location: string; event?: string | null;
  occurred_at_text?: string | null; occurred_at_start?: string | null; occurred_at_end?: string | null; occurred_at_precision?: string | null;
  timezone: string; target?: string | null; contact?: string | null; priority: Priority; status: TicketStatus; status_label?: string;
  category_id?:number|null; category_code?:string|null; category_name?:string|null; category_path?:string|null; requested_priority?:string|null; priority_confirmed_at?:string|null;
  department_name?: string | null; assigned_department_id?: number | null; assigned_user_id?: number | null; creator_name?: string | null; assignee_name?: string | null;
  source: string; version: number; accepted_at?: string | null; resolved_at?: string | null; closed_at?: string | null; created_at: string; updated_at: string;
  resolution_summary?:string|null; resolution_measures?:string|null; resolution_outcome?:'resolved'|'partially_resolved'|'unresolved'|null;
  public_reply?:string|null; internal_note?:string|null; rejection_reason_code?:string|null; rejection_detail?:string|null;
  suggested_channel?:string|null; needs_supplement:boolean; closure_type?:'citizen_confirmed'|'admin_override'|null;
  accept_due_at?:string|null; resolve_due_at?:string|null; remaining_seconds?:number|null; is_overdue:boolean; sla_state:'on_track'|'due_soon'|'overdue'|'paused'; sla_paused_at?:string|null; sla_pause_reason?:string|null; total_paused_seconds:number; reminder_count:number;
  collaboration_status:CollaborationStatus; supplement_reason?:string|null; supplement_requested_at?:string|null; supplemented_at?:string|null;
  dispatch_return_reason?:string|null; dispute_reason?:string|null; dispute_resolution?:string|null;
  handling_round:number; appeal_count:number;
  external_platform?:string|null; external_ticket_id?:string|null; external_sync_status?:string|null; external_synced_at?:string|null;
}
export interface WorkOrderHistory { action:string; previous_status?:WorkOrderStatus|null; current_status:WorkOrderStatus; content:string; created_at:string }
export interface WorkOrder {
  id:string; work_order_no:string; ticket_id:string; task_type:WorkOrderType; status:WorkOrderStatus;
  department_id:number; department_name?:string|null; assignee_user_id?:number|null; assignee_name?:string|null;
  instructions:string; result_summary?:string|null; result_measures?:string|null; result_outcome?:string|null;
  public_content?:string|null; internal_note?:string|null; return_reason?:string|null; source_work_order_id?:string|null;
  accepted_at?:string|null; submitted_at?:string|null; completed_at?:string|null; version:number; created_at:string; updated_at:string;
  history:WorkOrderHistory[];
}
export interface TicketDetail extends Ticket { history: TicketHistory[]; feedbacks:TicketFeedback[]; work_orders:WorkOrder[] }
export type AttachmentType = 'citizen_material'|'site_photo'|'official_document'|'processing_proof'|'other'
export type AttachmentVisibility = 'public'|'internal'
export interface TicketAttachment {
  id:string; ticket_id:string; uploader_user_id?:number|null; uploader_role:Role;
  attachment_type:AttachmentType; visibility:AttachmentVisibility; original_filename:string;
  content_type:string; size_bytes:number; sha256:string; scan_status:'clean'|'skipped';
  scan_engine?:string|null; scanned_at?:string|null; created_at:string;
}
export interface AttachmentList { items:TicketAttachment[]; total:number }
export interface TicketPage { items: Ticket[]; page: number; page_size: number; total: number }
export interface TicketFilters { page?: number; page_size?: number; status?: TicketStatus; request_type?: string; department_id?: number; category_id?:number; priority?:Priority; sla_state?:'on_track'|'due_soon'|'overdue'|'paused'; keyword?: string; created_from?: string; created_to?: string; mine?: boolean; my_department?: boolean; sort?: 'created_at'|'updated_at'|'priority'; order?: 'asc'|'desc' }
export interface Dashboard { metrics: {key:string;label:string;value:number;unit?:string|null}[]; status_distribution: ChartSlice[]; request_type_distribution: ChartSlice[]; department_distribution: ChartSlice[]; department_sla:{department_name:string;total:number;overdue:number;overdue_rate:number}[]; recent_tickets: Ticket[] }
export interface ChartSlice { name: string; value: number }
export interface AuditLog { id:number; actor_user_id?:number|null; actor_type:string; action:string; resource_type?:string|null; resource_id?:string|null; outcome:string; details?:string|null; request_id?:string|null; created_at:string }
export interface AuditPage { items: AuditLog[]; page:number; page_size:number; total:number }
export interface RasaMessage { recipient_id?: string; text?: string; buttons?: {title:string;payload:string}[]; custom?: Record<string, unknown>; image?: string }
export interface DraftPayload { type:'draft_extracted'; draft:{request_type?:string;description?:string;location?:string;occurred_at_text?:string;target?:string;contact?:string}; missing:string[] }
export type NotificationEvent='ticket_created'|'ticket_accepted'|'supplement_required'|'ticket_assigned'|'ticket_due_soon'|'processing_completed'|'awaiting_confirmation'|'ticket_closed'|'appeal_submitted'|'appeal_approved'|'appeal_rejected'|'appeal_completed'|'appeal_prompt'
export interface NotificationItem { id:string;ticket_id?:string|null;event_type:NotificationEvent;channel:string;title:string;content:string;status:'unread'|'read';delivery_status:string;read_at?:string|null;created_at:string }
export interface NotificationPage { items:NotificationItem[];page:number;page_size:number;total:number;unread_count:number }
export interface NotificationChannel { channel:string;label:string;enabled:boolean;phase:string }
export type AppealStatus='submitted'|'approved'|'rejected'|'reprocessing'|'completed'
export interface Appeal { id:string;appeal_no:string;ticket_id:string;citizen_user_id?:number|null;citizen_name?:string|null;sequence:number;status:AppealStatus;reason:string;desired_resolution:string;review_comment?:string|null;reviewed_by_user_id?:number|null;reviewer_name?:string|null;reviewed_at?:string|null;reprocess_instructions?:string|null;result_summary?:string|null;completed_at?:string|null;created_at:string;updated_at:string }
export interface AppealPage { items:Appeal[];page:number;page_size:number;total:number }
export type FollowUpStatus='pending'|'in_progress'|'completed'|'cancelled'
export interface PhoneFollowUpRecord { id:string;task_id:string;ticket_id:string;caller_user_id?:number|null;caller_name?:string|null;contact_result:'reached'|'no_answer'|'wrong_number';satisfaction?:FeedbackRating|null;outcome:'confirmed'|'needs_followup'|'appeal_requested';notes:string;created_at:string }
export interface FollowUpTask { id:string;ticket_id:string;handling_round:number;status:FollowUpStatus;assigned_user_id?:number|null;assignee_name?:string|null;due_at:string;completed_at?:string|null;created_at:string;updated_at:string;records:PhoneFollowUpRecord[] }
export interface FollowUpPage { items:FollowUpTask[];page:number;page_size:number;total:number }
export type AiSuggestionType='assignment'|'similarity'|'summary'|'completeness'|'document_draft'|'risk'|'triage_assistant'|'handling_assistant'|'ticket_advice'
export interface AiSuggestion { id:string;ticket_id:string;suggestion_type:AiSuggestionType;status:string;risk_level:'none'|'attention'|'urgent'|'sensitive';confidence:number;provider:string;model_name:string;result:Record<string,unknown>;explanation?:string|null;review_decision?:'helpful'|'not_helpful'|'adopted'|'adopted_with_edits'|'rejected'|null;review_comment?:string|null;reviewed_at?:string|null;created_at:string;advisory_only:true }
export interface Hotspot { cluster_key:string;label:string;count:number;urgent_count:number;sample_ticket_ids:string[] }
export interface IntegrationStatus { integration_type:string;enabled:boolean;configured:boolean;mode:string;message:string }

// ===== Knowledge Base (RAG) =====
export type KbType = 'policy' | 'guide' | 'faq' | 'internal' | 'procedure' | 'case'
export type KbVisibility = 'PUBLIC' | 'DEPARTMENT' | 'INTERNAL'
export type KbDocStatus = 'DRAFT' | 'REVIEWING' | 'PUBLISHED' | 'REJECTED' | 'WITHDRAWN' | 'EXPIRED' | 'PARSE_FAILED'
export type KbParseStatus = 'pending' | 'parsing' | 'done' | 'failed'
export type KbIndexStatus = 'pending' | 'building' | 'ready' | 'failed'
export type KbOcrStatus = 'none' | 'required' | 'done' | 'failed'
export type KbFeedbackType = 'helpful' | 'inaccurate' | 'outdated' | 'no_answer'
export type KbNoAnswerStatus = 'open' | 'assigned' | 'resolved' | 'wont_fix'

export interface KbDocument {
  id: number; title: string; doc_number?: string | null; kb_type: KbType
  domain?: string | null; region?: string | null; audience?: string | null
  visibility: KbVisibility; status: KbDocStatus; version: number
  parent_version_id?: number | null; replaces_doc_id?: number | null
  department_id?: number | null; department_name?: string | null
  published_department_name?: string | null
  source_url?: string | null; keywords?: string | null
  chunk_count: number; parse_status: KbParseStatus; index_status: KbIndexStatus
  ocr_status: KbOcrStatus; file_type: string
  original_filename?: string | null; file_size_bytes?: number | null
  embedding_model?: string | null
  review_comment?: string | null; rejected_reason?: string | null
  published_at?: string | null; effective_at?: string | null; expires_at?: string | null
  reviewed_at?: string | null; created_at: string; updated_at?: string | null
}
export interface KbDocumentDetail extends KbDocument {
  tags: string[]; meta: Record<string, unknown>
  uploaded_by_user_id?: number | null
  reviewed_by_user_id?: number | null
  published_by_user_id?: number | null
  storage_key?: string | null; mime_type?: string | null
  ocr_quality?: number | null; chunking_version?: string | null
  has_file: boolean; has_content: boolean
}
export interface KbDocPage { items: KbDocument[]; total: number; page: number; page_size: number }
export interface KbDocFilters {
  status?: KbDocStatus; kb_type?: KbType; visibility?: KbVisibility
  department_id?: number; domain?: string; keyword?: string
  page?: number; page_size?: number
}
export interface KbDocCreatePayload {
  title: string; doc_number?: string; kb_type?: KbType
  domain?: string; region?: string; audience?: string
  visibility?: KbVisibility; keywords?: string
  source_url?: string; effective_at?: string; expires_at?: string
  raw_content?: string; department_id?: number
  tags?: string[]; auto_publish?: boolean
}
export interface KbDocUpdatePayload {
  title?: string; doc_number?: string; kb_type?: KbType
  domain?: string; region?: string; audience?: string
  visibility?: KbVisibility; keywords?: string
  source_url?: string; effective_at?: string; expires_at?: string
  department_id?: number; tags?: string[]
}
export interface KbUploadPayload {
  title?: string; doc_number?: string; kb_type?: KbType
  domain?: string; region?: string; audience?: string
  visibility?: KbVisibility; keywords?: string
  source_url?: string; effective_at?: string; expires_at?: string
  department_id?: number; tags?: string
  doc_id?: number; auto_publish?: boolean
}
export interface KbChunk {
  id: number; document_id: number; chunk_index: number
  content: string; char_count: number; token_count: number
  chunk_hash?: string | null; keywords: string[]
  has_embedding: boolean
  embedding_status?: 'external' | 'hash_fallback' | 'missing' | 'failed'
  embedding_model?: string | null
  embedding_provider?: string | null
  embedding_dimension?: number | null
  embedding_fallback?: string | null
  created_at?: string | null
}
export interface KbChunkPage { items: KbChunk[]; total: number; page: number; page_size: number }

export interface KbCitation {
  index: number; doc_id: number; title: string
  doc_number?: string | null; issuing_authority?: string | null
  kb_type?: KbType | null
  department?: string | null; published_at?: string | null
  effective_at?: string | null; expires_at?: string | null
  status?: string | null; version?: number | null
  is_expired: boolean; excerpt?: string
  chunk_index?: number | null; score?: number
}
export interface KbRagAnswer {
  answer: string; citations: KbCitation[]
  no_evidence: boolean; retrieval_count: number
  latency_ms: number; generated_at: string
  provider?: string; model?: string
}
export interface KbRetrievalChunk {
  chunk_id: number; content: string
  score: number; chunk_index: number
  char_count: number; is_expired: boolean
  document: Record<string, unknown>
}
export interface KbRetrievalResult {
  chunks: KbRetrievalChunk[]
  accessible_doc_count: number; no_evidence: boolean
}
export interface KbRagQuery {
  query: string; region?: string; domain?: string
  audience?: string; top_k?: number
}

export interface KbFeedback {
  id: number; user_id?: number | null
  query_text: string; answer_text?: string | null
  document_ids: string[]; feedback_type: KbFeedbackType
  comment?: string | null; route?: string | null
  created_at: string
}
export interface KbFeedbackPage { items: KbFeedback[]; total: number; page: number; page_size: number }
export interface KbFeedbackPayload {
  query_text: string; answer_text?: string
  document_ids: number[]; feedback_type: KbFeedbackType
  comment?: string; route?: string
}

export interface KbNoAnswer {
  id: number; query_text: string
  user_id?: number | null; role?: string | null
  route?: string | null; retrieved_doc_ids: string[]
  status: KbNoAnswerStatus; assigned_department_id?: number | null
  resolution_note?: string | null
  created_at: string; resolved_at?: string | null
}
export interface KbNoAnswerPage { items: KbNoAnswer[]; total: number; page: number; page_size: number }

export interface KbEvalCase {
  id: number; title: string; domain?: string | null
  scenario: string; query: string
  expected_answer_summary?: string | null
  expected_doc_ids?: string | null
  must_cite_doc_ids?: string | null
  must_not_cite_doc_ids?: string | null
  must_avoid_keywords?: string | null
  expected_role: string; expected_no_answer: boolean
  notes?: string | null; is_active: boolean
  created_at: string; updated_at?: string | null
}
export interface KbEvalCasePayload {
  title: string; domain?: string; scenario: string
  query: string; expected_answer_summary?: string
  expected_doc_ids?: string; must_cite_doc_ids?: string
  must_not_cite_doc_ids?: string; must_avoid_keywords?: string
  expected_role?: string; expected_no_answer?: boolean
  notes?: string; is_active?: boolean
}
export interface KbEvalRunResult {
  total: number
  metrics: {
    retrieval_hit_rate: number
    citation_correct_rate: number
    answer_faithful_rate: number
    expired_policy_blocked_rate: number
    permission_isolated_rate: number
    no_answer_rate: number
    avg_latency_ms: number
  }
  runs: Array<{
    case_id: number; title: string; scenario: string
    retrieval_hit: boolean; citation_correct: boolean
    answer_faithful: boolean; expired_policy_blocked: boolean
    permission_isolated: boolean; no_evidence: boolean
    latency_ms: number
  }>
}

export interface KbTicketAdvice {
  /** Stable suggestion id for audit / review evidence chain (backend advice_id). */
  advice_id?: string
  applicable_policies: string[]
  verification_needed: string[]
  material_completeness: string
  suggested_steps: string[]
  responsibility_boundary: string
  timeline_risk: string
  similar_cases: string[]
  reply_draft: string
  citations: KbCitation[]
  no_evidence: boolean
  generated_at: string
  provider?: string; model?: string
  /** Optional suggestion schema / content version from backend. */
  suggestion_version?: number | string | null
}
