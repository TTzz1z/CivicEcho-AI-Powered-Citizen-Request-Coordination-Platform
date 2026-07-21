import { expect, test } from '@playwright/test'

test('长对话只滚动消息区并固定左侧建议栏', async ({ page }) => {
  await page.addInitScript(() => {
    const sender = 'web-anon-layout-regression'
    const messages = Array.from({ length: 36 }, (_, index) => ({
      id: `layout-message-${index}`,
      side: index % 2 === 0 ? 'user' : 'bot',
      text: `用于验证长对话布局的第 ${index + 1} 条消息。`,
    }))

    localStorage.setItem('tingting_sender_id', sender)
    // chatStorage requires v1 TTL envelope; bare arrays are purged as legacy.
    localStorage.setItem(
      `tingting_chat_${sender}`,
      JSON.stringify({ v: 1, savedAt: Date.now(), data: messages }),
    )
  })

  await page.goto('/chat')

  const aside = page.locator('.chat-aside')
  await expect(aside.getByText(/快捷入口|建议问题/)).toBeVisible()
  await expect(aside.getByRole('button', { name: '新建会话' })).toBeVisible()

  await page.waitForFunction(() => {
    const messages = document.querySelector<HTMLElement>('.messages')
    if (!messages || messages.scrollHeight <= messages.clientHeight) return false
    return messages.scrollHeight - messages.clientHeight - messages.scrollTop < 8
  })

  const layout = await page.evaluate(() => {
    const asideElement = document.querySelector<HTMLElement>('.chat-aside')!
    const messagesElement = document.querySelector<HTMLElement>('.messages')!
    const asideRect = asideElement.getBoundingClientRect()

    return {
      pageScrollY: window.scrollY,
      asideTop: asideRect.top,
      asideBottom: asideRect.bottom,
      viewportHeight: window.innerHeight,
      messageScrollTop: messagesElement.scrollTop,
      messageScrollable: messagesElement.scrollHeight > messagesElement.clientHeight,
    }
  })

  expect(layout.pageScrollY).toBe(0)
  expect(layout.messageScrollable).toBe(true)
  expect(layout.messageScrollTop).toBeGreaterThan(0)
  expect(layout.asideTop).toBeGreaterThanOrEqual(0)
  expect(layout.asideBottom).toBeLessThanOrEqual(layout.viewportHeight)
})

test('公开会话说明访客工单归属并可返回首页', async ({ page }) => {
  await page.goto('/chat')

  await expect(page.getByText(/访客模式|访客会话/)).toBeVisible()
  await expect(page.getByRole('link', { name: /账号登录/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /账号登录/ })).toHaveAttribute('href', '/login')

  await page.getByRole('link', { name: /返回服务首页/ }).click()
  await expect(page).toHaveURL(/\/welcome$/)
  await expect(page.getByRole('button', { name: /访客智能对话/ })).toBeVisible()
})
