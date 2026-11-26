/** Warm the service before timing browser workflows. */
import { request as apiRequest } from '@playwright/test'

import { e2ePassword as PASSWORD } from './env'
const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8081'

async function pingBackend(): Promise<void> {
  const ctx = await apiRequest.newContext({ baseURL: BASE_URL })
  try {
    const res = await ctx.get('/healthz', { timeout: 10_000 })
    if (!res.ok()) throw new Error(`E2E entrypoint health check failed with HTTP ${res.status()}`)
    console.log(`[global-setup] entrypoint healthy (status=${res.status()})`)
  } finally {
    await ctx.dispose()
  }
}

async function warmOrchestrator(): Promise<void> {
  // A rule-routed greeting warms up the orchestrator without a provider call.
  const ctx = await apiRequest.newContext({ baseURL: BASE_URL })
  try {
    const loginRes = await ctx.post('/api/v1/auth/login', {
      data: { username: 'citizen_local', password: PASSWORD },
    })
    if (!loginRes.ok()) {
      console.log(`[global-setup] orchestrator warmup login failed: ${loginRes.status()}`)
      return
    }
    const token = (await loginRes.json()).data.access_token
    const chatRes = await ctx.post('/api/v1/orchestrator/chat', {
      headers: { Authorization: `Bearer ${token}` },
      data: { message: '你好', session_id: 'e2e-warmup-session' },
      timeout: 30_000,
    })
    console.log(`[global-setup] orchestrator warmup status=${chatRes.status()} (non-fatal)`)
  } catch (e) {
    console.log(`[global-setup] orchestrator warmup failed (non-fatal): ${(e as Error).message}`)
  } finally {
    await ctx.dispose()
  }
}

export default async function globalSetup(): Promise<void> {
  console.log('[global-setup] starting E2E warm-up')
  await pingBackend()
  await warmOrchestrator()
  console.log('[global-setup] warm-up complete')
}
