import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './browser-check'

import { e2ePassword as password } from './env'
const productionUrl = process.env.E2E_PRODUCTION_URL
const longTitle = '超长政策标题' + 'A'.repeat(128)
const longNumber = '〔2026〕' + 'B'.repeat(128) + '号'
const longFilename = '申请证明' + 'C'.repeat(180) + '.pdf'

function authorization(token: string) {
  return { Authorization: `Bearer ${token}` }
}

async function api<T>(request: APIRequestContext, path: string, token?: string, data?: object): Promise<T> {
  const response = await request.fetch('/api/v1' + path, {
    method: data ? 'POST' : 'GET', headers: token ? authorization(token) : undefined, data,
  })
  expect(response.ok(), `${path}: HTTP ${response.status()}`).toBeTruthy()
  return (await response.json()).data
}

async function apiLogin(request: APIRequestContext, username: string, secret = password) {
  return (await api<{ access_token: string }>(request, '/auth/login', undefined, { username, password: secret })).access_token
}

async function useToken(page: Page, token: string) {
  await page.addInitScript(value => sessionStorage.setItem('tingting_access_token', value), token)
}

async function newTicket(request: APIRequestContext, token: string, description: string) {
  return (await api<{ ticket: { ticket_id: string; version: number } }>(request, '/tickets', token, {
    idempotency_key: randomUUID(), request_type: '咨询', description, location: '幸福路社区', source: 'web',
  })).ticket
}

async function acceptTicket(request: APIRequestContext, token: string, ticket: { ticket_id: string; version: number }) {
  await api(request, `/tickets/${ticket.ticket_id}/accept`, token, { version: ticket.version, remark: '浏览器验收受理' })
}

