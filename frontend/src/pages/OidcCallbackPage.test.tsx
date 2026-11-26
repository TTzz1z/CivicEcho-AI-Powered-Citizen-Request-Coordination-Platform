import { StrictMode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { OidcCallbackPage } from './OidcCallbackPage'

const oidc = vi.hoisted(() => ({ config: vi.fn(), exchange: vi.fn(), refresh: vi.fn() }))
vi.mock('../api/intelligence', () => ({ getOidcConfig: oidc.config, exchangeOidcCode: oidc.exchange }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ refresh: oidc.refresh }) }))

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

function callbackAt(path: string) {
  return renderApp(<StrictMode><MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/auth/oidc/callback" element={<OidcCallbackPage />} />
      <Route path="/agent/tickets" element={<h1>坐席工单</h1>} />
    </Routes>
  </MemoryRouter></StrictMode>)
}

it('allows return to sign-in when the callback state is missing', async () => {
  callbackAt('/auth/oidc/callback')
  expect(await screen.findByRole('alert')).toHaveTextContent('登录请求已失效')
  expect(screen.getByRole('link', { name: '返回登录' })).toHaveAttribute('href', '/login')
  expect(oidc.exchange).not.toHaveBeenCalled()
})

it('consumes the callback state and exchanges once under StrictMode', async () => {
  sessionStorage.setItem('tingting_oidc_state', 'test-state')
  oidc.config.mockResolvedValue({ enabled: true, redirect_uri: 'https://fixture.example/auth/oidc/callback' })
  oidc.exchange.mockResolvedValue({ access_token: 'fixture-only' })
  oidc.refresh.mockResolvedValue({ id: 4, role: 'agent' })
  callbackAt('/auth/oidc/callback?state=test-state&code=fixture-code')

  expect(await screen.findByRole('heading', { name: '坐席工单' })).toBeVisible()
  expect(oidc.exchange).toHaveBeenCalledTimes(1)
  expect(sessionStorage.getItem('tingting_oidc_state')).toBeNull()
})
