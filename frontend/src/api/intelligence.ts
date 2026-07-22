import { api } from './client'
import type { AiSuggestion, AiSuggestionType, Hotspot, IntegrationStatus } from '../types'

export async function analyzeTicket(
  ticketId: string,
  suggestionTypes: AiSuggestionType[],
  capability?: 'triage_assistant' | 'handling_assistant',
) {
  return (await api.post<{ data: AiSuggestion[] }>(`/ai/tickets/${encodeURIComponent(ticketId)}/analyze`, {
    suggestion_types: suggestionTypes,
    capability,
  })).data.data
}
export async function listSuggestions(ticketId: string) {
  return (await api.get<{ data: AiSuggestion[] }>(`/ai/tickets/${encodeURIComponent(ticketId)}/suggestions`)).data.data
}
export async function reviewSuggestion(
  id: string,
  decision: 'helpful' | 'not_helpful' | 'adopted' | 'adopted_with_edits' | 'rejected',
  comment?: string,
  edited_content?: Record<string, unknown>,
) {
  return (await api.post<{ data: AiSuggestion }>(`/ai/suggestions/${id}/review`, { decision, comment, edited_content })).data.data
}
export async function listHotspots(days=30){return (await api.get<{data:Hotspot[]}>('/ai/hotspots',{params:{days}})).data.data}
export async function listIntegrationStatuses(){return (await api.get<{data:IntegrationStatus[]}>('/integrations/status')).data.data}
export async function syncDirectory(){return (await api.post<{data:{created:number;updated:number;skipped:number}}>('/integrations/directory/sync')).data.data}
export async function syncExternalTicket(ticketId:string){return (await api.post<{data:{external_ticket_id:string;status:string}}>(`/integrations/tickets/${encodeURIComponent(ticketId)}/sync`,{force:false})).data.data}

export interface PreReviewPayload { description:string; request_type?:string; location?:string; occurred_at_text?:string; target?:string; contact?:string }
export interface PreReviewData { identified_type:string; identified_location:string; identified_time:string; identified_target:string; impact:string; urgency_hint:string; missing_fields:string[]; field_tips:Record<string,string>; normalized_description:string; recommended_department:string|null; department_reason:string|null; provider:string; advisory_only:true }
export async function preReview(payload:PreReviewPayload){return (await api.post<{data:PreReviewData}>('/ai/pre-review',payload)).data.data}

export interface OidcConfig {enabled:boolean;issuer?:string|null;client_id?:string|null;redirect_uri?:string|null;scopes:string;authorization_endpoint?:string|null}
export async function getOidcConfig(){return (await api.get<{data:OidcConfig}>('/auth/oidc/config')).data.data}
export async function exchangeOidcCode(code:string,redirect_uri:string){return (await api.post<{data:{access_token:string}}>('/auth/oidc/exchange',{code,redirect_uri})).data.data}
