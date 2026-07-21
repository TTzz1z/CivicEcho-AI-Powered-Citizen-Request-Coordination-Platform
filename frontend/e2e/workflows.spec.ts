import { expect, test } from '@playwright/test'
const password=process.env.E2E_PASSWORD||'tingting-seed-demo-2026'
async function login(page:import('@playwright/test').Page,username:string){await page.goto('/login');await page.getByLabel('用户名').fill(username);await page.getByLabel('密码').fill(password||'');await page.getByRole('button',{name:'安全登录'}).click()}
async function apiLogin(request:import('@playwright/test').APIRequestContext,username:string){const response=await request.post('/api/v1/auth/login',{data:{username,password}});expect(response.ok()).toBeTruthy();return (await response.json()).data.access_token as string}

test.describe('真实服务工作流',()=>{
  test('市民通过 Orchestrator 对话创建诉求',async({page})=>{
    test.setTimeout(120_000)
    await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/)
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel('输入消息').fill('幸福路社区3号楼旁路灯坏了三天')
    const sendStart=Date.now()
    await Promise.all([
      page.waitForResponse(r=>r.url().includes('/api/v1/orchestrator/chat')&&r.status()===200,{timeout:60_000}),
      page.getByRole('button',{name:/^发送$/}).click(),
    ])
    console.log(`[orchestrator] send latency=${Date.now()-sendStart}ms`)
    await expect(page.locator('.draft-panel')).toBeVisible({timeout:30_000})
    const submitBtn=page.getByRole('button',{name:'确认提交工单'})
    if(!(await submitBtn.isEnabled())){
      const pendingRow=page.locator('.draft-panel .ant-descriptions-item').filter({hasText:'待补充'}).first()
      await pendingRow.getByRole('button').first().click()
      const fieldInput=page.locator('.draft-panel input, .draft-panel textarea').first()
      await fieldInput.fill('幸福路社区3号楼旁')
      await fieldInput.blur()
      await expect(submitBtn).toBeEnabled({timeout:5_000})
    }
    await submitBtn.click()
    await expect(page.getByText(/QT\d{16}/).first()).toBeVisible({timeout:20_000})
    await expect(page.getByText(/查看工单详情|查看办理进度/).first()).toBeVisible()
  })
  test('坐席可以打开工单工作台',async({page})=>{await login(page,'agent_local');await expect(page).toHaveURL(/agent\/tickets/);await expect(page.getByRole('heading',{name:'坐席工单台'})).toBeVisible()})
  test('部门人员可以打开本部门工单',async({page})=>{await login(page,'department_local');await expect(page).toHaveURL(/department\/tickets/);await expect(page.getByRole('heading',{name:'部门工单'})).toBeVisible()})
  test('管理员可以访问看板和管理页面',async({page})=>{await login(page,'admin_local');await expect(page).toHaveURL(/admin\/dashboard/);await expect(page.getByRole('heading',{name:'运营总览'})).toBeVisible();await page.getByRole('menuitem',{name:'用户管理'}).click();await expect(page.getByRole('heading',{name:'用户管理'})).toBeVisible()})
  test('普通用户访问管理员页面被阻止',async({page})=>{await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/);await page.goto('/admin/dashboard');await expect(page.getByText('无权访问').first()).toBeVisible()})
})

test('四角色均可进入对应的 AI 辅助页面，且行政决定边界清晰',async({page})=>{
  test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流')
  for(const [username,path,menu,boundary] of [
    ['citizen_local','/citizen/intelligence','智能诉求检查','提交前智能预审'],
    ['agent_local','/agent/intelligence','智能分派','人机协同边界'],
    ['department_local','/department/intelligence','文书辅助','人机协同边界'],
    ['admin_local','/admin/intelligence','智能与平台接入','人机协同边界'],
  ] as const){
    await login(page,username);await page.getByRole('menuitem',{name:menu}).click();await expect(page).toHaveURL(new RegExp(path.replaceAll('/','\\/')))
    // Citizen intelligence is CitizenPreReview; staff pages keep the advisory boundary Alert.
    await expect(page.getByText(boundary).first()).toBeVisible({timeout:15_000})
    if(boundary==='人机协同边界'){
      await expect(page.getByText(/不会把任何 AI 输出自动写入工单状态/)).toBeVisible({timeout:15_000})
    }
  }
})

