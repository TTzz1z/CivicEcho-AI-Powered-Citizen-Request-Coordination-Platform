# 五分钟演示脚本

> 演示前重置环境，确保工单列表、AI 用量、审计日志干净。本脚本约 5 分钟走完一条主闭环，覆盖市民咨询、工单全生命周期、AI 办件助手（advisory only）、审计与 AI 用量。

## 演示前 1 分钟：重置环境

```powershell
# 1. 确认 .env 已填好 4 个强密钥 + AI_API_KEY + EMBEDDING_API_KEY
# 2. 确认 8 服务 healthy
docker compose ps

# 3. 一键重置演示数据
SEED_PASSWORD=tingting-seed-demo-2026 docker exec -w /app tingting-assistant-backend-1 python -m scripts.demo_reset
```

预期输出：清理事务表（tickets/notifications/ai_usage_logs/audit_logs 等）+ 重新 Seed 4 账号 + 演示 KB 文档。打开 `http://localhost:8080`，准备四个无痕窗口。

| 角色 | 用户名 | 密码 |
|---|---|---|
| 市民 | `citizen_local` | `tingting-seed-demo-2026` |
| 坐席 | `agent_local` | `tingting-seed-demo-2026` |
| 部门人员 | `department_local` | `tingting-seed-demo-2026` |
| 管理员 | `admin_local` | `tingting-seed-demo-2026` |

---

## 第 1 步：市民政策咨询（约 45 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `citizen_local` |
| 操作页面 | 首页 → "智能对话" → `ChatPage` |
| 操作 | 输入 "社保补贴政策适用于哪些人群" |

预期结果：
- AI 返回带引用的政策答案。
- 答案下方展示 `citations[]` 卡片，每条引用包含：
  - `title`（如《就业创业补贴政策实施细则》）
  - `doc_number`（如"人社发〔2024〕XX 号"）
  - `issuing_authority`（如"市人力资源和社会保障局"）
  - `excerpt`（命中段落原文）

关键验证点：
- 答案中的事实陈述必须能在 citation 的 excerpt 中找到对应文字。
- 若检索无证据，返回 `no_evidence=true`，提示"是否创建咨询工单"，不编造答案。
- 右侧 "对话建议" 不出现 "提交工单" 按钮（policy_rag 不建单）。

---

## 第 2 步：市民描述路灯问题并提交工单（约 45 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `citizen_local` |
| 操作页面 | 仍在 `ChatPage`，发起**新会话** |
| 操作 | 输入 "幸福路路灯坏了" |

预期结果：
- Orchestrator 识别为 `ticket_intake` 路由。
- 右侧 `TicketDraftPanel` 显示草稿：description="幸福路路灯坏了"、location="幸福路"、request_type=complaint。
- 动态字段提示：道路/小区（必填）、故障位置（必填）、持续时间（必填）。
- 市民补全 "幸福路 88 号" + "3 天" 后点击 "提交工单"。

关键验证点：
- 提交后返回 `QT...` 工单号。
- AI 仅生成草稿，不直接建单；市民点击提交才落库。
- session_id 隔离：新会话不会继承上一轮社保咨询的上下文（避免政策上下文污染工单）。

---

## 第 3 步：坐席受理、确认 AI 分类、派发（约 45 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `agent_local` |
| 操作页面 | "工单列表" → 打开上一步创建的工单 → `TicketDetailPage` |
| 操作 | 1) 查看 AI 自动分类建议 → 2) 点击 "受理工单" → 3) "派发部门" 选择 "城市管理" |

预期结果：
- 工单状态：`pending → accepted → assigned`。
- `ticket_status_history` 留痕：每步记录 operator_user_id、operation_type、previous/current status。
- 顶部 "版本号" 字段从 1 递增到 3（每次状态变更 +1）。

关键验证点：
- 三态人工确认：AI 自动分类建议显示 "建议分类=路灯报修/城市管理"，坐席可 `accept` / `modify` / `reject`。
- 若 AI 自动分类错误，坐席点 `modify` 改为正确分类（如 "教育投诉/教育服务"）后才派发，体现 advisory only。
- 越权验证：尝试用 `citizen_local` 账号点击受理按钮，前端守卫拦截 + 后端 `AuthorizationPolicy.require_transition` 返回 403。

---

## 第 4 步：部门登录，AI 办件助手，采纳建议，提交办理结果（约 60 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `department_local` |
| 操作页面 | "我的工单" → 打开刚派发的工单 → `TicketDetailPage` → 右侧 `AiCaseAssistant` |
| 操作 | 1) 点击 "开始处理" → 2) 点 "AI 办件助手" 生成建议 → 3) 采纳建议 → 4) 填写办理结果 → 5) "提交处理结果" |

预期结果：
- 工单状态：`assigned → processing → resolved`。
- AI 办件助手返回：处理摘要、风险提示、责任部门建议、文书草稿。
- 每条 AI 建议卡片显示 `provider=deepseek`、`model=deepseek-chat`。
- 采纳（accept）后建议内容填入草稿，但仍需人工点 "提交处理结果" 才进入 `resolved`。

