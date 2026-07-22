# 五分钟演示（现行）

> **文档基线（本轮整理核对）**
> - Commit：`438047c776787da6c5b412c403c7799ba52364c8`（`Expand municipal category coverage for demos and add README UI screenshots.`）
> - Alembic head：`0025`
> - 演示派发部门：**综合受理**；部门账号：`department_local`
> - 状态机以代码为准：部门提交结果 ≠ 办结；坐席 `review-resolve` → `resolved`；市民满意或管理员代办结 → `closed`
> - 申诉提交后**不**立即重办；管理员批准后才回 `processing`
> - AI 采纳只记人工决策，**不**自动写业务字段 / 改状态

旧稿见 [archive/demo-script.md](./archive/demo-script.md)（内容可能过期，以本文为准）。

## 演示前：重置环境

```powershell
docker compose ps
# 开发 8 服务应 healthy：frontend / postgres / minio / backend / duckling / action_server / rasa / worker

docker exec -w /app `
  -e SEED_PASSWORD=tingting-seed-demo-2026 `
  -e CONFIRM_DEMO_RESET=YES `
  tingting-assistant-backend-1 `
  python -m scripts.demo_reset --confirm-reset
```

打开 `http://localhost:8080`，准备四个无痕窗口。

| 角色 | 用户名 | 密码（`SEED_PASSWORD`） | 部门 |
|---|---|---|---|
| 市民 | `citizen_local` | `tingting-seed-demo-2026` | — |
| 坐席 | `agent_local` | 同上 | — |
| 部门 | `department_local` | 同上 | **综合受理**（`general-intake`） |
| 管理员 | `admin_local` | 同上 | — |

**演示策略**：坐席派发一律选「综合受理」，否则 `department_local` 看不到工单。AI 可建议其他归口，口播说明「演示环境由综合受理接单闭环」。

---

## 第 1 步：市民政策咨询（约 45 秒）

1. 登录 `citizen_local` → 智能对话。
2. 输入：「社保补贴政策适用于哪些人群」。
3. 预期：路由 `policy_rag`；答案带 `citations[]`（`title` / `doc_number` / `issuing_authority` / `excerpt`）；`should_create_ticket=false`；无证据时 `no_evidence`，不编造。

未配置 `AI_API_KEY` / `EMBEDDING_API_KEY` 时会降级（规则 / 关键词检索），管理员 AI 用量页可见 `degrade_reason`。**不要把降级演示说成真实向量检索。**

---

## 第 2 步：市民建单（约 45 秒）

1. **新会话**，输入：「幸福路路灯坏了」。
2. 预期：`ticket_intake` 草稿；市民补全后点「提交工单」得到 `QT...` 号。
3. AI 只出草稿，市民点击才落库。

---

## 第 3 步：坐席分诊与派发（约 60 秒）

1. 登录 `agent_local` → 打开工单。
2. （可选）打开「智能分诊与派发」：capability=`triage_assistant`，状态须为 `pending`/`accepted`。生成建议后点「记录为已采纳」——**仅审计，不自动派发**。
3. 工单详情：「受理」→「派发」选 **综合受理**。
4. 状态：`pending → accepted → assigned`。

分诊 vs 办件：坐席页只做分类/紧急度/部门候选/SLA/告知语；不要在坐席侧期望办结文书。

---

## 第 4 步：部门办件（约 60 秒）

1. 登录 `department_local` → 打开该工单。
2. 「开始处理」→ `processing`。
3. （可选）「AI 办件与文书辅助」：capability=`handling_assistant`；「记录采纳意见」**不会**自动填结果或办结。
4. 填写并提交 work order 结果 → 主办「汇总」提交待审。
5. 此时主单仍为 **`processing`**，`collaboration_status=awaiting_review`（**不是** `resolved` / `closed`）。

---

## 第 5 步：坐席复核办结（约 30 秒）

1. 回到 `agent_local` → 工单详情。
2. 执行 **复核办结**（`POST .../review-resolve`）。
3. 状态：`processing` → **`resolved`**（待市民确认）。

部门不能直接把主单办结为 `resolved`/`closed`。

---

## 第 6 步：市民确认 / 申诉（约 30 秒）

**满意路径**

1. `citizen_local` → 确认结果并评价满意。
2. 状态：`resolved` → **`closed`**（`closure_type=citizen_confirmed`）。

**不满意 + 申诉路径（可选）**

1. 评价不满意 → 主单**保持** `resolved`（不自动重开）。
2. 提交申诉 → `appeals.status=submitted`，主单状态**不变**。
3. `admin_local` 批准申诉 → 主单才回 **`processing`** 重办。

管理员也可对 `resolved` 工单代办结（`close`）→ `closed`。

---

## 第 7 步：管理员审计与 AI 用量（约 30 秒）

1. `admin_local` → 审计日志：可按 `request_id` 串联动作。
2. AI 用量页：真实 LLM 时 `total_tokens > 0`；`estimated_cost_rmb` 为**本地估算**，不是供应商账单。
3. 可按 capability 区分 `triage_assistant` / `handling_assistant`。

---

## 失败退路

| 现象 | 处理 |
|---|---|
| 服务不健康 | `docker compose ps` / `docker compose logs backend` |
| 部门看不到单 | 确认派发到「综合受理」 |
| AI 超时 | 自动规则降级；卡片 `provider=rules` |
| 数据脏 | 再跑 `demo_reset`（需 `CONFIRM_DEMO_RESET=YES`） |
| 误删数据 | **勿**在演示现场 `docker compose down -v` |
