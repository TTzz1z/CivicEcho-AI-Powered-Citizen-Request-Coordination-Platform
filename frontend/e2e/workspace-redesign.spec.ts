import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './browser-check'
import { randomUUID } from 'node:crypto'
import type { Dashboard, Ticket, TicketDetail, User } from '../src/types'

import { e2ePassword as password } from './env'
type Account = 'citizen_local' | 'agent_local' | 'department_local' | 'admin_local'

async function apiLogin(request: APIRequestContext, username: Account): Promise<string> {
  const response = await request.post('/api/v1/auth/login', { data: { username, password } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).data.access_token
}

async function api<T>(request: APIRequestContext, token: string, path: string, data?: object): Promise<T> {
  const response = await request.fetch('/api/v1' + path, {
    method: data ? 'POST' : 'GET', headers: { Authorization: `Bearer ${token}` }, data,
  })
  expect(response.ok(), path).toBeTruthy()
  return (await response.json()).data
}

async function open(page: Page, token: string, path: string) {
  await page.addInitScript((value) => sessionStorage.setItem('tingting_access_token', value), token)
  await page.goto(path)
}

async function seedTicket(request: APIRequestContext, citizen: string, description: string) {
  return (await api<{ ticket: Ticket }>(request, citizen, '/tickets', {
    idempotency_key: randomUUID(), request_type: '求助', description, location: '演示社区',
    occurred_at_text: '三天前', source: 'workspace-e2e',
  })).ticket
}

async function checkWidths(page: Page) {
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 980 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  }
}

test('坐席可键盘选单并审核建议，工单仍由人工操作', async ({ page, request }) => {
  const citizen = await apiLogin(request, 'citizen_local')
  const agent = await apiLogin(request, 'agent_local')
  const ticket = await seedTicket(request, citizen, '演示验收：社区路灯已经损坏三天，请核查。')
  await open(page, agent, '/agent/intelligence')
  const search = page.getByLabel('搜索工单编号或关键词')
  await search.fill(ticket.ticket_id)
  await search.press('Enter')
  await page.getByRole('button', { name: new RegExp(ticket.ticket_id) }).press('Enter')
  await expect(page.getByText('市民原始诉求')).toBeVisible()
  await page.getByRole('button', { name: '生成分诊建议' }).click()
  await expect(page.getByRole('heading', { name: '责任部门推荐' })).toBeVisible()
  await page.getByRole('button', { name: '记录为已采纳' }).click()
  await expect(page.getByText('已采纳', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '记录修改后采纳' }).click()
  await page.getByLabel('修订内容').fill('演示验收：现场核对设施编号。')
  await page.getByRole('button', { name: '保存修订记录' }).click()
  await expect(page.getByText('人工修订记录')).toBeVisible()
  await page.getByRole('button', { name: '拒绝建议' }).click()
  await expect(page.getByText('已拒绝', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '有帮助', exact: true }).click()
  await expect(page.getByRole('button', { name: '有帮助', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '加载历史建议' }).click()
  const history = page.getByRole('dialog', { name: '历史分诊建议' })
  await history.getByRole('button', { name: /分诊建议$/ }).click()
  await expect(history).toBeHidden()
  const after = await api<TicketDetail>(request, agent, '/tickets/' + ticket.ticket_id)
  expect(after.status).toBe(ticket.status)
  expect(after.version).toBe(ticket.version)
  await checkWidths(page)
  await page.getByRole('link', { name: '前往工单详情继续办理' }).click()
  await expect(page.getByRole('button', { name: /受理工单$/ })).toBeVisible()
})

test('市民可以在移动端编辑并确认真实草稿，随后查看进度', async ({ page, request }) => {
  const citizen = await apiLogin(request, 'citizen_local')
  await page.setViewportSize({ width: 390, height: 900 })
  await open(page, citizen, '/citizen/chat')
  await page.getByRole('button', { name: '会话与快捷入口' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '新建会话' }).click()
  await page.getByLabel('输入消息').fill('幸福路社区3号楼旁路灯坏了三天')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '核对并确认诉求' })).toBeVisible()
  await page.getByRole('button', { name: '编辑发生地点' }).click()
  const location = page.getByLabel('发生地点', { exact: true })
  await location.fill('幸福路社区3号楼旁')
  await location.press('Tab')
  await page.getByRole('button', { name: /确认提交工单/ }).click()
  const link = page.getByRole('link', { name: '查看工单详情' }).last()
  await expect(link).toBeVisible()
  const detailPath = await link.getAttribute('href')
  expect((await api<TicketDetail>(request, citizen, detailPath!.replace('/citizen', ''))).location).toBe('幸福路社区3号楼旁')
  await checkWidths(page)
  await link.click()
  await expect(page.getByRole('region', { name: '诉求办理进度' })).toBeVisible()
  await checkWidths(page)
})