关键验证点：
- AI 建议仅写入 `ai_suggestions` 表，不直接修改 `ticket.status`。
- `advisory_only=true` 在 UI 顶部显著标注 "人机协同边界"。
- 三态人工确认按钮：accept / modify / reject，不会出现 "AI 自动办结" 按钮。

---

## 第 5 步：坐席审核办结（约 30 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `agent_local` |
| 操作页面 | 工单详情 → `TicketDetailPage` |
| 操作 | 查看部门提交的办理结果 → 点击 "办结工单" → 填写公开依据 |

预期结果：
- 工单状态：`resolved → closed`。
- `closed_at` 写入。
- `notifications` 自动给 `citizen_local` 推送 "工单已办结" 通知（worker 异步投递）。

关键验证点：
- 部门人员不能直接办结（`require_transition` 限制 `close` 仅 agent/admin）。
- 版本号一致性：若期间市民在前端做了评价导致版本变化，坐席点办结时返回 409 `VERSION_CONFLICT`，前端提示刷新。

---

## 第 6 步：市民评价或申诉（约 30 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `citizen_local` |
| 操作页面 | "我的工单" → 打开办结工单 |
| 操作（满意） | 点击 "确认结果并评价" → 5 星 + "已修复" → 工单保持 `closed`。 |
| 操作（不满意） | 选 "不满意" → 提交申诉理由与期望结果 → 工单回 `processing` + 等待管理员审核。 |

预期结果（满意）：
- `ticket_feedbacks` 写入 rating=5、result=satisfied。
- 工单正式完结。

预期结果（不满意 + 申诉）：
- `appeals` 写入 appeal_no、sequence=1、status=submitted。
- 工单 `status` 由 `resolved` 回到 `processing`（重办）。
- `admin_local` 收到申诉审核通知。

关键验证点：
- 每工单申诉次数有上限（`appeal_count` 与 `sequence` 唯一约束）。
- 申诉窗口期由 SLA 策略控制；窗口外不允许申诉。

---

## 第 7 步：管理员查看审计日志与 AI 用量（约 30 秒）

| 项 | 值 |
|---|---|
| 登录账号 | `admin_local` |
| 操作页面 | 1) 左侧 "审计日志" → `AuditPage` 2) 左侧 "AI 用量与安全" → `AdminAiUsagePage` |

预期结果（审计页）：
- 列表显示本轮演示所有业务动作（create_ticket / accept / assign / process / resolve / close / feedback / appeal）。
- 每条记录有 `request_id`、`actor_user_id`、`action`、`outcome`、`created_at`。
- 可按 `request_id` 筛选，串联出一次请求的完整链路。

预期结果（AI 用量页）：
- 列表显示至少 4 条真实 LLM 调用记录（社保咨询、办事指南、AI 办件助手、AI 草稿提取）。
- 每条记录：`provider=deepseek`、`model_name=deepseek-chat`、`total_tokens` 在 1582-2419 区间、`estimated_cost_rmb` 在 0.013-0.019 RMB 区间、`usage_unavailable=false`。
- 顶部统计：总调用次数、总 tokens、总成本、各 capability 分布。
- 可按 `session_id` 筛选，把同一次会话的多次模型调用聚合展示。
- 可按 `degrade_reason` 筛选降级调用（正常演示应为空，除非演示降级场景）。

关键验证点：
- `total_tokens > 0`：证明是真实 DeepSeek 调用，不是 mock。
- `request_id` 与审计页一一对应：一次市民请求同时产生 audit_logs + ai_usage_logs。
- `session_id` 隔离：社保咨询 session 与路灯报修 session 是两个不同 session_id。

---

## 降级场景演示（可选，约 1 分钟）

如需展示降级：

1. 编辑 `.env`，将 `AI_API_KEY` 改为空 → `docker compose up -d backend`。
2. 市民重新咨询 "社保补贴政策" → 系统返回 "智能解答服务暂时不可用，已切换到检索模式"，仍展示 citations。
3. 管理员 AI 用量页查看：`provider=rules`、`degraded=true`、`degrade_reason=llm_unavailable`、`total_tokens=0`。

如需展示 embedding 降级：将 `EMBEDDING_API_KEY` 改为空 → RAG 回退到关键词检索，`kb_chunks.embedding_fallback=fallback_used`。

---

## 失败时的安全退路

- 页面打不开：`docker compose ps` 确认 8 服务 healthy；`docker compose logs backend` 查错误。
- AI 调用超时：系统自动降级规则，AI 卡片 `provider` 变为 `rules`，演示不中断。
- 端口冲突：只改 `.env` 的 `FRONTEND_PORT`，不改容器内端口。
- 演示数据脏：再次执行 `python -m scripts.demo_reset`。
- Rasa 首次加载慢：`docker compose logs rasa`，确认模型文件 `tingting-v1.2.0.tar.gz`。
- 不在现场执行 `docker compose down -v`，会删除数据库与 MinIO 卷。
