# CivicEcho v2 五分钟演示

> **演示基线**
> - Alembic head 为 `0032`，预置近 14 天 18 条工单及 3 份真实 PDF / PNG 附件。
> - 演示派发部门：**综合受理**；部门账号：`department_local`
> - 状态机以代码为准：部门提交结果 ≠ 办结；坐席 `review-resolve` → `resolved`；市民满意或管理员代办结 → `closed`
> - 申诉提交后**不**立即重办；管理员批准后才回 `processing`
> - AI 采纳只记人工决策，**不**自动写业务字段 / 改状态

## 演示准备

```powershell
.\scripts\check-demo.ps1 -Start -Build
```

打开脚本输出的 Web 地址，准备四个独立的浏览器会话。密码取自本地 `SEED_PASSWORD`。

| 角色 | 用户名 | 密码（`SEED_PASSWORD`） | 部门 |
|---|---|---|---|
| 市民 | `citizen_local` | 读取本地 `SEED_PASSWORD` | — |
| 坐席 | `agent_local` | 同上 | — |
| 部门 | `department_local` | 同上 | **综合受理**（`general-intake`） |
| 管理员 | `admin_local` | 同上 | — |

**演示策略**：坐席派发一律选「综合受理」，否则 `department_local` 看不到工单。AI 可建议其他归口，口播说明「演示环境由综合受理接单闭环」。

---

## 第 1 步：市民政策咨询（约 45 秒）

1. 登录 `citizen_local` → 智能对话。
2. 输入：「社保补贴政策适用于哪些人群」。
3. 预期看到增量正文、停止生成按钮和供核对的政策引用。无证据时页面提示无法作答。

未配置 `AI_API_KEY` / `EMBEDDING_API_KEY` 时会降级（规则 / 关键词检索），管理员 AI 用量页可见 `degrade_reason`。**不要把降级演示说成真实向量检索。**

---

## 第 2 步：市民建单（约 45 秒）

1. **新会话**，输入：「幸福路路灯坏了」。
2. 界面生成 `ticket_intake` 草稿，市民补全后点击「确认提交工单」，取得工单编号。
3. AI 只出草稿，市民点击才落库。

---

## 第 3 步：坐席分诊与派发（约 60 秒）

1. 登录 `agent_local` → 打开工单。
2. （可选）打开「智能分诊与派发」：capability=`triage_assistant`，状态须为 `pending`/`accepted`。生成建议后点「记录为已采纳」——**仅审计，不自动派发**。
3. 工单详情：「受理」→「派发」选 **综合受理**。
4. 状态：`pending → accepted → assigned`。

可从坐席工单台勾选两条现成的已受理工单，打开批量派发，查看每条工单的结果。派发会改变演示状态，演示前可先浏览列表与弹窗，提交时选用本次演示创建的工单。

分诊 vs 办件：坐席页只做分类/紧急度/部门候选/SLA/告知语；不要在坐席侧期望办结文书。

---

## 第 4 步：部门办件（约 60 秒）

1. 登录 `department_local` → 打开该工单。
2. 「开始处理」→ `processing`。
3. （可选）「AI 办件与文书辅助」：capability=`handling_assistant`；「记录采纳意见」**不会**自动填结果或办结。
4. 填写并提交 work order 结果 → 主办「汇总」提交待审。
5. 此时主单仍为 **`processing`**，`collaboration_status=awaiting_review`（**不是** `resolved` / `closed`）。

如需展示 PDF，查看部门工单 `QT2026110000000010` 的附件材料，打开供电抢修验收单。工单详情右上角可打印。

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

可在市民页面保持通知抽屉打开，查看办理事件推送到未读角标与列表。

**不满意 + 申诉路径（可选）**

1. 评价不满意 → 主单**保持** `resolved`（不自动重开）。
2. 提交申诉 → `appeals.status=submitted`，主单状态**不变**。
3. `admin_local` 批准申诉 → 主单才回 **`processing`** 重办。

管理员也可对 `resolved` 工单代办结（`close`）→ `closed`。

---

## 第 7 步：管理员审计与 AI 用量（约 30 秒）

1. `admin_local` 打开运营总览查看 14 天登记趋势。审计页支持按 `request_id` 串联动作并导出 CSV。
2. AI 用量页：真实 LLM 时 `total_tokens > 0`；`estimated_cost_rmb` 为**本地估算**，不是供应商账单。
3. 可按 capability 区分 `triage_assistant` / `handling_assistant`。

---

## 失败退路

| 现象 | 处理 |
|---|---|
| 服务不健康 | `docker compose ps` / `docker compose logs backend` |
| 部门看不到单 | 确认派发到「综合受理」 |
| AI 超时 | 自动规则降级；卡片 `provider=rules` |
| 需要清空临时演示操作 | 确认当前环境为可清空的演示库后，执行 `docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m scripts.demo_reset --confirm-reset` |
| 误删数据 | **勿**在演示现场 `docker compose down -v` |
