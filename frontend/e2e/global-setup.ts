/**
 * Round 2 r2-9: E2E global setup.
 *
 * Warms up Rasa and the backend so the first real test doesn't pay the
 * 4-8s cold-start cost (Round 1 root cause #4 / #8). Also seeds a chat
 * session so the action server is hot.
 */
import { chromium, expect, FullConfig, request as apiRequest } from '@playwright/test'

const PASSWORD = process.env.E2E_PASSWORD || 'tingting-seed-demo-2026'
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8081'

async function pingRasa(): Promise<void> {
  // Best-effort: send a warm-up message to /rasa/webhooks/rest/webhook so the
  // action server is hot before any test runs. Failures are logged but not
  // fatal — tests will still surface real Rasa errors.
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 30_000)
  try {
    const res = await fetch(`${BASE_URL}/rasa/webhooks/rest/webhook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sender: 'e2e-warmup',
        message: '/greet',
      }),
      signal: controller.signal,
    })
    if (!res.ok) {
      console.log(`[global-setup] rasa warmup http=${res.status} (non-fatal)`)
    } else {
      console.log('[global-setup] rasa warmup ok')
    }
  } catch (e) {
    console.log(`[global-setup] rasa warmup failed (non-fatal): ${(e as Error).message}`)
  } finally {
    clearTimeout(timeout)
  }
}

async function pingBackend(): Promise<void> {
  // Verify backend health so tests fail fast with a clear message if it's down.
  const ctx = await apiRequest.newContext({ baseURL: BASE_URL })
  try {
    const res = await ctx.get('/api/v1/auth/me')
    // 401 is fine — we just need the backend to answer.
    if (res.status() >= 500) {
      console.log(`[global-setup] backend unhealthy: GET /api/v1/auth/me -> ${res.status()}`)
    } else {
      console.log(`[global-setup] backend healthy (status=${res.status()})`)
    }
  } catch (e) {
    console.log(`[global-setup] backend ping failed: ${(e as Error).message}`)
  } finally {
    await ctx.dispose()
  }
}

async function warmOrchestrator(): Promise<void> {
  // Warm the orchestrator + LLM/embedding clients with a trivial policy query
  // so the first real test doesn't pay LLM cold-start latency.
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

export default async function globalSetup(config: FullConfig): Promise<void> {
  console.log('[global-setup] starting r2-9 warm-up sequence')
  await pingBackend()
  await pingRasa()
  await warmOrchestrator()
  console.log('[global-setup] warm-up complete')
}