test('真实浏览器生成紧急 AI 提示且不改变工单行政状态',async({page,request})=>{
  test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流')
  test.setTimeout(90_000)
  const citizenToken=await apiLogin(request,'citizen_local');const agentToken=await apiLogin(request,'agent_local')
  const created=await request.post('/api/v1/tickets',{headers:{Authorization:`Bearer ${citizenToken}`},data:{idempotency_key:`phase6-ai-${Date.now()}-${Math.random()}`,request_type:'投诉',description:'幸福路社区燃气泄漏并且有人受伤，请立即人工核实',location:'幸福路社区 8 号楼',timezone:'Asia/Shanghai',source:'phase6-e2e'}})
  expect(created.ok()).toBeTruthy();const before=(await created.json()).data.ticket
  await login(page,'agent_local');await page.getByRole('menuitem',{name:'智能分派'}).click();await page.getByLabel('工单编号').fill(before.ticket_id)
  // r2-9: extend analyze timeout to 60s; LLM (if available) runs risk + 5 more types.
  const response=page.waitForResponse(r=>r.url().includes(`/api/v1/ai/tickets/${before.ticket_id}/analyze`)&&r.status()===200,{timeout:60_000})
  await page.getByRole('button',{name:'生成 AI 建议'}).click();await response
  // r2-9: "敏感紧急提示" is the rule-based suggestion_type label (deterministic,
  // not LLM-generated); the recommendation text is also rule-based because the
  // description contains "燃气泄漏" + "有人受伤" (URGENT_WORDS).
  await expect(page.getByText('敏感紧急提示').first()).toBeVisible({timeout:30_000})
  await expect(page.getByText(/请立即由人工核实并按应急预案升级/).first()).toBeVisible({timeout:15_000})
  await expect(page.getByText(/不得未经人工核实直接作为办结/).first()).toBeVisible({timeout:15_000})
  const detail=await request.get(`/api/v1/tickets/${before.ticket_id}`,{headers:{Authorization:`Bearer ${agentToken}`}});expect(detail.ok()).toBeTruthy();const after=(await detail.json()).data
  expect(after.status).toBe(before.status);expect(after.version).toBe(before.version)
})

test('编排与 Rasa 均不可用时聊天页可降级重试',async({page})=>{
  await page.route('**/api/v1/orchestrator/**',route=>route.abort())
  await page.route('**/api/v1/chat/rasa**',route=>route.abort())
  await page.route('**/rasa/**',route=>route.abort())
  await page.goto('/chat')
  await page.getByLabel('输入消息').fill('测试服务降级')
  await page.getByRole('button',{name:/^发送$/}).click()
  // Both the banner Alert and the bot bubble may match; assert the Alert + retry.
  await expect(page.getByRole('alert').filter({hasText:'消息发送失败'})).toBeVisible({timeout:15_000})
  await expect(page.getByRole('button',{name:'重试'})).toBeVisible()
})