test('部门提交实际处置，坐席复核后市民确认结果', async ({ page, request, context }) => {
  const citizen = await apiLogin(request, 'citizen_local')
  const agent = await apiLogin(request, 'agent_local')
  const department = await apiLogin(request, 'department_local')
  const user = await api<User>(request, department, '/auth/me')
  const ticket = await seedTicket(request, citizen, '演示验收：人行道旁设施需要核查。')
  const path = '/tickets/' + ticket.ticket_id
  const accepted = await api<Ticket>(request, agent, path + '/accept', { version: ticket.version, remark: '演示受理' })
  await api(request, agent, path + '/assign', { version: accepted.version, remark: '演示派发', department_id: user.department_id })
  await open(page, department, '/department/tickets')
  await page.getByRole('tab', { name: '待办理', exact: true }).click()
  await expect(page).toHaveURL(/status=assigned/)
  await checkWidths(page)
  await page.getByRole('link', { name: ticket.ticket_id }).click()
  await page.getByRole('link', { name: '查看协同任务' }).click()
  await page.getByRole('button', { name: '开始办理', exact: true }).click()
  await page.getByLabel('操作说明').fill('演示：开始核查')
  await page.getByRole('button', { name: '确认提交' }).click()
  await expect(page.getByText('办理中', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '提交结果', exact: true }).click()
  await page.getByLabel('结果摘要').fill('演示：已核查设施')
  await page.getByLabel('处理措施').fill('演示：已完成现场核查')
  await page.getByLabel('本部门公开答复').fill('演示：已处理诉求')
  await page.getByLabel('操作说明').fill('演示：提交实际办理结果')
  await page.getByRole('button', { name: '确认提交' }).click()
  await page.getByRole('button', { name: /汇总最终答复/ }).click()
  await page.getByLabel('最终结果摘要').fill('演示：核查完成')
  await page.getByLabel('综合处理措施').fill('演示：已安排现场检查')
  await page.getByLabel('对市民最终答复').fill('演示：设施已核实')
  await page.getByLabel('操作说明').fill('演示：提交坐席复核')
  await page.getByRole('button', { name: '确认提交' }).click()
  await expect(page.getByText('主办部门已提交答复，等待坐席审核办结')).toBeVisible()
  const after = await api<TicketDetail>(request, department, path)
  expect(after.status).toBe('processing')
  expect(after.collaboration_status).toBe('awaiting_review')
  await api(request, agent, path + '/review-resolve', {
    version: after.version, remark: '演示：完成坐席复核', resolution_summary: '设施已核实',
    resolution_measures: '完成检查', resolution_outcome: 'resolved', public_reply: '设施已核实',
  })
  const citizenPage = await context.newPage()
  try {
    await open(citizenPage, citizen, '/citizen' + path)
    await citizenPage.getByRole('button', { name: /确认结果并评价/ }).click()
    await citizenPage.getByRole('dialog').getByRole('button', { name: '确认提交' }).click()
    await expect(citizenPage.getByText('确认办结', { exact: false }).first()).toBeVisible()
    expect((await api<TicketDetail>(request, citizen, path)).status).toBe('closed')
  } finally {
    await citizenPage.close()
  }
})

test('管理员趋势读取真实数据，风险和审计可下钻，账号可切换', async ({ page, request }) => {
  const admin = await apiLogin(request, 'admin_local')
  const citizen = await apiLogin(request, 'citizen_local')
  const before = await api<Dashboard>(request, admin, '/admin/dashboard')
  await seedTicket(request, citizen, '演示验收：建议核查公共设施。')
  const after = await api<Dashboard>(request, admin, '/admin/dashboard')
  expect(after.intake_trend).toHaveLength(14)
  expect(after.trend_timezone).toBe('Asia/Shanghai')
  const last = after.intake_trend!.at(-1)!
  expect(last.count).toBe((before.intake_trend?.find((point) => point.day === last.day)?.count ?? 0) + 1)
  await open(page, admin, '/admin/dashboard')
  await expect(page.getByRole('img', { name: '近 14 天每日新增工单折线图' }).locator('canvas')).toBeVisible()
  await checkWidths(page)
  await page.getByRole('button', { name: '查看每日数据' }).click()
  await expect(page.getByRole('region', { name: '每日新增工单' }).getByRole('row')).toHaveCount(15)
  await page.getByRole('link', { name: '查看已超时工单' }).click()
  await expect(page).toHaveURL(/sla_state=overdue/)
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.goto('/admin/audit')
  await page.getByRole('button', { name: /查看记录/ }).first().press('Enter')
  const drawer = page.getByRole('dialog', { name: '审计记录详情' })
  await expect(drawer.getByText('请求编号')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await page.getByRole('button', { name: /账号菜单/ }).click()
  const logout = page.waitForResponse('**/api/v1/auth/logout')
  await page.getByRole('menuitem', { name: /切换账号/ }).click()
  const loggedOut = await logout
  expect(loggedOut.status()).toBe(200)
  expect((await loggedOut.json()).data.revoked).toBe(true)
  await page.getByLabel('用户名').fill('citizen_local')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '智能对话' })).toBeVisible()
})
