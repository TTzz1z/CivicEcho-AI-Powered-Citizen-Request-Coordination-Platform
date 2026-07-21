import { expect, test } from '@playwright/test'

test('退出后切换角色会进入新账号工作台', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname

    if (pathname.endsWith('/auth/login')) {
      const { username } = request.postDataJSON() as { username: string }
      const role = username.startsWith('citizen') ? 'citizen' : 'agent'
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { access_token: `${role}-token`, token_type: 'bearer', expires_in: 900 } }),
      })
      return
    }

    if (pathname.endsWith('/auth/me')) {
      const authorization = request.headers().authorization || ''
      const citizen = authorization.includes('citizen-token')
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            id: citizen ? 2 : 1,
            username: citizen ? 'citizen_second' : 'agent_first',
            display_name: citizen ? '演示市民' : '演示坐席',
            role: citizen ? 'citizen' : 'agent',
            department_id: null,
            is_active: true,
          },
        }),
      })
      return
    }

    if (pathname.endsWith('/categories') || pathname.endsWith('/departments')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [] }),
      })
      return
    }

    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [], page: 1, page_size: 20, total: 0 } }),
    })
  })

  await page.goto('/login')
  await page.getByLabel('用户名').fill('agent_first')
  await page.getByLabel('密码').fill('test-password')
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page).toHaveURL(/\/agent\/tickets$/)

  await page.getByRole('button', { name: /演示坐席/ }).click()
  await page.getByText('退出登录', { exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('用户名').fill('citizen_second')
  await page.getByLabel('密码').fill('test-password')
  await page.getByRole('button', { name: '安全登录' }).click()

  await expect(page).toHaveURL(/\/citizen\/chat$/)
  await expect(page.getByRole('heading', { name: '智能对话' })).toBeVisible()
  await expect(page.getByText('无权访问')).toHaveCount(0)
})
