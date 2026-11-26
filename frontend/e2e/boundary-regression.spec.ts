import { expect, test } from './browser-check'
import { randomUUID } from 'node:crypto'

import { e2ePassword as password } from './env'

test('清空会话会丢弃迟到的回复，并允许发送下一条消息', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  const late = '这条答复只属于上一会话'
  const fresh = '这条答复属于当前会话'
  let count = 0
  await page.route('**/api/v1/orchestrator/chat/stream', async route => {
    const first = ++count === 1
    if (first) await held
    await route.fulfill({
      contentType: 'text/event-stream',
      body: `event: done\ndata: ${JSON.stringify({ route: 'general_chat', message: first ? late : fresh, payload: {} })}\n\n`,
    }).catch(error => {
      // The app is allowed to cancel the first request before the fixture replies.
      if (!first) throw error
    })
  })
  await page.goto('/chat')
  const input = page.getByRole('textbox', { name: '输入消息' })
  await input.fill('请问社区服务时间')
  const sent = page.waitForRequest('**/api/v1/orchestrator/chat/stream')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await sent
  await page.getByRole('button', { name: '清空', exact: true }).click()
  release()
  await input.fill('请问社区服务地点')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const chat = page.getByRole('log', { name: '对话记录' })
  await expect(chat.getByText(fresh)).toBeVisible()
  await expect(page.getByText(late)).toHaveCount(0)
})

test('坐席可以用方向键选择快捷页，Escape 后焦点返回', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('agent_local')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page).toHaveURL(/\/agent\/tickets$/)
  const trigger = page.getByRole('button', { name: '打开快捷导航命令面板' })
  await trigger.focus()
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog', { name: '快捷跳转' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('/admin/dashboard')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  await trigger.click()
  const search = dialog.getByRole('combobox')
  await search.press('ArrowDown')
  await search.press('ArrowDown')
  await search.press('Enter')
  await expect(page).toHaveURL(/\/agent\/policy$/)
})

function previewPdf() {
  const stream = '0 0 1 rg 16 16 80 60 re f'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 120 100] /Contents 4 0 R >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(pdf)
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return offset
  })
  const xref = Buffer.byteLength(pdf)
  pdf += `xref\n0 5\n0000000000 65535 f \n${offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}`
  return Buffer.from(pdf + `trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
}

test('390px 工单详情能预览已扫描 PDF，未扫描附件只可下载', async ({ page, request }) => {
  const login = await request.post('/api/v1/auth/login', {
    data: { username: 'admin_local', password },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).data.access_token as string
  const citizenLogin = await request.post('/api/v1/auth/login', { data: { username: 'citizen_local', password } })
  expect(citizenLogin.ok()).toBeTruthy()
  const citizenToken = (await citizenLogin.json()).data.access_token as string
  const created = await request.post('/api/v1/tickets', {
    headers: { Authorization: `Bearer ${citizenToken}` },
    data: { idempotency_key: randomUUID(), request_type: '咨询', description: '浏览器 PDF 预览验收', location: '幸福路社区', source: 'web' },
  })
  expect(created.ok()).toBeTruthy()
  const ticket = (await created.json()).data.ticket.ticket_id as string
  const pdf = previewPdf()
  const document = {
    id: 'fixture-pdf', ticket_id: ticket, content_type: 'application/pdf', original_filename: '办理证明.pdf',
    attachment_type: 'processing_proof', visibility: 'public', size_bytes: pdf.length,
    scan_status: 'clean', sha256: '0123456789abcde', created_at: '2026-11-25T01:00:00Z',
  }
  await page.addInitScript(value => sessionStorage.setItem('tingting_access_token', value), token)
  await page.route(`**/api/v1/tickets/${ticket}/attachments`, route => route.fulfill({
    json: { success: true, data: { items: [document, { ...document, id: 'fixture-skipped', original_filename: '待核验.pdf', scan_status: 'skipped' }], total: 2 } },
  }))
  await page.route('**/api/v1/attachments/fixture-pdf/download', route =>
    route.fulfill({ status: 200, contentType: 'application/pdf', body: pdf }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/admin/tickets/${ticket}`)
  await expect(page.getByText('办理时间线', { exact: true })).toBeVisible()
  await page.getByText('附件材料', { exact: true }).click()
  await expect(page.getByRole('button', { name: '预览 待核验.pdf' })).toHaveCount(0)
  await page.getByRole('button', { name: '预览 办理证明.pdf' }).click()
  const drawer = page.getByRole('dialog', { name: '附件预览' })
  await expect(drawer.getByRole('img', { name: '办理证明.pdf，第 1 页' })).toBeVisible()
  const hasBlue = await drawer.locator('canvas').evaluate((canvas: HTMLCanvasElement) => {
    const pixel = canvas.getContext('2d')?.getImageData(40, 95, 1, 1).data
    return Boolean(pixel && pixel[2] > pixel[0])
  })
  expect(hasBlue).toBe(true)
})

test('快捷视图更新 URL，通知抽屉在确认成功后刷新未读数', async ({ page }) => {
  let unread = true
  const recent = {
    id: 'fixture-notification', event_type: 'ticket_assigned', title: '部门工单更新',
    content: '这是一条隔离通知。', created_at: '2026-11-25T01:00:00Z',
  }
  await page.route('**/api/v1/notifications?**', route => route.fulfill({
    json: { success: true, data: {
      items: [{ ...recent, status: unread ? 'unread' : 'read' }],
      page: 1, page_size: 6, total: 1, unread_count: unread ? 1 : 0,
    } },
  }))
  await page.route('**/api/v1/notifications/stream', route => route.fulfill({
    contentType: 'text/event-stream', body: 'event: ping\ndata: {}\n\n',
  }))
  await page.route('**/api/v1/notifications/fixture-notification/read', route => {
    unread = false
    return route.fulfill({ json: { success: true, data: { ...recent, status: 'read' } } })
  })

  await page.goto('/login')
  await page.getByLabel('用户名').fill('agent_local')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '待复核', exact: true }).click()
  await expect(page).toHaveURL(/work_queue=awaiting_review/)
  await page.getByRole('button', { name: '通知，1 条未读' }).click()
  const drawer = page.getByRole('dialog', { name: '最近通知' })
  await expect(drawer.getByText(recent.title)).toBeVisible()
  await drawer.getByRole('button', { name: '标为已读' }).click()
  await expect(drawer.getByRole('button', { name: '标为已读' })).toHaveCount(0)
  await drawer.getByRole('link', { name: '查看全部通知' }).click()
  await expect(page).toHaveURL(/\/agent\/notifications$/)
  await expect(page.getByRole('button', { name: '打开通知' })).toBeVisible()
})