test('Backend 不可用时工单页可安全降级',async({page})=>{test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流');await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/);await page.route('**/api/v1/tickets**',route=>route.abort());await page.goto('/citizen/tickets');await expect(page.getByText('网络连接失败，请检查服务状态')).toBeVisible();await expect(page.getByRole('button',{name:'重新加载'})).toBeVisible()})

test('停用用户无法登录',async({page,request})=>{test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流');const adminToken=await apiLogin(request,'admin_local');const username=`disabled_e2e_${Date.now()}`;const created=await request.post('/api/v1/users',{headers:{Authorization:`Bearer ${adminToken}`},data:{username,password,display_name:'E2E 停用用户',role:'citizen',is_active:false}});expect(created.status()).toBe(201);await page.goto('/login');await page.getByLabel('用户名').fill(username);await page.getByLabel('密码').fill(password!);await page.getByRole('button',{name:/登录/}).click();await expect(page.getByRole('alert')).toContainText('用户名或密码错误')})

test('并发版本冲突会提示并刷新',async({page,request})=>{test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流');const citizenToken=await apiLogin(request,'citizen_local');const agentToken=await apiLogin(request,'agent_local');const created=await request.post('/api/v1/tickets',{headers:{Authorization:`Bearer ${citizenToken}`},data:{idempotency_key:`conflict-${Date.now()}-${Math.random()}`,request_type:'咨询',description:'E2E 并发冲突验证工单',location:'线上',timezone:'Asia/Shanghai',source:'web'}});const ticket=(await created.json()).data.ticket;await login(page,'agent_local');await expect(page).toHaveURL(/agent\/tickets/);await page.goto(`/agent/tickets/${ticket.ticket_id}`);await expect(page.getByRole('button',{name:'受理工单'})).toBeVisible();const concurrent=await request.post(`/api/v1/tickets/${ticket.ticket_id}/accept`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticket.version,remark:'并发操作先行受理'}});expect(concurrent.ok()).toBeTruthy();await page.getByRole('button',{name:'受理工单'}).click();await page.getByLabel('末级诉求分类').click();await page.getByText(/路灯故障 · CSGL-GGSS-LD/).last().click();await page.getByLabel('操作备注').fill('使用旧版本再次受理');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText('数据已被他人更新，已为你加载最新工单')).toBeVisible()})

test('市民满意评价后直接办结',async({page,request})=>{
  test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流')
  const citizenToken=await apiLogin(request,'citizen_local');const agentToken=await apiLogin(request,'agent_local');const staffToken=await apiLogin(request,'department_local')
  const departments=await request.get('/api/v1/departments',{headers:{Authorization:`Bearer ${agentToken}`}})
  const departmentId=((await departments.json()).data as {id:number;name:string}[]).find(item=>item.name==='综合受理')!.id
  const created=await request.post('/api/v1/tickets',{headers:{Authorization:`Bearer ${citizenToken}`},data:{idempotency_key:`feedback-${Date.now()}-${Math.random()}`,request_type:'求助',description:'E2E 市民评价闭环验证',location:'幸福路社区',timezone:'Asia/Shanghai',source:'web'}})
  const ticket=(await created.json()).data.ticket
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/accept`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:1,remark:'评价测试受理'}})).ok()).toBeTruthy()
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/assign`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:2,remark:'评价测试派发',department_id:departmentId}})).ok()).toBeTruthy()
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/process`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:3,remark:'评价测试处理'}})).ok()).toBeTruthy()
  // P0-A: submit primary work order before summary
  const detailBefore=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  const primary=(await detailBefore.json()).data.work_orders.find((w:{task_type:string})=>w.task_type==='primary')
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/work-orders/${primary.id}/submit`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:primary.version,remark:'评价测试提交结果',result_summary:'诉求已经处理',result_measures:'完成现场协调处理',result_outcome:'resolved',public_content:'您的诉求已经处理完成'}})).ok()).toBeTruthy()
  const detailAfter=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  const ticketVersion=(await detailAfter.json()).data.version
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/summary`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:ticketVersion,remark:'评价测试内部复核',resolution_summary:'诉求已经处理',resolution_measures:'完成现场协调处理',resolution_outcome:'resolved',public_reply:'您的诉求已经处理完成',internal_note:'仅内部可见'}})).ok()).toBeTruthy()
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/review-resolve`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticketVersion+1,remark:'坐席审核办结',resolution_summary:'诉求已经处理',resolution_measures:'完成现场协调处理',resolution_outcome:'resolved',public_reply:'您的诉求已经处理完成',internal_note:'仅内部可见'}})).ok()).toBeTruthy()
  await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/);await page.goto(`/citizen/tickets/${ticket.ticket_id}`)
  await page.getByRole('button',{name:'确认结果并评价'}).click();await page.getByLabel('评价内容（可选）').fill('处理结果满意');await page.getByRole('button',{name:'确认提交'}).click()
  await expect(page.locator('.ant-tag').filter({hasText:'已办结'}).first()).toBeVisible();await expect(page.getByText('市民确认')).toBeVisible()
})

