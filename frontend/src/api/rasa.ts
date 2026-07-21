import axios from 'axios'
import type { RasaMessage } from '../types'
import { createRequestId } from './client'
export async function sendRasaMessage(sender:string,message:string){const requestId=createRequestId();return (await axios.post<RasaMessage[]>('/rasa/webhooks/rest/webhook',{sender,message,metadata:{request_id:requestId}},{timeout:20_000,headers:{'X-Request-ID':requestId}})).data}
