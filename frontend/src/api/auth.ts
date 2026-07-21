import { api, tokenStore } from './client'
import type { ApiSuccess, User } from '../types'
export async function login(username:string,password:string){ const {data}=await api.post<ApiSuccess<{access_token:string;token_type:string;expires_in:number}>>('/auth/login',{username,password}); tokenStore.set(data.data.access_token); return data.data }
export async function getMe(){ return (await api.get<ApiSuccess<User>>('/auth/me')).data.data }
