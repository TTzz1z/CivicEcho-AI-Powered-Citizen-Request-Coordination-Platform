import { expect, test } from './browser-check'

import { e2ePassword as PASSWORD } from './env'

async function loginAsCitizen(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill('citizen_local')
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.waitForURL('**/citizen/**', { timeout: 15000 })
}

// Wait for the current chat stream before checking the draft panel.
async function sendChatAndWait(page: import('@playwright/test').Page, text: string) {
  const input = page.getByLabel('输入消息')
  await input.fill(text)
  const responsePromise = page.waitForResponse(
    r => r.url().endsWith('/api/v1/orchestrator/chat/stream') && r.status() === 200,
    { timeout: 30_000 }
  )
  await page.getByRole('button', { name: /^发送$/ }).click()
  const response = await responsePromise
  expect(await response.text()).toContain('event: done')
}

test.describe('智能对话建单 - 草稿模式', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsCitizen(page)
    await page.goto('/citizen/chat')
    await expect(page.getByLabel('输入消息')).toBeVisible({ timeout: 15_000 })
  })

  test('教育投诉：识别类型并补全后提交', async ({ page }) => {
    // r2-9: longer timeout for LLM latency; assert draft panel presence rather
    // than specific request_type wording (LLM may classify as 投诉/求助/etc).
    test.setTimeout(90_000)
    await sendChatAndWait(page, '和平路小学门口有违规培训班扰民')

    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 30_000 })

    const submitBtn = page.getByRole('button', { name: '确认提交工单' })
    if (!(await submitBtn.isEnabled())) {
      // Edit the first missing required field via its descriptions-item row.
      const pendingRow = page.locator('.draft-panel .ant-descriptions-item').filter({ hasText: '待补充' }).first()
      await pendingRow.getByRole('button').first().click()
      const fieldInput = page.locator('.draft-panel input, .draft-panel textarea').first()
      await fieldInput.fill('和平路小学门口')
      await fieldInput.blur()
      await expect(submitBtn).toBeEnabled({ timeout: 5_000 })
    }

    await submitBtn.click()
    await expect(page.getByText(/QT\d{16}/).first()).toBeVisible({ timeout: 15_000 })
  })

  test('路灯故障：地点已识别，补全后提交', async ({ page }) => {
    await sendChatAndWait(page, '幸福路社区3号楼旁路灯坏了三天')

    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText(/幸福路/).first()).toBeVisible()

    const submitBtn = page.getByRole('button', { name: '确认提交工单' })
    if (!(await submitBtn.isEnabled())) {
      const pendingRow = page.locator('.draft-panel .ant-descriptions-item').filter({ hasText: '待补充' }).first()
      await pendingRow.getByRole('button').first().click()
      const fieldInput = page.locator('.draft-panel input, .draft-panel textarea').first()
      await fieldInput.fill('幸福路社区3号楼旁')
      await fieldInput.blur()
      await expect(submitBtn).toBeEnabled({ timeout: 5_000 })
    }
    await submitBtn.click()

    await expect(page.getByText(/QT\d{16}/).first()).toBeVisible({ timeout: 10_000 })
  })

  test('政策咨询：识别为咨询，地点填不适用后提交', async ({ page }) => {
    // Explicit confirmation phrase must match CREATE_CONSULTATION_TICKET_WORDS.
    await page.getByRole('button', { name: '新建会话' }).click()
    await sendChatAndWait(page, '我要咨询路灯报修的具体流程，请帮我创建咨询工单')

    await expect(page.locator('.draft-panel')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('咨询').first()).toBeVisible()

    const submitBtn = page.getByRole('button', { name: '确认提交工单' })
    if (!(await submitBtn.isEnabled())) {
      await page.getByRole('button', { name: '编辑发生地点' }).click()
      const locInput = page.getByLabel('发生地点', { exact: true })
      await locInput.fill('不适用')
      await locInput.blur()
      await expect(submitBtn).toBeEnabled({ timeout: 5_000 })
    }

    await submitBtn.click()
    await expect(page.getByText(/QT\d{16}/).first()).toBeVisible({ timeout: 15_000 })
  })
})
