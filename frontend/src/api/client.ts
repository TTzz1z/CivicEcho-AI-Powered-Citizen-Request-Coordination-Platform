import axios, { AxiosError } from 'axios'
import type { ApiErrorBody } from '../types'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: ApiErrorBody['details']) { super(message); this.name = 'ApiError' }
}

export const tokenStore = {
  get: () => sessionStorage.getItem('tingting_access_token'),
  set: (token: string) => sessionStorage.setItem('tingting_access_token', token),
  clear: () => sessionStorage.removeItem('tingting_access_token'),
}

export const api = axios.create({ baseURL: '/api/v1', timeout: 12_000 })
export function createRequestId(){return crypto.randomUUID().replaceAll('-','')}
api.interceptors.request.use(config => { const token = tokenStore.get(); if (token) config.headers.Authorization = `Bearer ${token}`; config.headers['X-Request-ID']=createRequestId(); return config })
api.interceptors.response.use(r => r, (error: AxiosError<{error?: ApiErrorBody}>) => {
  const status = error.response?.status ?? 0
  const body = error.response?.data?.error
  if (status === 401) { tokenStore.clear(); window.dispatchEvent(new Event('tingting:unauthorized')) }
  const message = body?.message || (status >= 500 ? '服务暂时不可用，请稍后重试' : status === 0 ? '网络连接失败，请检查服务状态' : '请求未能完成')
  return Promise.reject(new ApiError(status, body?.code || 'NETWORK_ERROR', message, body?.details))
})
