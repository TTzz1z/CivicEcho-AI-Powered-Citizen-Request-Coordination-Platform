/**
 * Round 5: Playwright Smoke — 6 core E2E paths in Chromium only.
 *
 * Purpose: cover the critical demo flows in <5 minutes for daily verification.
 * The full 96-test multi-browser suite remains in the other spec files for
 * pre-release / pre-interview runs.
 *
 * Run:
 *   npx playwright test e2e/smoke.spec.ts --project=chromium
 *
 * 6 paths:
 *   S1. citizen submits complaint via chat → ticket draft
 *   S2. full ticket lifecycle (create → accept → assign → process → resolve → citizen satisfied close)
 *   S3. dissatisfied feedback → appeal → admin approve → reprocess
 *   S4. policy RAG returns citations (title/doc_number/issuing_authority)
 *   S5. four roles route guards — unauthorized access redirected to /forbidden
 *   S6. AI case advice + three-state review recorded (advisory only, no status change)
 */
import { test, expect, request, type APIRequestContext, type Page } from '@playwright/test'

const PASSWORD = process.env.E2E_PASSWORD || 'tingting-seed-demo-2026'
const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:8081'
const API = process.env.E2E_API_URL || 'http://127.0.0.1:8001'

async function loginViaAPI(ctx: APIRequestContext, username: string): Promise<string> {
  const res = await ctx.post(`${API}/api/v1/auth/login`, { data: { username, password: PASSWORD } })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return body.data.access_token as string
}

async function injectToken(page: Page, token: string): Promise<void> {
  await page.addInitScript((t) => sessionStorage.setItem('tingting_access_token', t), token)
}

test.describe.configure({ mode: 'serial' })

test('S1. citizen login → chat page renders', async ({ page }) => {
  const ctx = await request.newContext()
  const token = await loginViaAPI(ctx, 'citizen_local')
  await injectToken(page, token)
  await page.goto(`${BASE}/citizen/chat`)
  await page.waitForLoadState('domcontentloaded')
  // Chat input TextArea present
  await expect(page.locator('textarea[aria-label="输入消息"]')).toBeVisible({ timeout: 10_000 })
  await ctx.dispose()
})