async function downloadCsv(page: Page) {
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 CSV' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/\.csv$/)
  const bytes = await readFile((await file.path())!)
  expect([...bytes.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
  return bytes.toString('utf8')
}

test('市民自助注册及修改密码更新会话并撤销旧令牌', async ({ page, request }) => {
  const username = `e2e_${randomUUID().replaceAll('-', '').slice(0, 16)}`
  const originalPassword = 'BrowserTest2026Initial'
  const newPassword = 'BrowserTest2026Changed'

  await page.goto('/login')
  await page.getByRole('tab', { name: '市民注册', exact: true }).click()
  await page.getByLabel('用户名', { exact: true }).fill(username)
  await page.getByLabel('姓名/昵称（可选）', { exact: true }).fill('浏览器验收市民')
  await page.getByLabel('密码', { exact: true }).fill(originalPassword)
  await page.getByLabel('确认密码', { exact: true }).fill(originalPassword)
  await page.getByRole('button', { name: '注册并登录' }).click()
  await expect(page).toHaveURL(/\/citizen\/chat$/)
  const oldToken = await page.evaluate(() => sessionStorage.getItem('tingting_access_token'))
  expect(oldToken).toBeTruthy()

  await page.getByRole('button', { name: /账号菜单/ }).click()
  await page.getByRole('menuitem', { name: '修改密码' }).click()
  const dialog = page.getByRole('dialog', { name: '修改密码' })
  await dialog.getByLabel('当前密码', { exact: true }).fill(originalPassword)
  await dialog.getByLabel('新密码', { exact: true }).fill(newPassword)
  await dialog.getByLabel('确认新密码', { exact: true }).fill(newPassword)
  await dialog.getByRole('button', { name: '确认修改' }).click()
  await expect(dialog).toBeHidden()
  const newToken = await page.evaluate(() => sessionStorage.getItem('tingting_access_token'))
  expect(newToken).toBeTruthy()
  expect(newToken).not.toBe(oldToken)
  const who = await api<{ username: string; role: string }>(request, '/auth/me', newToken!)
  expect(who).toMatchObject({ username, role: 'citizen' })
  expect((await request.get('/api/v1/auth/me', { headers: authorization(oldToken!) })).status()).toBe(401)
  expect((await request.post('/api/v1/auth/login', { data: { username, password: originalPassword } })).status()).toBe(401)
  expect(await apiLogin(request, username, newPassword)).toBeTruthy()
  await page.reload()
  await expect(page.getByRole('heading', { name: '智能对话' })).toBeVisible()
})

test('坐席批量派发返回逐条结果并下载筛选后的工单 CSV', async ({ page, request }) => {
  const citizen = await apiLogin(request, 'citizen_local')
  const agent = await apiLogin(request, 'agent_local')
  const department = await apiLogin(request, 'department_local')
  const { department_id: departmentId } = await api<{ department_id: number }>(request, '/auth/me', department)
  const departments = await api<{ id: number; name: string }[]>(request, '/departments', agent)
  const departmentName = departments.find(item => item.id === departmentId)!.name
  const keyword = `batch-${randomUUID().slice(0, 8)}`
  const first = await newTicket(request, citizen, `=${keyword} first`)
  const second = await newTicket(request, citizen, `${keyword} second`)
  const pending = await newTicket(request, citizen, `${keyword} pending`)
  await acceptTicket(request, agent, first)
  await acceptTicket(request, agent, second)

  await useToken(page, agent)
  await page.goto(`/agent/tickets?keyword=${keyword}`)
  for (const ticket of [first, second, pending]) {
    await page.getByRole('row').filter({ hasText: ticket.ticket_id }).getByRole('checkbox').check()
  }
  const toolbar = page.getByRole('region', { name: '批量派发操作栏' })
  await expect(toolbar).toContainText('已选 3 条')
  await toolbar.getByRole('button', { name: '批量派发' }).click()
  const dialog = page.getByRole('dialog', { name: /批量派发（/ })
  await dialog.getByRole('combobox', { name: '责任部门' }).click()
  await page.locator('.ant-select-dropdown').getByText(departmentName, { exact: true }).click()
  await dialog.getByRole('button', { name: '确认派发' }).click()
  const result = page.getByRole('dialog', { name: '批量派发结果' })
  await expect(result).toContainText('成功 2 条，失败 1 条')
  for (const ticket of [first, second, pending]) await expect(result).toContainText(ticket.ticket_id)
  await result.getByRole('button', { name: '知道了' }).click()
  const csv = await downloadCsv(page)
  for (const ticket of [first, second, pending]) expect(csv).toContain(ticket.ticket_id)
  expect(csv).toContain(`'=${keyword} first`)
  expect(csv.trim().split(/\r?\n/)).toHaveLength(4)
})

test('管理员下载筛选后的审计 CSV，并可打印工单归档单', async ({ page, request }) => {
  const admin = await apiLogin(request, 'admin_local')
  const citizen = await apiLogin(request, 'citizen_local')
  const description = '打印验收：核查社区便民服务设施'
  const ticket = await newTicket(request, citizen, description)
  await page.addInitScript(() => {
    window.print = () => document.documentElement.setAttribute('data-print-called', 'true')
  })
  await useToken(page, admin)
  await page.goto('/admin/audit')
  const search = page.getByLabel('按动作精确查询')
  await search.fill('login')
  await search.press('Enter')
  const exportRequest = page.waitForRequest(url => new URL(url.url()).pathname === '/api/v1/admin/audit-logs/export')
  const csv = await downloadCsv(page)
  expect(new URL((await exportRequest).url()).searchParams.get('action')).toBe('login')
  expect(csv).toContain('操作类型')
  expect(csv).toContain(',login,')

  await page.goto(`/admin/tickets/${ticket.ticket_id}`)
  const printButton = page.getByRole('button', { name: '打印工单' })
  await expect(page.locator('.ticket-print-header')).toBeHidden()
  await printButton.click()
  await expect(page.locator('html')).toHaveAttribute('data-print-called', 'true')
  await page.emulateMedia({ media: 'print' })
  await expect(page.locator('.ticket-print-header')).toBeVisible()
  await expect(page.locator('.ticket-print-header')).toContainText(ticket.ticket_id)
  await expect(page.getByText(description, { exact: true })).toBeVisible()
  await expect(page.getByText('办理时间线', { exact: true })).toBeVisible()
  await expect(printButton).toBeHidden()
  await expect(page.getByRole('button', { name: /账号菜单/ })).toBeHidden()
})

test('站内通知由真实 SSE 更新角标并展示最新受理记录', async ({ page, request }) => {
  const username = `e2e_notify_${randomUUID().slice(0, 8)}`
  const citizen = (await api<{ access_token: string }>(request, '/auth/register', undefined, { username, password })).access_token
  const agent = await apiLogin(request, 'agent_local')
  const ticket = await newTicket(request, citizen, '站内消息验收：核实市民健身设施')
  await api(request, '/notifications/read-all', citizen, {})
  await useToken(page, citizen)
  const stream = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/notifications/stream')
  await page.goto('/citizen/chat')
  const response = await stream
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  await expect(page.getByRole('button', { name: '打开通知' })).toBeVisible()
  await acceptTicket(request, agent, ticket)
  await page.getByRole('button', { name: '通知，1 条未读' }).click({ timeout: 12_000 })
  const drawer = page.getByRole('dialog', { name: '最近通知' })
  const notification = drawer.getByRole('listitem').filter({ has: page.getByRole('heading', { name: '工单已受理 未读' }) })
  await expect(notification).toBeVisible()
  await expect(notification).toContainText(`工单 ${ticket.ticket_id} 已受理，正在安排承办。`)
  const description = notification.locator('.ant-list-item-meta-description')
  await expect.poll(async () => (await description.boundingBox())?.width ?? 0).toBeGreaterThan(120)
  await expect(notification.getByRole('link', { name: '查看工单' })).toHaveAttribute('href', `/citizen/tickets/${ticket.ticket_id}`)
  await notification.getByRole('button', { name: '标为已读' }).click()
  await expect(page.getByRole('button', { name: '打开通知' })).toBeVisible()
})

test('市民聊天和政策问答使用实际流式接口完成回答', async ({ page, request }) => {
  await useToken(page, await apiLogin(request, 'citizen_local'))
  await page.goto('/citizen/chat')
  await page.getByRole('textbox', { name: '输入消息' }).fill('你好')
  const chatStream = page.waitForResponse('**/api/v1/orchestrator/chat/stream')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const chat = await chatStream
  expect(chat.headers()['content-type']).toContain('text/event-stream')
  expect(await chat.text()).toMatch(/event: meta[\s\S]+event: delta[\s\S]+event: done/)
  await expect(page.getByRole('log').getByText(/我是倾听助手/)).toBeVisible()

  await page.goto('/citizen/policy')
  await page.getByRole('textbox', { name: '政策咨询问题' }).fill('路灯故障报修需要什么材料？')
  const policyStream = page.waitForResponse('**/api/v1/kb/query/stream')
  await page.getByRole('button', { name: '查询政策' }).click()
  const policy = await policyStream
  expect(policy.headers()['content-type']).toContain('text/event-stream')
  expect(await policy.text()).toMatch(/event: meta[\s\S]+event: delta[\s\S]+event: done/)
  await expect(page.getByTestId('policy-citations')).toBeVisible()
})

test('增量文本在结束前可见，停止生成后保留已显示内容', async ({ page }) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = (input, init) => {
      if (input !== '/api/v1/orchestrator/chat/stream') return originalFetch(input, init)
      const encoder = new TextEncoder()
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          const frame = (event: string, data: object) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
          frame('meta', { route: 'general_chat', payload: {}, advisory_only: true })
          frame('delta', { text: '第一段增量。' })
          document.addEventListener('e2e:continue', () => frame('delta', { text: '第二段增量。' }), { once: true })
          init?.signal?.addEventListener('abort', () => {
            document.documentElement.setAttribute('data-stream-aborted', 'true')
            controller.error(new DOMException('Aborted', 'AbortError'))
          }, { once: true })
        },
      })
      return Promise.resolve(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }))
    }
  })
  await page.goto('/chat')
  await page.getByRole('textbox', { name: '输入消息' }).fill('社区办理时间')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const chat = page.getByRole('log', { name: '对话记录' })
  await expect(chat.getByText('第一段增量。', { exact: true })).toBeVisible()
  await expect(chat.getByText(/第二段增量/)).toHaveCount(0)
  await page.evaluate(() => document.dispatchEvent(new Event('e2e:continue')))
  await expect(chat.getByText('第一段增量。第二段增量。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '停止生成' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-stream-aborted', 'true')
  await expect(chat.getByText('第一段增量。第二段增量。', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
})

test('320px 和 390px 可展示极长标题、文号及文件名且无横向溢出', async ({ page, request }) => {
  const agent = await apiLogin(request, 'agent_local')
  const citizen = await apiLogin(request, 'citizen_local')
  const ticket = await newTicket(request, citizen, '长文本移动端验收工单')
  const citation = {
    index: 1, doc_id: 0, title: longTitle, doc_number: longNumber, status: 'PUBLISHED',
    issuing_authority: '区政务服务中心', excerpt: '公开政策原文摘录',
  }
  const answer = {
    query: '请查询办事指南', answer: '可在线查询办理进度。', citations: [citation], no_evidence: false,
    degraded: false, advisory_only: true, latency_ms: 1,
  }
  await useToken(page, agent)
  await page.route('**/api/v1/kb/query/stream', route => route.fulfill({
    contentType: 'text/event-stream',
    body: `event: meta\ndata: ${JSON.stringify(answer)}\n\nevent: done\ndata: ${JSON.stringify(answer)}\n\n`,
  }))
  await page.route(`**/api/v1/tickets/${ticket.ticket_id}/attachments`, route => route.fulfill({
    json: { success: true, data: { items: [{
      id: randomUUID(), ticket_id: ticket.ticket_id, original_filename: longFilename, content_type: 'application/pdf',
      size_bytes: 2096, visibility: 'public', attachment_type: 'processing_proof', scan_status: 'clean',
      created_at: '2026-11-25T01:00:00Z', sha256: 'a'.repeat(64),
    }], total: 1 } },
  }))
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/agent/policy')
    await page.getByRole('textbox', { name: '政策咨询问题' }).fill(answer.query)
    await page.getByRole('button', { name: '查询政策' }).click()
    await expect(page.getByText(longTitle, { exact: true })).toBeVisible()
    await expect(page.getByText(longNumber, { exact: true })).toBeVisible()
    await expectNoHorizontalOverflow(page, width)
    await page.getByText(longTitle, { exact: true }).click()
    await page.getByRole('button', { name: `查看详情：${longTitle}` }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expectNoHorizontalOverflow(page, width)

    await page.goto(`/agent/tickets/${ticket.ticket_id}`)
    await page.getByText('附件材料', { exact: true }).click()
    await expect(page.getByText(longFilename, { exact: true })).toBeVisible()
    await expectNoHorizontalOverflow(page, width)
  }
})

async function expectNoHorizontalOverflow(page: Page, width: number) {
  await expect.poll(() => page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth))).toBe(width)
}

test('生产构建首页、登录与访客入口无演示文案，保留市民注册', async ({ page }) => {
  test.skip(!productionUrl, '配置 E2E_PRODUCTION_URL 指向 VITE_DEMO_MODE=false 构建')
  for (const [path, heading] of [['/welcome', /让每一件诉求都有回应/], ['/login', '登录倾听助手'], ['/chat', '智能对话']] as const) {
    await page.goto(new URL(path, productionUrl).toString())
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
    await expect(page.locator('body')).not.toContainText(/演示|admin_local|agent_local|department_local|citizen_local/)
  }
  await page.goto(new URL('/login', productionUrl).toString())
  await page.getByRole('tab', { name: '市民注册', exact: true }).click()
  await expect(page.getByRole('heading', { name: '注册市民账号' })).toBeVisible()
  await expect(page.getByRole('button', { name: '注册并登录' })).toBeEnabled()
})
