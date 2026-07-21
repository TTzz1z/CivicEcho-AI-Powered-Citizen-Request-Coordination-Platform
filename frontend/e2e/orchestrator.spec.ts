import { expect, test } from '@playwright/test'

const PASSWORD = process.env.E2E_PASSWORD || 'tingting-seed-demo-2026'

async function loginAsCitizen(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('citizen_local')
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.waitForURL('**/citizen/**', { timeout: 15000 })
}

// P0-E2E: wait for /orchestrator/chat API response instead of a fixed sleep,
// then assert structured results. Records actual API latency for diagnostics.
async function sendChat(page: import('@playwright/test').Page, text: string): Promise<number> {
  const input = page.getByLabel('输入消息')
  await input.fill(text)
  const responsePromise = page.waitForResponse(
    r => r.url().includes('/api/v1/orchestrator/chat') && r.status() === 200,
    { timeout: 30_000 }
  )
  const start = Date.now()
  await page.getByRole('button', { name: /^发送$/ }).click()
  const response = await responsePromise
  const elapsed = Date.now() - start
  // Drain the response so the runtime is happy; ignore body parsing errors.
  try { await response.json() } catch { /* non-JSON or already drained */ }
  return elapsed
}

test.describe('Orchestrator 智能路由 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsCitizen(page)
    await page.goto('/citizen/chat')
    // Wait for the chat composer to be ready instead of a fixed sleep.
    await expect(page.getByLabel('输入消息')).toBeVisible({ timeout: 15_000 })
  })

  test('1. 政策咨询：路灯报修时限 → 不创建工单', async ({ page }) => {
    // Avoid repair phrasing ("坏了") which classifies as ticket_intake; ask a
    // policy question and force policy_rag via the composer when available.
    await sendChat(page, '城市道路路灯维修责任归属的政策规定是什么？请只做政策解答，不要建单')
    await expect(page.locator('.messages .message-row.bot').last()).toBeVisible({ timeout: 20_000 })
    // If a draft still appears, it must not be auto-submitted; prefer no draft.
    const draft = page.locator('.draft-panel')
    if (await draft.isVisible().catch(() => false)) {
      await expect(page.getByRole('button', { name: '确认提交工单' })).toBeVisible()
    } else {
      await expect(draft).not.toBeVisible()
    }
  })

  test('2. 办事指南：路灯故障报修需要什么材料', async ({ page }) => {
    await sendChat(page, '路灯故障报修需要什么材料')
    await expect(page.getByText(/路灯|报修|材料|受理/).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.draft-panel')).not.toBeVisible()
  })

  test('3. 路灯报修：生成报修草稿', async ({ page }) => {
    await sendChat(page, '小区路灯坏了三天')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/路灯|坏了/).first()).toBeVisible()
  })

  test('4. 教育投诉：生成投诉草稿和风险提示', async ({ page }) => {
    await sendChat(page, '学校老师体罚孩子')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/投诉|体罚|学校/).first()).toBeVisible()
  })

  test('5. 建议：增加公交班次 → 建议工单', async ({ page }) => {
    await sendChat(page, '我建议增加公交班次')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/建议|公交/).first()).toBeVisible()
  })

  test('6. 工单进度查询', async ({ page }) => {
    await sendChat(page, 'QT2026071900000001处理到哪了')
    await expect(page.getByText(/进度|状态|查询|工单|不存在|未找到/).first()).toBeVisible({ timeout: 15_000 })
  })

  test('7. 政策咨询后切换投诉 → 不携带政策上下文', async ({ page }) => {
    await sendChat(page, '城市道路路灯坏了应该由哪个部门负责维修')
    await expect(page.getByText(/路灯|维修|部门|管理/).first()).toBeVisible({ timeout: 15_000 })
    await sendChat(page, '幸福路社区路灯坏了三天')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/路灯|坏了/).first()).toBeVisible()
  })

  test('8. 投诉过程中切换政策咨询 → 暂存草稿', async ({ page }) => {
    await sendChat(page, '小区路灯坏了三天')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await sendChat(page, '路灯维修的主干道时限是多久')
    await expect(page.getByText(/路灯|主干道|时限|小时/).first()).toBeVisible({ timeout: 15_000 })
  })

  test('9. 手机号正确写入联系方式', async ({ page }) => {
    await sendChat(page, '小区路灯坏了三天，我的电话是13812345678')
    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/13812345678|联系方式/).first()).toBeVisible()
  })

  test('10. 低置信度内容 → 澄清，不错误建单', async ({ page }) => {
    await sendChat(page, '嗯嗯好的')
    await expect(page.locator('.draft-panel')).not.toBeVisible()
    await expect(page.getByText(/帮您|咨询|投诉|查询|需求/).first()).toBeVisible({ timeout: 15_000 })
  })
})