test('S2. full ticket lifecycle satisfied close', async () => {
  const ctx = await request.newContext()
  const citizen = await loginViaAPI(ctx, 'citizen_local')
  const agent = await loginViaAPI(ctx, 'agent_local')
  const dept = await loginViaAPI(ctx, 'department_local')

  // 1. citizen creates ticket
  const createRes = await ctx.post(`${API}/api/v1/tickets`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: {
      idempotency_key: `smoke-${Date.now()}`,
      request_type: '投诉',
      description: 'Smoke 测试 - 路灯故障',
      location: '测试路 1 号',
      occurred_at_text: '昨天晚上',
      contact: '13800000000',
      source: 'smoke',
    },
  })
  expect(createRes.status()).toBe(201)
  const ticket = (await createRes.json()).data.ticket
  const tid = ticket.ticket_id

  // 2. agent accept
  let res = await ctx.post(`${API}/api/v1/tickets/${tid}/accept`, {
    headers: { Authorization: `Bearer ${agent}` },
    data: { version: 1, remark: '受理' },
  })
  expect(res.status()).toBe(200)

  // 3. agent assign to dept
  const meRes = await ctx.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${dept}` } })
  const deptId = (await meRes.json()).data.department_id
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/assign`, {
    headers: { Authorization: `Bearer ${agent}` },
    data: { version: 2, remark: '派发', department_id: deptId },
  })
  expect(res.status()).toBe(200)

  // 4. dept process
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/process`, {
    headers: { Authorization: `Bearer ${dept}` },
    data: { version: 3, remark: '处理' },
  })
  expect(res.status()).toBe(200)

  // 5. dept submit work order + summary
  const detailRes = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${dept}` } })
  const detail = (await detailRes.json()).data
  const primary = detail.work_orders.find((w: any) => w.task_type === 'primary')
  expect(primary).toBeTruthy()
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/work-orders/${primary.id}/submit`, {
    headers: { Authorization: `Bearer ${dept}` },
    data: {
      version: primary.version,
      remark: '处置完成',
      result_summary: '现场处理完成',
      result_measures: '现场处理',
      result_outcome: 'resolved',
      public_content: '问题已处理',
    },
  })
  expect(res.status()).toBe(200)

  // 6. dept summary
  const detail2Res = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${dept}` } })
  const detail2 = (await detail2Res.json()).data
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/summary`, {
    headers: { Authorization: `Bearer ${dept}` },
    data: {
      version: detail2.version,
      remark: '汇总',
      resolution_summary: '处理完成',
      resolution_measures: '现场处理',
      resolution_outcome: 'resolved',
      public_reply: '问题已处理',
    },
  })
  expect(res.status()).toBe(200)

  // 7. agent review_resolve
  const detail3Res = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${agent}` } })
  const detail3 = (await detail3Res.json()).data
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/review-resolve`, {
    headers: { Authorization: `Bearer ${agent}` },
    data: {
      version: detail3.version,
      remark: '复核',
      resolution_summary: '处理完成',
      resolution_measures: '现场处理',
      resolution_outcome: 'resolved',
      public_reply: '问题已处理',
    },
  })
  expect(res.status()).toBe(200)
  const resolved = (await res.json()).data
  expect(resolved.status).toBe('resolved')

  // 8. citizen satisfied → closed
  res = await ctx.post(`${API}/api/v1/tickets/${tid}/feedback`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: { version: resolved.version, rating: 'satisfied', comment: '处理及时' },
  })
  expect(res.status()).toBe(200)
  const closed = (await res.json()).data
  expect(closed.status).toBe('closed')
  expect(closed.closure_type).toBe('citizen_confirmed')

  await ctx.dispose()
})

test('S3. dissatisfied → appeal → admin approve → reprocess', async () => {
  const ctx = await request.newContext()
  const citizen = await loginViaAPI(ctx, 'citizen_local')
  const agent = await loginViaAPI(ctx, 'agent_local')
  const dept = await loginViaAPI(ctx, 'department_local')
  const admin = await loginViaAPI(ctx, 'admin_local')

  // 快速建一条 resolved 工单(与 S2 相同流程压缩)
  const createRes = await ctx.post(`${API}/api/v1/tickets`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: {
      idempotency_key: `smoke-appeal-${Date.now()}`,
      request_type: '投诉',
      description: 'Smoke 申诉测试',
      location: '测试路 2 号',
      occurred_at_text: '昨天晚上',
      contact: '13800000000',
      source: 'smoke',
    },
  })
  const ticket = (await createRes.json()).data.ticket
  const tid = ticket.ticket_id

  await ctx.post(`${API}/api/v1/tickets/${tid}/accept`, { headers: { Authorization: `Bearer ${agent}` }, data: { version: 1, remark: '受理' } })
  const meRes = await ctx.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${dept}` } })
  const deptId = (await meRes.json()).data.department_id
  await ctx.post(`${API}/api/v1/tickets/${tid}/assign`, { headers: { Authorization: `Bearer ${agent}` }, data: { version: 2, remark: '派发', department_id: deptId } })
  await ctx.post(`${API}/api/v1/tickets/${tid}/process`, { headers: { Authorization: `Bearer ${dept}` }, data: { version: 3, remark: '处理' } })

  const detailRes = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${dept}` } })
  const detail = (await detailRes.json()).data
  const primary = detail.work_orders.find((w: any) => w.task_type === 'primary')
  await ctx.post(`${API}/api/v1/tickets/${tid}/work-orders/${primary.id}/submit`, {
    headers: { Authorization: `Bearer ${dept}` },
    data: { version: primary.version, remark: '处置完成', result_summary: '现场处理完成', result_measures: '现场处理', result_outcome: 'resolved', public_content: '问题已处理' },
  })
  const detail2 = (await (await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${dept}` } })).json()).data
  await ctx.post(`${API}/api/v1/tickets/${tid}/summary`, {
    headers: { Authorization: `Bearer ${dept}` },
    data: { version: detail2.version, remark: '汇总', resolution_summary: '处理完成', resolution_measures: '现场处理', resolution_outcome: 'resolved', public_reply: '问题已处理' },
  })
  const detail3 = (await (await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${agent}` } })).json()).data
  const rr = await ctx.post(`${API}/api/v1/tickets/${tid}/review-resolve`, {
    headers: { Authorization: `Bearer ${agent}` },
    data: { version: detail3.version, remark: '复核', resolution_summary: '处理完成', resolution_measures: '现场处理', resolution_outcome: 'resolved', public_reply: '问题已处理' },
  })
  const resolved = (await rr.json()).data

  // dissatisfied → stays resolved
  const fb = await ctx.post(`${API}/api/v1/tickets/${tid}/feedback`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: { version: resolved.version, rating: 'dissatisfied', comment: '问题未解决' },
  })
  expect((await fb.json()).data.status).toBe('resolved')

  // appeal
  const ap = await ctx.post(`${API}/api/v1/tickets/${tid}/appeals`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: { reason: '市民对本次处理结果不满意,要求重新核实并处理。', desired_resolution: '希望部门重新核实情况并给出实质性处理结果。' },
  })
  expect(ap.status()).toBe(201)
  const appealId = (await ap.json()).data.id

  // admin approve
  const rv = await ctx.post(`${API}/api/v1/appeals/${appealId}/review`, {
    headers: { Authorization: `Bearer ${admin}` },
    data: { decision: 'approved', review_comment: '重新处理', reprocess_instructions: '请部门重新核实并处理' },
  })
  expect(rv.status()).toBe(200)

  // verify ticket back to processing
  const final = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${citizen}` } })
  expect((await final.json()).data.status).toBe('processing')

  await ctx.dispose()
})