test('阶段五通知、申诉重办和电话回访完整闭环',async({page,request})=>{
  test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流');test.setTimeout(90_000)
  const citizenToken=await apiLogin(request,'citizen_local');const agentToken=await apiLogin(request,'agent_local');const staffToken=await apiLogin(request,'department_local')
  const departments=await request.get('/api/v1/departments',{headers:{Authorization:`Bearer ${agentToken}`}})
  const departmentId=((await departments.json()).data as {id:number;name:string}[]).find(item=>item.name==='综合受理')!.id
  const created=await request.post('/api/v1/tickets',{headers:{Authorization:`Bearer ${citizenToken}`},data:{idempotency_key:`phase5-${Date.now()}-${Math.random()}`,request_type:'投诉',description:'阶段五夜间噪声申诉回访验证',location:'幸福路社区',timezone:'Asia/Shanghai',source:'e2e'}})
  let ticket=(await created.json()).data.ticket
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/accept`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticket.version,remark:'阶段五受理',priority:'normal'}})).json()).data
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/assign`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticket.version,remark:'阶段五派发',department_id:departmentId}})).json()).data
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/process`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:ticket.version,remark:'阶段五开始处理'}})).json()).data
  // P0-A: submit primary work order before summary
  const phase5Detail1=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  const phase5Primary1=(await phase5Detail1.json()).data.work_orders.find((w:{task_type:string})=>w.task_type==='primary')
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/work-orders/${phase5Primary1.id}/submit`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:phase5Primary1.version,remark:'阶段五提交结果',result_summary:'首次处理完成',result_measures:'完成日间现场核查',result_outcome:'resolved',public_content:'已完成首次处理，请确认'}})).ok()).toBeTruthy()
  const phase5Refresh1=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  ticket=(await phase5Refresh1.json()).data
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/summary`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:ticket.version,remark:'阶段五首次处理',resolution_summary:'首次处理完成',resolution_measures:'完成日间现场核查',resolution_outcome:'resolved',public_reply:'已完成首次处理，请确认'}})).json()).data
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/review-resolve`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticket.version,remark:'阶段五坐席审核办结',resolution_summary:'首次处理完成',resolution_measures:'完成日间现场核查',resolution_outcome:'resolved',public_reply:'已完成首次处理，请确认'}})).json()).data

  await login(page,'citizen_local');await page.getByRole('menuitem',{name:'通知中心'}).click();await expect(page.getByRole('heading',{name:'通知中心'})).toBeVisible();await expect(page.getByText('等待市民确认').first()).toBeVisible()
  await page.getByRole('menuitem',{name:'回访与申诉'}).click();await page.getByRole('button',{name:'提交申诉'}).click();await page.getByLabel('工单编号').fill(ticket.ticket_id);await page.getByLabel('申诉理由').fill('首次处理没有覆盖夜间噪声反复出现的问题');await page.getByLabel('期望处理方式').fill('请安排夜间复查并反馈结果');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText(`${ticket.ticket_id}-SS-1`)).toBeVisible()

  await login(page,'admin_local');await page.getByRole('menuitem',{name:'回访与申诉'}).click();const appealRow=page.locator('.ant-list-item').filter({hasText:ticket.ticket_id});await appealRow.getByRole('button',{name:'审核申诉'}).click();await page.getByLabel('审核意见').fill('申诉事实清楚，同意重新办理');await page.getByLabel('重新办理要求').fill('安排夜间复查并公开复查证据');await page.getByRole('button',{name:'提交审核'}).click();await expect(page.getByText('重新办理中').first()).toBeVisible()

  const detailResponse=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}});ticket=(await detailResponse.json()).data;expect(ticket.handling_round).toBe(2)
  // P0-A: submit primary work order before summary (reprocessing round)
  const phase5Detail2=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  const phase5Primary2=(await phase5Detail2.json()).data.work_orders.find((w:{task_type:string})=>w.task_type==='primary')
  expect((await request.post(`/api/v1/tickets/${ticket.ticket_id}/work-orders/${phase5Primary2.id}/submit`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:phase5Primary2.version,remark:'阶段五重新办理提交结果',result_summary:'夜间复查完成',result_measures:'夜间驻点核查并整改',result_outcome:'resolved',public_content:'夜间复查和整改已经完成'}})).ok()).toBeTruthy()
  const phase5Refresh2=await request.get(`/api/v1/tickets/${ticket.ticket_id}`,{headers:{Authorization:`Bearer ${staffToken}`}})
  ticket=(await phase5Refresh2.json()).data
  ticket=(await (await request.post(`/api/v1/tickets/${ticket.ticket_id}/summary`,{headers:{Authorization:`Bearer ${staffToken}`},data:{version:ticket.version,remark:'阶段五重新办理',resolution_summary:'夜间复查完成',resolution_measures:'夜间驻点核查并整改',resolution_outcome:'resolved',public_reply:'夜间复查和整改已经完成'}})).json()).data
  const resolvedAgain=await request.post(`/api/v1/tickets/${ticket.ticket_id}/review-resolve`,{headers:{Authorization:`Bearer ${agentToken}`},data:{version:ticket.version,remark:'阶段五重新办理审核办结',resolution_summary:'夜间复查完成',resolution_measures:'夜间驻点核查并整改',resolution_outcome:'resolved',public_reply:'夜间复查和整改已经完成'}});expect(resolvedAgain.ok()).toBeTruthy()

  await login(page,'agent_local');await page.getByRole('menuitem',{name:'回访与申诉'}).click()
  // Playwright has no toHaveCountGreaterThanOrEqual; assert first card then round-2 card.
  await expect(page.locator('.follow-up-card').first()).toBeVisible({timeout:15_000})
  const round2Card=page.locator('.follow-up-card',{hasText:ticket.ticket_id}).filter({hasText:'第 2 轮'})
  await expect(round2Card).toBeVisible({timeout:15_000})
  await round2Card.getByRole('button',{name:'记录电话回访'}).click()
  await page.getByLabel('回访记录').fill('市民确认重新办理结果满意，同意办结');await page.getByRole('button',{name:'保存记录'}).click()
  await expect(round2Card.getByText('已完成').first()).toBeVisible({timeout:15_000})

  await login(page,'citizen_local');await page.getByRole('menuitem',{name:'通知中心'}).click();await expect(page.getByText('工单已办结').first()).toBeVisible();await page.getByRole('menuitem',{name:'回访与申诉'}).click();const citizenAppeal=page.locator('.ant-list-item').filter({hasText:ticket.ticket_id});await expect(citizenAppeal.getByText(/夜间复查和整改已经完成/)).toBeVisible()
})

