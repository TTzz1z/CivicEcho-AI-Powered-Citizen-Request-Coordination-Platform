import { api, tokenStore } from './client'
import type { ApiSuccess, AuthTokenResponse, ChangePasswordPayload, CitizenRegisterPayload, User } from '../types'

export async function login(username: string, password: string) {
  const { data } = await api.post<ApiSuccess<AuthTokenResponse>>('/auth/login', { username, password })
  tokenStore.set(data.data.access_token)
  return data.data
}

export async function register(payload: CitizenRegisterPayload) {
  const body: CitizenRegisterPayload = {
    username: payload.username.trim(),
    password: payload.password,
  }
  const displayName = payload.display_name?.trim()
  if (displayName) body.display_name = displayName
  const phone = payload.phone?.trim()
  if (phone) body.phone = phone

  const { data } = await api.post<ApiSuccess<AuthTokenResponse>>('/auth/register', body)
  tokenStore.set(data.data.access_token)
  return data.data
}

export async function changePassword(payload: ChangePasswordPayload) {
  const { data } = await api.post<ApiSuccess<AuthTokenResponse>>('/auth/change-password', payload)
  tokenStore.set(data.data.access_token)
  return data.data
}

export async function getMe() {
  return (await api.get<ApiSuccess<User>>('/auth/me')).data.data
}

export async function logoutApi(token: string) {
  return (await api.post<ApiSuccess<{ revoked: boolean }>>('/auth/logout', undefined, {
    headers: { Authorization: `Bearer ${token}` },
  })).data.data
}
