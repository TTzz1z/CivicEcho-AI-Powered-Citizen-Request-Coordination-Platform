import { api, extractDispositionFilename, triggerBlobDownload } from './client'
import type { ApiSuccess, AttachmentList, AttachmentType, AttachmentVisibility, TicketAttachment } from '../types'

export const attachmentKeys={ticket:(ticketId:string)=>['attachments',ticketId] as const}

export async function listAttachments(ticketId:string){
  return (await api.get<ApiSuccess<AttachmentList>>(`/tickets/${ticketId}/attachments`)).data.data
}

export async function uploadAttachment(ticketId:string,file:File,attachmentType:AttachmentType,visibility:AttachmentVisibility){
  const form=new FormData();form.append('file',file);form.append('attachment_type',attachmentType);form.append('visibility',visibility)
  return (await api.post<ApiSuccess<TicketAttachment>>(`/tickets/${ticketId}/attachments`,form,{timeout:60_000})).data.data
}

export async function deleteAttachment(attachmentId:string,reason:string){
  return (await api.delete<ApiSuccess<{deleted:boolean}>>(`/attachments/${attachmentId}`,{data:{reason}})).data.data
}

export async function downloadAttachment(attachment:TicketAttachment){
  const response=await api.get<Blob>(`/attachments/${attachment.id}/download`,{responseType:'blob',timeout:60_000})
  triggerBlobDownload(response.data,extractDispositionFilename(response.headers['content-disposition'],attachment.original_filename))
}

const previewTypes = new Set(['image/jpeg', 'image/png', 'image/webp', 'application/pdf'])

export function canPreviewAttachment(attachment: TicketAttachment) {
  return attachment.scan_status === 'clean' && previewTypes.has(attachment.content_type)
}

export async function loadAttachmentPreview(attachment: TicketAttachment, signal?: AbortSignal) {
  if (!canPreviewAttachment(attachment)) throw new Error('该附件不支持预览')
  const response = await api.get<Blob>(`/attachments/${attachment.id}/download`, {
    responseType: 'blob',
    timeout: 60_000,
    signal,
  })
  if (response.data.type !== attachment.content_type) throw new Error('文件类型不一致，请下载后核实')
  return response.data
}