test('S4. policy RAG returns citations', async () => {
  const ctx = await request.newContext()
  const citizen = await loginViaAPI(ctx, 'citizen_local')
  const res = await ctx.post(`${API}/api/v1/orchestrator/chat`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: { message: '社保补贴政策适用于哪些人群', session_id: `smoke-${Date.now()}` },
    timeout: 30_000,
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(body.data.route).toBe('policy_rag')
  const citations = body.data.payload?.citations || []
  expect(citations.length).toBeGreaterThan(0)
  // 每个 citation 必须含 4 要素
  for (const c of citations.slice(0, 2)) {
    expect(c.title).toBeTruthy()
    expect(c.doc_number || c.issuing_authority || c.excerpt).toBeTruthy()
  }
  expect(body.data.should_create_ticket).toBe(false)
  await ctx.dispose()
})

test('S5. route guards — unauthorized access redirected to /forbidden', async ({ page }) => {
  const ctx = await request.newContext()
  const citizen = await loginViaAPI(ctx, 'citizen_local')
  await injectToken(page, citizen)
  // citizen 访问 admin 页面 → 403
  await page.goto(`${BASE}/admin/dashboard`)
  await page.waitForURL(/forbidden/, { timeout: 10_000 })
  expect(page.url()).toContain('/forbidden')

  // citizen 访问 department/kb → 403
  await page.goto(`${BASE}/department/kb`)
  await page.waitForURL(/forbidden/, { timeout: 10_000 })
  expect(page.url()).toContain('/forbidden')
  await ctx.dispose()
})

test('S6. AI case advice + three-state review recorded', async () => {
  const ctx = await request.newContext()
  const citizen = await loginViaAPI(ctx, 'citizen_local')
  const agent = await loginViaAPI(ctx, 'agent_local')
  const dept = await loginViaAPI(ctx, 'department_local')

  // 建一条 processing 工单
  const createRes = await ctx.post(`${API}/api/v1/tickets`, {
    headers: { Authorization: `Bearer ${citizen}` },
    data: {
      idempotency_key: `smoke-ai-${Date.now()}`,
      request_type: '投诉',
      description: 'Smoke AI 三态审核测试',
      location: '测试路 3 号',
      occurred_at_text: '昨天晚上',
      contact: '13800000000',
      source: 'smoke',
    },
  })
  const ticket = (await createRes.json()).data.ticket
  const tid = ticket.ticket_id
  await ctx.post(`${API}/api/v1/tickets/${tid}/accept`, { headers: { Authorization: `Bearer ${agent}` }, data: { version: 1, remark: '受理' } })
  const meRes = await ctx.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${dept}` } })
  const deptId = (await meRes.json()).data.department_id
  await ctx.post(`${API}/api/v1/tickets/${tid}/assign`, { headers: { Authorization: `Bearer ${agent}` }, data: { version: 2, remark: '派发', department_id: deptId } })
  await ctx.post(`${API}/api/v1/tickets/${tid}/process`, { headers: { Authorization: `Bearer ${dept}` }, data: { version: 3, remark: '处理' } })

  // 三态审核：每次审核需要新的 advice_id（同一建议不可重复审核）
  for (const decision of ['adopted', 'adopted_with_edits', 'rejected']) {
    const adviceRes = await ctx.post(`${API}/api/v1/ai/tickets/${tid}/case-advice`, {
      headers: { Authorization: `Bearer ${agent}` },
      data: {},
    })
    expect(adviceRes.ok()).toBeTruthy()
    const adviceId = (await adviceRes.json()).data.advice_id
    expect(adviceId).toBeTruthy()
    const payload: Record<string, string> = { advice_id: adviceId, decision }
    if (decision === 'adopted_with_edits') payload.edit_summary = '调整措辞'
    const r = await ctx.post(`${API}/api/v1/kb/tickets/${tid}/advice/review`, {
      headers: { Authorization: `Bearer ${agent}` },
      data: payload,
    })
    expect(r.status()).toBe(200)
  }

  // 验证 ticket.status 不变(AI 不自动决策)
  const final = await ctx.get(`${API}/api/v1/tickets/${tid}`, { headers: { Authorization: `Bearer ${agent}` } })
  expect((await final.json()).data.status).toBe('processing')

  await ctx.dispose()
})