test.describe.serial('真实工单全状态闭环',()=>{
  test.skip(!password,'设置 E2E_PASSWORD 后运行真实账号工作流')
  let ticketId=''

  test('市民通过聊天创建真实诉求并查看详情',async({page})=>{
    test.setTimeout(120_000)
    await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/)
    await page.getByRole('button',{name:'新建会话'}).click()
    await page.getByLabel('输入消息').fill('幸福路社区路灯连续三晚不亮')
    await Promise.all([
      page.waitForResponse(r=>r.url().includes('/api/v1/orchestrator/chat')&&r.status()===200,{timeout:60_000}),
      page.getByRole('button',{name:/^发送$/}).click(),
    ])
    await expect(page.locator('.draft-panel')).toBeVisible({timeout:30_000})
    const submitBtn=page.getByRole('button',{name:'确认提交工单'})
    if(!(await submitBtn.isEnabled())){
      const pendingRow=page.locator('.draft-panel .ant-descriptions-item').filter({hasText:'待补充'}).first()
      await pendingRow.getByRole('button').first().click()
      const fieldInput=page.locator('.draft-panel input, .draft-panel textarea').first()
      await fieldInput.fill('幸福路社区')
      await fieldInput.blur()
      await expect(submitBtn).toBeEnabled({timeout:5_000})
    }
    await submitBtn.click()
    const ticketCard=page.locator('.ticket-highlight').last()
    await expect(ticketCard).toContainText(/QT\d{16}/,{timeout:20_000})
    const match=(await ticketCard.textContent())?.match(/QT\d{16}/);expect(match).toBeTruthy();ticketId=match![0]
    await ticketCard.getByRole('link',{name:'查看工单详情'}).click()
    await expect(page.getByRole('heading',{name:ticketId})).toBeVisible()
    await expect(page.getByText(/路灯连续三晚不亮/)).toBeVisible()
  })

  test('坐席确认分类和优先级后受理工单',async({page})=>{await login(page,'agent_local');await expect(page).toHaveURL(/agent\/tickets/);await page.goto(`/agent/tickets/${ticketId}`);await page.getByRole('button',{name:'受理工单'}).click();await page.getByLabel('末级诉求分类').click();await page.getByText(/路灯故障 · CSGL-GGSS-LD/).last().click();await page.getByLabel('确认优先级').click();await page.getByText('紧急',{exact:true}).last().click();await page.getByLabel('操作备注').fill('E2E 坐席已核实分类和紧急程度');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.locator('.ant-tag').filter({hasText:'已受理'}).first()).toBeVisible();await expect(page.getByText('城市管理 / 公共设施 / 路灯故障')).toBeVisible()})

  test('坐席通过页面派发责任部门并继续协调',async({page})=>{await login(page,'agent_local');await expect(page).toHaveURL(/agent\/tickets/);await page.goto(`/agent/tickets/${ticketId}`);await page.getByRole('button',{name:'派发部门'}).click();await page.getByLabel('责任部门').click();await page.locator('.ant-select-item-option').filter({hasText:'综合受理'}).click();await page.getByLabel('操作备注').fill('E2E 派发至综合受理');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText('部门协同任务')).toBeVisible();await expect(page.getByText('综合受理').first()).toBeVisible()})

  test('部门人员开始处理并可筛选分派给我的工单',async({page})=>{
    await login(page,'department_local');await expect(page).toHaveURL(/department\/tickets/);await page.goto(`/department/tickets/${ticketId}`)
    await page.getByRole('button',{name:'开始处理'}).click();await page.getByLabel('操作备注').fill('E2E 已到现场开始处理');await page.getByRole('button',{name:'确认提交'}).click()
    await expect(page.locator('.ant-tag').filter({hasText:'处理中'}).first()).toBeVisible()
    // "工单范围" lives in the advanced-filter drawer; keyword search is the stable assertion.
    await page.goto('/department/tickets')
    await page.getByPlaceholder('编号、描述或地点').fill(ticketId)
    await page.getByRole('button',{name:/查\s*询/}).click()
    await expect(page.getByText(ticketId)).toBeVisible()
  })

  test('部门人员暂停并恢复 SLA 计时',async({page})=>{await login(page,'department_local');await expect(page).toHaveURL(/department\/tickets/);await page.goto(`/department/tickets/${ticketId}`);await page.getByRole('button',{name:'暂停 SLA 计时'}).click();await page.getByLabel('暂停原因').fill('等待市民补充现场照片');await page.getByLabel('操作备注').fill('E2E 暂停计时');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText('计时已暂停')).toBeVisible();await page.getByRole('button',{name:'恢复 SLA 计时'}).click();await page.getByLabel('操作备注').fill('E2E 材料已补齐恢复计时');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText('时限正常')).toBeVisible()})

  test('部门人员添加处理记录',async({page})=>{await login(page,'department_local');await expect(page).toHaveURL(/department\/tickets/);await page.goto(`/department/tickets/${ticketId}`);await page.getByRole('button',{name:'添加内部处理记录'}).click();await page.getByLabel('操作备注').fill('E2E 已联系物业并完成现场复核');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.getByText('E2E 已联系物业并完成现场复核')).toBeVisible();await expect(page.locator('.ant-tag').filter({hasText:'处理中'}).first()).toBeVisible()})

  test('部门人员提交工作单结果并汇总答复',async({page})=>{
    await login(page,'department_local');await expect(page).toHaveURL(/department\/tickets/);await page.goto(`/department/tickets/${ticketId}`)
    // P0-A step 1: submit work order result (work order card button)
    await page.getByRole('button',{name:'提交结果'}).first().click()
    await page.getByLabel('结果摘要').fill('路灯故障已修复')
    await page.getByLabel('处理措施').fill('更换损坏灯具并完成夜间亮灯测试')
    await page.getByLabel('处理结果').click();await page.getByText('已解决',{exact:true}).last().click()
    await page.getByLabel('本部门公开答复').fill('已更换灯具并恢复照明')
    await page.getByLabel('操作说明').fill('E2E 部门内部复核通过')
    await page.getByRole('button',{name:'确认提交'}).click()
    await expect(page.getByText('待主办汇总').first()).toBeVisible()
    // P0-A step 2: summarize final reply for agent review
    await page.getByRole('button',{name:'汇总最终答复'}).click()
    await page.getByLabel('最终结果摘要').fill('路灯故障已修复')
    await page.getByLabel('综合处理措施').fill('更换损坏灯具并完成夜间亮灯测试')
    await page.getByLabel('最终结果').click();await page.getByText('已解决',{exact:true}).last().click()
    await page.getByLabel('对市民最终答复').fill('已更换灯具并恢复照明')
    await page.getByLabel('操作说明').fill('E2E 主办部门汇总答复')
    await page.getByRole('button',{name:'确认提交'}).click()
    await expect(page.getByText('待坐席审核').first()).toBeVisible()
  })

  test('坐席审核办结',async({page})=>{
    await login(page,'agent_local');await expect(page).toHaveURL(/agent\/tickets/);await page.goto(`/agent/tickets/${ticketId}`)
    // P0-A step 3: agent reviews and resolves
    await page.getByRole('button',{name:'审核办结'}).click()
    await page.getByLabel('最终结果摘要').fill('路灯故障已修复')
    await page.getByLabel('综合处理措施').fill('更换损坏灯具并完成夜间亮灯测试')
    await page.getByLabel('最终结果').click();await page.getByText('已解决',{exact:true}).last().click()
    await page.getByLabel('对市民最终答复').fill('已更换灯具并恢复照明')
    await page.getByLabel('操作说明').fill('E2E 坐席审核通过')
    await page.getByRole('button',{name:'确认提交'}).click()
    await expect(page.locator('.ant-tag').filter({hasText:'待市民确认'}).first()).toBeVisible()
  })

  test('市民看到最新办理进度',async({page})=>{await login(page,'citizen_local');await expect(page).toHaveURL(/citizen\/chat/);await page.goto(`/citizen/tickets/${ticketId}`);await expect(page.locator('.ant-tag').filter({hasText:'待市民确认'}).first()).toBeVisible();await expect(page.getByText('已更换灯具并恢复照明').first()).toBeVisible();await expect(page.getByText('E2E 部门内部复核通过')).toHaveCount(0)})

  test('管理员说明依据后代办结',async({page})=>{await login(page,'admin_local');await expect(page).toHaveURL(/admin\/dashboard/);await page.goto(`/admin/tickets/${ticketId}`);await page.getByRole('button',{name:'管理员代办结'}).click();await page.getByLabel('代办结原因').fill('电话回访确认问题已经解决');await page.getByLabel('操作备注').fill('E2E 管理员依据回访记录闭环');await page.getByRole('button',{name:'确认提交'}).click();await expect(page.locator('.ant-tag').filter({hasText:'已办结'}).first()).toBeVisible()})
})
