import { api } from './client'
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

function responseFilename(disposition:string|undefined,fallback:string){
  const encoded=disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if(!encoded)return fallback
  try{return decodeURIComponent(encoded)}catch{return fallback}
}

export async function downloadAttachment(attachment:TicketAttachment){
  const response=await api.get<Blob>(`/attachments/${attachment.id}/download`,{responseType:'blob',timeout:60_000})
  const url=URL.createObjectURL(response.data)
  const anchor=document.createElement('a');anchor.href=url;anchor.download=responseFilename(response.headers['content-disposition'],attachment.original_filename)
  document.body.appendChild(anchor);anchor.click();anchor.remove();URL.revokeObjectURL(url)
}
