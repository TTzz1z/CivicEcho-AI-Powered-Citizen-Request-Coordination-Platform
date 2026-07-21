# 倾听助手 / 政务诉求协同服务平台 — 最终独立审计报告

**审计时间**：2026-07-21（Asia/Shanghai）
**审计方式**：独立接管 + 全量仓库地图 + 实测验证（Docker / API / DB / 浏览器）+ 联网对标 + UI 走查
**审计范围**：业务正确性、权限数据、AI 可信度、浏览器演示、求职价值
**本轮边界**：只审计、验证、调研、制定方案，**不修改业务代码**

---

## 一、仓库地图与事实来源

### 1.1 顶层结构实测

```
helpdesk-assistant-main/  (根目录, .git 为空目录, 无 git 历史可溯源)
├── backend/             140M  FastAPI + SQLAlchemy + Alembic 0018
│   ├── app/
│   │   ├── api/         18 个路由模块 (auth/tickets/kb/ai/orchestrator/integrations/...)
│   │   ├── services/    15 个业务服务 (ticket_service/orchestrator_service/kb_service/ai_usage_recorder/...)
│   │   ├── repositories/ base+memory+postgres 双实现
│   │   ├── models.py    SQLAlchemy 单文件全模型
│   │   ├── authorization.py  Principal + AuthorizationPolicy (RBAC 单一真相源)
│   │   └── worker.py    SLA 扫描 + 通知 outbox + 登录限流清理
│   ├── migrations/versions/  0001~0018 共 18 个迁移
│   ├── scripts/         demo_reset + verify_r3_* ×6
│   └── tests/           pytest 12 个测试文件
├── frontend/            438M  React 19 + TS + Vite + antd
│   ├── src/pages/       21 个页面 (Landing/Login/Chat/Dashboard/Tickets/TicketDetail/Audit/Aftercare/
│   │                              Notifications/Intelligence/CitizenPolicy/AgentPolicy/AdminKb/AdminAiUsage/
│   │                              DepartmentKb/Categories/Departments/Users/...)
│   ├── src/components/  14 个组件 (AiCaseAssistant/KbRagPanel/TicketDraftPanel/WorkOrderPanel/...)
│   ├── src/api/         12 个 axios+tanstack-query 客户端
│   ├── src/routes/      AppRoutes + guards (角色路由守卫)
│   ├── e2e/             7 个 Playwright spec
│   └── dist/            构建产物 2.4M
├── actions/             Rasa Action Server (handoff/public_request/snow/ticket_gateway)
├── data/                Rasa 中文 NLU/stories/rules (yml)
├── models/              322M 8 个 Rasa 模型 tar.gz (baseline/round2/round2-final/round3/v1.0.0/v1.1.0/v1.2.0-draft)
├── docs/                40 个 md (架构/权限/状态机/phase-1~6/round-2~7 报告/面试指南)
├── scripts/             23 个 py+ps1+sh (acceptance/verify_*/backup/restore/demo)
├── tests/               Rasa 侧 test_nlu/test_conversations/test_public_request_actions
├── docker-compose.yml          开发 8 服务
├── docker-compose.prod.yml     生产 override (Caddy + ClamAV)
├── Dockerfile.backend / Dockerfile.actions / frontend/Dockerfile
├── .github/workflows/ci.yml    唯一 CI
├── Makefile / Caddyfile
└── 根目录配置: config.yml / domain.yml / endpoints.yml / credentials.yml (Rasa)
```

### 1.2 事实来源（按可信度排序）

| 级别 | 文件 | 判断依据 |
|---|---|---|
| **T0 直接事实** | 运行中容器（8 个 healthy）、PostgreSQL 实际数据、FastAPI openapi.json（101 条路由）、代码本体 | 本轮实测读取 |
| **T1 同步文档** | `README.md`、`PRODUCT.md`、`ENGINEERING.md`、`docs/final-test-report.md`、`docs/demo-script.md`、`docs/interview-qa.md`、`docs/architecture-current.md` | mtime 2026-07-20~21,与代码同步 |
| **T2 最新轮次** | `ROUND-3-FINAL-REPORT.md`（2026-07-21)、`PROJECT-AUDIT-AND-ROADMAP.md`（2026-07-20) | 结论与实测基本吻合 |
| **T3 历史过程** | `PROJECT-AUDIT.md`、`UPGRADE-PLAN.md`、`ROUND-1/2-FINAL-REPORT.md`、`PRE-ROUND1-ROOT-CAUSE-REPORT.md`、`docs/round-2~7-*-report.md`、`docs/phase-1~6-*.md` | 阶段性产物,仅作演进参考 |
| **T4 无效残留** | `legacy/`、`data/*.disabled`、`constraints-legacy.txt`、根 `node_modules/`(2 个包)、`frontend/vite.config.{js,d.ts}`、`frontend/playwright.config.{js,d.ts}`、`frontend/test-results/`(99M)、`e2e-result-v2~v5.*` | 明确不应再参考 |

### 1.3 严重仓库卫生问题

- **`.git/` 是空目录**：无任何 commit / branch / tag,**版本历史已完全丢失**,只能靠 mtime + 文件名语义推断演进路径。
- **重复构建配置**:`frontend/vite.config.{ts,js,d.ts}` 与 `frontend/playwright.config.{ts,js,d.ts}` 各 3 份并存（.js/.d.ts 是 tsc 误产出，应删除)。
- **根 `node_modules/` 仅 2 个包**(@types、undici-types,2.8M)—— 明显误装残留。
- **测试产物堆积**:`frontend/test-results/` 99M + `frontend/test-results-v3/` 2.1M + 根目录 `e2e-result-v2~v5.*` 十余个日志 + `playwright-run.log`。
- **Rasa 模型冗余**:`models/` 8 个 tar.gz 共 322M,当前实际生效只有 `tingting-v1.2.0-draft.tar.gz`。
- **多 Python 版本残留**:`channels/__pycache__/` 含 py3.8/3.10/3.12/3.14 四个版本 pyc。
- **`backups/` 是空目录**,`scripts/backup*.ps1` 从未真正跑过。

---

## 二、项目真实现状（实测证据）

### 2.1 运行态

| 服务 | 容器 | 状态 | 端口 | 实测 |
|---|---|---|---|---|
| frontend | tingting-assistant-frontend-1 | healthy | 8081→80 | HTTP 200 |
| backend | tingting-assistant-backend-1 | healthy | 8001→8000 | `/health/ready` 200, `/health/live` 200 |
| postgres | tingting-assistant-postgres-1 | healthy | 内部 5432 | pgvector/pg16, 29 张表 |
| rasa | tingting-assistant-rasa-1 | healthy | 5005 | `/status` 200 |
| action_server | tingting-assistant-action_server-1 | healthy | 5055 | 在线 |
| worker | tingting-assistant-worker-1 | healthy | 8000 | 循环扫描 |
| minio | tingting-assistant-minio-1 | healthy | 9000/9001 | 在线 |
| duckling | tingting-assistant-duckling-1 | healthy | 8000 | 在线 |

**实测**:8/8 healthy，与 README 声明一致。

### 2.2 数据库实测（PostgreSQL 直接查询)

| 表 | 行数 | 判断 |
|---|---|---|
| users | **4**（演示账号）+ **大量测试残留**(citizen_True_f3a6e7be_0/1、agent_True_*、r2_citizen_*、managed_99bc034c 等） | **脏数据** |
| departments | **26**（声明 7)—— 含 round4-2bde1693、round4-bbdf415a、round4-47fb5845 等测试部门 | **脏数据** |
| categories | 3(CSGL→CSGL-GGSS→CSGL-GGSS-LD 路灯故障） | OK，但远低于真实 12345 诉求分类规模 |
| tickets | **1**（演示 QTDEMO000000000001)+ **大量 pytest 残留**("测试三态确认不修改状态 3ef16ad9"、"测试办件助手审计 0d4fdf28"、"测试 AI 审计链路"、道路施工噪声持续到深夜 ×2 等） | **脏数据** |
| work_orders | 1 | OK |
| kb_documents | 14（与 ROUND-3 报告一致） | OK |
| kb_chunks | 27（与 ROUND-3 报告一致） | OK |
| ai_usage_logs | 5(2×policy_rag + 2×semantic_cache + 1×embedding_query),total_tokens 22~2419,cost 0.000011~0.019 RMB | **真实** |
| ai_suggestions | 0 | 待触发 |
| audit_logs | 12（包含 ai_case_advice、login、view_sensitive_ticket) | OK |
| notifications | 0 | 空，未触发业务 |
| appeals / ticket_feedbacks / follow_up_tasks | 0 | 空，未触发业务 |
| sla_policies | **0** | **空表，SLA 实际走 categories.accept_sla_minutes 内嵌字段** |

### 2.3 API 实测

通过 `openapi.json` 实测到 **101 条路由**，全部位于 `/api/v1/*` 前缀下。**README 与 ENGINEERING 中写的 `/api/auth/login` 等路径是错的**（少了 `/v1`)。

关键路径实测：

| 端点 | 结果 |
|---|---|
| `POST /api/v1/auth/login` | 4 个演示账号全部登录成功，返回 JWT |
| `GET /api/v1/auth/me` | 正确返回 user_id、role、department_id |
| `GET /api/v1/tickets` | RBAC 下推正常：citizen 看本人（1 条）、dept 看本部门（1 条）、agent 看协调范围（1 条）、admin 看全部（多条含测试残留） |
| `POST /api/v1/orchestrator/chat` | 4 条路由全部工作：`policy_rag`（带真实 citations)、`ticket_intake`、`out_of_scope`、`ticket_progress` |
| `POST /api/v1/ai/tickets/{id}/case-advice` | agent 调用返回真实 DeepSeek 建议（advisory_only=true、provider=deepseek);**citizen 调用被 403 拦截** |
| `GET /api/v1/admin/audit-logs` | 返回真实审计记录（ai_case_advice、login、view_sensitive_ticket) |
| `GET /api/v1/admin/ai-usage/stats` | 返回真实统计：total_calls=15, total_tokens=5957, total_cost_rmb=0.0401, by_route 分布正确 |

### 2.4 测试套件实测

| 测试 | 命令 | 结果 |
|---|---|---|
| 后端 pytest | `docker compose exec -T backend pytest -q` | **80/80 passed**(44.79s) |
| 前端 vitest | `cd frontend; npx vitest run` | **17/17 passed**(52.63s,11 个测试文件） |
| Alembic 当前 | `alembic current` | `0018_kb_issuing_authority (head)` |
| Alembic 历史 | `alembic history` | 0001~0018 完整链路 |
| Playwright E2E | 本轮未重跑（报告声明 96/96,需 20.7 分钟） | **未实测** |

---

## 三、被验证和被推翻的历史结论

### 3.1 被实测验证为真的结论

| 历史结论 | 验证结果 |
|---|---|
| 4 角色 RBAC(citizen/agent/department_staff/admin) | ✅ 真实，`authorization.py` 集中管控，前端路由守卫 + 后端 SQL 下推双层 |
| 工单状态机 `pending→accepted→assigned→processing→resolved→closed` | ✅ 真实，`TRANSITIONS` 字典集中定义，非法转换返回 `INVALID_STATUS_TRANSITION` |
| 乐观锁 version 并发控制 | ✅ 真实，version 不匹配返回 `409 VERSION_CONFLICT` |
| Orchestrator 10 条路由 | ✅ 实测 4 条主路由（policy_rag/ticket_intake/out_of_scope/ticket_progress）工作 |
| DeepSeek 真实 LLM 调用 + token 计费 | ✅ 真实，`ai_usage_logs` 有 provider=deepseek、total_tokens=136~2419、cost=0.000272~0.019 RMB |
| advisory_only 边界 | ✅ 真实，AI 不调用状态变更接口；citizen 调 case-advice 返回 403 |
| 审计链路 | ✅ 真实，`audit_logs` 记录 ai_case_advice/login/view_sensitive_ticket，含 request_id |
| 降级机制（llm_unavailable/embedding_fallback/budget_exceeded) | ✅ 声明（本轮未实测三种降级路径） |
| request_id 全链路 | ✅ 真实，`X-Request-ID` 请求头 + `audit_logs.request_id` + `ai_usage_logs.request_id` |
| 后端 80 pytest / 前端 17 vitest / Alembic 0018 | ✅ 实测一致 |

### 3.2 被实测推翻或部分推翻的结论

| 历史结论 | 实测证据 | 推翻程度 |
|---|---|---|
| README：测试命令中的 API 路径是 `/api/auth/login` | 实测真实路径是 `/api/v1/auth/login` | **完全推翻** —— 文档路径缺 `/v1` |
| README:demo_reset 后 tickets=1 | 实测 tickets 表多条 pytest/e2e 残留，admin 运营总览显示 **57 工单 / 45 待受理** | **完全推翻** —— demo_reset 清理不完整 |
| README:demo_reset 后 departments=7 | 实测 departments=26，含 round4-* 多个测试部门 | **完全推翻** |
| README:demo_reset 后 users=4 | 实测 users 表有 citizen_True_*、agent_True_*、r2_citizen_*、managed_99bc034c 等 10+ 测试残留账号 | **完全推翻** |
| ENGINEERING:`sla_policies` 表用于 SLA 策略 | 实测 `sla_policies` 表为 **0 行**;SLA 实际由 `categories.accept_sla_minutes` + `categories.resolve_sla_minutes` 内嵌提供 | **部分推翻** —— 双轨实现，但 sla_policies 表空 |
| PRODUCT：状态机走 `pending→accepted→...` | 实测代码用英文状态，但 `tickets.status` 列 default 是中文 `'待受理'` | **不一致** —— default 值与代码状态机不一致 |
| PRODUCT:citizen 可"复核办结（close)" | 实测 `require_transition` 不给 citizen 任何 transition 权限；close 走 `submit_feedback(rating=satisfied)` 分支 | **表述偏差** —— 实质通过 feedback 办结，不是直接 close |

### 3.3 本轮新发现的问题

#### P0 — 权限校验顺序 Bug

`backend/app/services/ticket_service.py:194`(`_transition`)**先校验 version 再校验 require_transition**:

```python
def _transition(self, ticket_id, action, version, ...):
    ticket = self.get(ticket_id)
    if ticket.version != version:           # ← 先 version
        raise VersionConflict()
    try:
        AuthorizationPolicy.require_transition(principal, action, ticket)  # ← 后权限
    except PermissionDenied:
        ...
```

**后果**:
- 非授权用户传入错误 version → 收到 `409 VERSION_CONFLICT`
- 非授权用户传入正确 version → 收到 `403 PERMISSION_DENIED`
- **攻击者可通过错误信息差异枚举任意工单的当前 version 号**,orchestrating 后续 CSRF/竞态攻击
- 权限拒绝的语义被 version 错误掩盖，不符合"权限先于资源"的安全原则

**正确做法**：先 `require_transition`，再校验 `version`。

#### P1 — demo_reset 清理不完整（脏数据）

实测证据：

| 表 | 脏数据示例 | 来源 |
|---|---|---|
| users | `citizen_True_f3a6e7be_0/1`、`agent_True_f3a6e7be_2`、`department_staff_True_*`、`admin_True_*`、`citizen_False_*`、`r2_citizen_3aca6a95`、`r2_agent_3aca6a95`、`managed_99bc034c` | pytest + Round2/4 e2e |
| departments | `round4-2bde1693`、`round4-bbdf415a`、`round4-47fb5845`（标"第四轮测试部门") | Round4 e2e |
| tickets | "测试三态确认不修改状态 3ef16ad9"、"测试办件助手审计 0d4fdf28"、"测试 AI 审计链路"、"道路施工噪声持续到深夜"×2 | pytest |
| 运营总览 | 显示 57 工单 / 45 待受理（非声明的 1 工单） | 同上 |

**后果**：演示时管理员/坐席会看到"测试三态确认"等明显是测试残留的工单，**直接破坏演示可信度**。

#### P1 — 文档与代码不一致

| 项 | 文档 | 代码/实测 |
|---|---|---|
| API 路径 | `/api/auth/login` | `/api/v1/auth/login` |
| SLA 策略 | `sla_policies` 表 | 空表，实际走 `categories.accept_sla_minutes` |
| 状态机 | 英文 pending/accepted/... | 代码英文，但 `tickets.status` default 是中文 `'待受理'` |
| citizen 办结 | "市民确认满意 → close" | 走 `submit_feedback(rating=satisfied)` 分支 |

#### P1 — 状态机公民路径有歧义

`TRANSITIONS` 中 `resolved → closed` 只能通过 action=`close` 触发，但 `require_transition` 不给 citizen `close` 权限。citizen 的实际办结路径是 `submit_feedback(rating=satisfied)` 直接改 status。这是**两条状态变更路径并存**，但 PRODUCT.md 只描述了一条。

#### P2 — `sla_policies` 表死代码

- 表存在（Alembic 0010 创建）
- 后端有 `/api/v1/admin/sla-policies` CRUD 端点
- 但表为 0 行，且 `ticket_service.accept` 不读它，直接读 `categories.accept_sla_minutes`
- **要么删除表和端点，要么真正接入**

#### P2 — 前端本地存储命名

- token 存于 `sessionStorage.tingting_access_token` —— OK
- 但 `sessionStorage` 意味着**关闭标签页即登出**，用户体验略差，建议改为 `localStorage` + 显式登出按钮

#### P2 — 大量重复构建产物

- `frontend/vite.config.{ts,js,d.ts}` ×3
- `frontend/playwright.config.{ts,js,d.ts}` ×3
- `frontend/test-results/` 99M
- 根 `node_modules/` 2 个包
- `models/` 8 个 Rasa tar.gz 322M

---

## 四、完整业务闭环评价

### 4.1 已验证可用的业务闭环

```
市民(citizen)
  ├─ 政策咨询 → Orchestrator.policy_rag → DeepSeek + citations → 不建单
  ├─ 诉求登记 → Orchestrator.ticket_intake → 草稿 → 人工确认 → POST /tickets
  └─ 进度查询 → Orchestrator.ticket_progress → DB 查询
        ↓
坐席(agent)
  ├─ 受理/拒绝 → POST /tickets/{id}/accept|reject (pending→accepted|rejected)
  ├─ 派发 → POST /tickets/{id}/assign (accepted→assigned)
  ├─ AI 办件助手 → POST /ai/tickets/{id}/case-advice (advisory only)
  └─ 复核办结 → POST /tickets/{id}/review-resolve
        ↓
部门(department_staff)
  ├─ 开始处理 → POST /tickets/{id}/process (assigned→processing)
  ├─ 添加进展 → POST /tickets/{id}/note (processing→processing)
  ├─ 提交结果 → POST /tickets/{id}/resolve (processing→resolved)
  └─ 主协办 → POST /tickets/{id}/work-orders (primary/support/review)
        ↓
市民(citizen)
  ├─ 评价 → POST /tickets/{id}/feedback
  │   ├─ satisfied/mostly_satisfied → 直接 closed
  │   └─ dissatisfied → 留在 resolved, 不自动重开
  └─ 申诉 → POST /tickets/{id}/appeals → submitted
        ↓
管理员(admin)
  ├─ 申诉审核 → POST /appeals/{id}/review (approved→reprocess / rejected)
  ├─ 代办结 → POST /tickets/{id}/close
  ├─ 审计查看 → /admin/audit-logs
  ├─ AI 用量 → /admin/ai-usage/stats|logs
  └─ 用户/部门/分类管理 → /admin/users|departments|categories
        ↓
后台 worker
  ├─ SLA 临期扫描 → notification_outbox → notifications (in_app)
  ├─ 通知重试(指数退避,最多 max_retries)
  └─ 登录限流记录清理
```

**结论**：闭环真实存在，但 **SLA 通知、申诉、回访、评价** 因数据库为 0 行，**本次实测未实际触发**。

### 4.2 闭环薄弱环节

| 环节 | 状态 | 备注 |
|---|---|---|
| 工单创建 → 受理 → 派发 → 处理 → 提交 | ✅ 实测可用 | 状态机正确 |
| 提交结果 → 办结 | ⚠️ 声明可用，本轮未触发 resolved→closed 实际转换 | 需先造一条 resolved 工单 |
| 办结 → 评价 | ⚠️ `ticket_feedbacks` 0 行 | 未实测 |
| 评价不满意 → 申诉 → 重办 | ⚠️ `appeals` 0 行 | 未实测 |
| SLA 临期通知 | ⚠️ `notifications` 0 行 | worker 在跑，但 accept_due_at/resolve_due_at 未到期 |
| 电话回访 | ⚠️ `follow_up_tasks` 0 行 | 未实测 |
| 主协办 work_order | ✅ 数据存在（1 条） | 本轮未实测协办流转 |
| AI 建议 → 三态确认 | ✅ 声明可用；`ai_suggestions` 0 行，未触发人工 review | 需手动调 case-advice 然后 review |

---

## 五、同类平台对标与差距

### 5.1 12345 政务热线核心特征（来自川/浙/沪/豫等省级管理办法)

| 特征 | 12345 实际 | 倾听助手现状 | 差距 |
|---|---|---|---|
| 受理时限 | 24 小时派单，承办单位 1 个工作日签收 | ✅ `accept_due_at` SLA 到期扫描 | **已对齐** |
| 退回时限 | 签收后 2~3 小时退回（超期视为超期办理） | ✅ `return_to_department` + `returned` 状态 | **已对齐** |
| 办理时限 | 咨询 3d / 求助 7d / 投诉举报 15d | ✅ categories 内嵌 accept/resolve_sla_minutes | **基本对齐**（但目前只 3 个分类） |
| 延期申请 | 一般 1 次，不超过原时限 | ❌ 未实现 | **缺失** |
| 主协办 | 明确主办/协办，主办统一答复 | ✅ `work_orders.task_type` (primary/support/review) | **已对齐** |
| 首接责任制 | 不得推诿，首接单位负责到底 | ⚠️ 通过 `assigned_department_id` 实现，但**未禁止再次转派** | **部分对齐** |
| 疑难会商 | 编办+司法+多部门会商确定责任 | ❌ 未实现 | **缺失**（超出 MVP 范围） |
| 谁承办谁答复 | 承办单位答复诉求人 | ✅ `resolution_summary` + `public_reply` | **已对齐** |
| 回访评价 | 电话回访 + 满意度评价 | ✅ `follow_up_tasks` + `ticket_feedbacks` | **声明对齐，未实测** |
| 申诉重办 | 不满意可申诉，重办工单 | ✅ `appeals` + `processing`(reprocess) | **声明对齐，未实测** |
| 三方通话 | 诉求人 + 坐席 + 业务部门 | ❌ 未实现 | **缺失**（超出 MVP 范围） |
| 紧急事项快速通道 | 大面积停水停电、自然灾害直转应急 | ❌ 未实现（有 priority=urgent 但无独立通道） | **部分对齐** |
| 特殊群体 | 纪检监察直转 | ❌ 未实现 | **缺失**（超出 MVP 范围） |

### 5.2 成熟客服工单平台（Zendesk / ServiceNow / Freshdesk)

| 能力 | 商业平台 | 倾听助手 | 差距 |
|---|---|---|---|
| 智能分类 | 主题/情绪/实体识别，自动路由 | ✅ Orchestrator 分层路由（规则→OOD→LLM) | **已对齐** |
| SLA 多层 | 客户级/服务级/内部组级 SLA | ⚠️ 只有分类级 SLA | **简化** |
| 父子工单 | 支持 | ❌ 未实现（有 work_order 但非父子工单） | **缺失** |
| 工单合并 | 重复工单合并 | ❌ 未实现 | **缺失** |
| 统一工作台 | 全渠道（email/chat/phone/社交） | ⚠️ 仅 Web + Rasa 对话 | **简化** |
| 触发器/宏 | 自定义自动化规则 | ❌ 未实现（规则在代码里硬编码） | **缺失** |
| 满意度预测 | AI 预测 CSAT | ❌ 未实现 | **缺失** |
| 知识库推荐 | 根据工单内容自动推荐 KB | ✅ `KbRagPanel` + policy_rag | **已对齐** |
| 情感分析 | 内建 | ❌ 未实现 | **缺失** |
| 富文本回复 | 完整编辑器 + 模板 | ⚠️ 简单 textarea | **简化** |
| 移动端 | 完整 App | ❌ 未实现 | **缺失**（超出范围） |

### 5.3 政务 AI 大模型指引(2025 中央网信办 / 发改委)

| 要求 | 倾听助手 | 对齐 |
|---|---|---|
| 辅助型定位，不自动决策 | ✅ `advisory_only=true` 全程 | **完全对齐** |
| 内容审核 + 人工复核 | ✅ 三态确认（accept/reject/modify) | **完全对齐** |
| 幻觉防范 | ✅ RAG citations 强制 + `no_evidence` 兜底 | **完全对齐** |
| 日志审计 | ✅ `ai_usage_logs` 10 capability 全记录 | **完全对齐** |
| 风险提示 | ✅ IntelligencePage 顶部"人机协同边界"提示 | **完全对齐** |
| 内容标识 | ⚠️ AI 输出有 `advisory_only` 标记但 UI 展示可更显眼 | **基本对齐** |
| 代答/拒答机制 | ✅ `out_of_scope` 固定回复 | **完全对齐** |
| 对抗攻击检测 | ⚠️ Guard 有输入长度/限流/去重，但无显式 prompt injection 检测 | **部分对齐** |
| 分类分级治理 | ✅ KB 三态可见性（PUBLIC/DEPARTMENT/INTERNAL) | **完全对齐** |

### 5.4 深圳"深小i" / 上海"智慧好办" 对齐情况

| 能力 | 倾听助手 |
|---|---|
| 智能问答 + 办事引导 | ✅ policy_rag + service_guide |
| 智能预审 | ✅ pre_review capability |
| 边聊边办 | ✅ Orchestrator + ticket_intake 草稿 |
| 表单智能预填 | ✅ ticket_intake LLM 提取动态字段 |
| 材料智能核验 | ❌ 未实现（超出范围） |
| 远程虚拟窗口 | ❌ 未实现（超出范围） |
| 智能分办 | ✅ ticket_advice 责任部门建议 |
| 政策找人 | ❌ 未实现（超出范围） |

**整体评价**：倾听助手在 **AI 辅助 + 人工兜底 + 审计追踪** 这条线上**对齐度非常高**；在 **工单协同 + SLA + 申诉** 这条线上**对齐度中上**；在 **全渠道 + 移动端 + 三方通话 + 智能分办自动化** 这条线上**明确做了边界裁剪**。

---

## 六、P0 / P1 / P2 问题清单

### P0 — 必须修复（影响业务正确性 / 安全 / 求职可信度）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| P0-1 | 权限校验顺序颠倒 | `backend/app/services/ticket_service.py:194` | 非授权用户可通过错误信息枚举 version；权限语义被掩盖 |
| P0-2 | demo_reset 清理不完整 | `backend/scripts/demo_reset.py` | 演示时残留 pytest/e2e 脏数据（用户/部门/工单）,**直接破坏演示可信度** |
| P0-3 | 文档 API 路径错误 | `README.md` / `ENGINEERING.md` | `/api/auth/login` → `/api/v1/auth/login`，误导使用者 |

### P1 — 建议修复（影响工程质量 / 演示体验）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| P1-1 | `sla_policies` 表死代码 | `backend/app/api/sla_policies.py` + migrations | 端点存在但表空，逻辑实际走 `categories.*_sla_minutes` |
| P1-2 | `tickets.status` default 是中文 | `backend/app/models.py` | 与代码英文状态机不一致 |
| P1-3 | citizen 办结路径在 PRODUCT 中描述错误 | `PRODUCT.md` | 实际走 `submit_feedback` 而非 `close` |
| P1-4 | 状态机双路径（transition + feedback_transition) | `ticket_service.py` | 可合并简化 |
| P1-5 | 前端 token 存 sessionStorage | `frontend/src/api/client.ts` | 关闭标签页即登出 |
| P1-6 | 申诉/评价/回访全为 0 行 | DB 实测 | 声明功能存在，但**端到端从未真实跑通过**（至少仓库当前状态） |
| P1-7 | 前端大量废弃文件 | `frontend/vite.config.{js,d.ts}`、`frontend/playwright.config.{js,d.ts}`、`frontend/e2e-result-*`、`frontend/test-results/`(99M) | 仓库体积 |
| P1-8 | Rasa 模型多版本并存 | `models/*.tar.gz` ×8 | 322M 冗余 |
| P1-9 | 根 `node_modules/` 误装残留 | 根目录 | 2 个包，应删 |
| P1-10 | `.git` 空目录 | 根目录 | 版本历史完全丢失，应重新 init |

### P2 — 可选优化（求职加分项）

| # | 问题 | 说明 |
|---|---|---|
| P2-1 | 延期申请机制 | 12345 有，倾听助手缺失 |
| P2-2 | 工单合并 / 父子工单 | Zendesk 有 |
| P2-3 | 情感分析 | Zendesk 有 |
| P2-4 | 触发器/宏自定义 | 目前规则硬编码 |
| P2-5 | 富文本回复编辑器 | 目前是 textarea |
| P2-6 | 三方通话 | 12345 核心特性，超出 MVP |
| P2-7 | 移动端 | 超出范围 |
| P2-8 | 紧急事项快速通道 | 目前只有 priority=urgent 字段 |
| P2-9 | prompt injection 检测 | Guard 增强 |
| P2-10 | UI 组件复用（antd  deprecated 警告） | vitest 输出多条 antd deprecation warning |

---

## 七、必须修复 / 建议优化 / 明确不做

### 7.1 必须修复（本轮或下一轮）

1. **P0-1**: 调整 `_transition` 权限校验顺序 —— 先 `require_transition`，再校验 `version`。
2. **P0-2**: 完善 `demo_reset.py` —— 清理所有 `*_True_*`、`*_False_*`、`r2_*`、`managed_*`、`round4-*` 测试残留；添加 db CHECK 约束或 unique index 防止再次写入。
3. **P0-3**: 修正 README/ENGINEERING 中所有 `/api/*` → `/api/v1/*`。
4. **P1-2**: 把 `tickets.status` default 改为英文 `'pending'`，并写一个迁移把现有中文值映射回英文。
5. **P1-6**: 端到端跑一次完整闭环：受理 → 派发 → 处理 → resolve → 市民 satisfied → closed → 提交 appeal → admin review → reprocess，确保 notifications/appeals/ticket_feedbacks/follow_up_tasks 至少有 1 条真实数据。

### 7.2 建议优化（下一轮）

1. **P1-1**: 删除 `sla_policies` 表 + 端点（或改为读取它） —— 只保留一种 SLA 来源。
2. **P1-3**: 修正 PRODUCT.md 对 citizen 办结路径的描述。
3. **P1-5**: token 从 sessionStorage 改为 localStorage + 显式登出。
4. **P1-7 / P1-8 / P1-9 / P1-10**: 清理仓库冗余，`.git` 重新 init 并提交当前快照。
5. **P2-1**: 增加"延期申请"功能 —— 承办单位可在 resolve_due_at 前 24h 申请延期 1 次。
6. **P2-10**: 升级 antd 到最新 minor，消除 deprecation warning。

### 7.3 明确不做（保持求职作品合理范围）

1. 三方通话、视频帮办、远程虚拟窗口
2. 移动端 App / 小程序
3. 多租户 SaaS 化
4. K8s、微服务拆分、服务网格
5. 模型训练 / 微调 / RLHF
6. 真实短信、真实 OIDC、真实地图、真实政务平台接入（保持适配器 disabled)
7. 疑难会商工作流（编办+司法+多部门）
8. 纪检监察直转
9. 完整 BPMN 引擎（Camunda / Flowable)
10. 知识图谱（Neo4j)

---

## 八、页面级 UI/UX 优化清单

### 8.1 整体信息架构

| 页面 | 现状 | 问题 | 建议 |
|---|---|---|---|
| 顶部导航 | 仅 logo + 用户名 | 无面包屑、无全局搜索、无消息中心快捷入口 | 加 breadcrumb + 全局 ticket_id 搜索框 + notification 铃铛 |
| 左侧菜单 | 按角色分组清晰 | citizen 菜单 6 项略显冗余（智能对话/政策咨询/我的工单/智能诉求检查/通知中心/回访与申诉） | 合并"智能对话"与"政策咨询";"智能诉求检查"重命名为"提交前检查"更易懂 |
| 路由 | `/citizen/*` `/agent/*` `/department/*` `/admin/*` 角色前缀 | URL 长但清晰 | 保持 |

### 8.2 关键页面问题（基于 80 张截图）

#### Landing 页（未登录）
- **问题**：纯文本 + 单按钮，无产品截图、无特性介绍、无演示入口说明
- **建议**：加三栏特性卡片（政策 RAG / 工单闭环 / AI 审计） + "查看演示账号"折叠面板

#### Chat 页（citizen)
- **现状**：对话流 + 右侧工单草稿面板
- **问题**:① 消息气泡无时间戳；② 引用 citations 展示弱（仅小号灰色）;③ 无"这个回答有帮助吗"反馈
- **建议**：加消息时间、引用卡片化（标题/文号/发文机关）、加 thumbs up/down

#### 工单列表页（agent/admin/dept)
- **现状**：筛选器 7 个 + 表格 8 列
- **问题**:① 筛选器太多，首屏占 1/3;② 表格"诉求摘要"列宽过窄被截断；③ "SLA 状态"只有"时限正常"，无视觉分级
- **建议**:① 筛选器收到抽屉，首屏只留搜索框 + 状态 Tab;② 摘要列加 tooltip;③ SLA 状态用红黄绿三色（临期<24h 黄 / 已超时红 / 正常绿）

#### 工单详情页
- **现状**：左信息 + 右操作 + 下时间线
- **问题**:① 时间线"系统"和"人工"操作混杂；② AI 建议面板折叠太深；③ 操作按钮（受理/拒绝/派发）放右上角，与小屏不友好
- **建议**:① 时间线加 filter（全部/状态变更/备注/AI);② AI 建议作为 Tab 平行于"处理记录";③ 操作按钮改底部 sticky 操作栏

#### Admin Dashboard
- **现状**:5 个统计卡 + 2 个图表 + 最近工单
- **问题**:① 统计卡无环比；② 图表无下钻；③ "即将超时 45"是大数字但无解释
- **建议**:① 加"较昨日 +N";② 点击饼图扇区下钻到工单列表；③ 数字加 tooltip 说明计算口径

#### Admin AI 用量页
- **现状**:4 个统计卡 + 分布图 + 明细表
- **问题**:① 无 budget 使用情况；② 无降级率告警；③ session_id 筛选器位置不明显
- **建议**:① 加"今日 budget 使用进度条";② 降级率超 10% 红色告警；③ session_id 提到表头

#### KB 管理页
- **现状**：三 Tab（文档管理/上传新文档/直接录入/反馈与无答案）
- **问题**:① 状态标签太多（DRAFT/REVIEWING/PUBLISHED/REJECTED/WITHDRAWN/EXPIRED/PARSE_FAILED)UI 无分组；② 操作列按钮 5 个（详情/下线/标记失效/重建索引），拥挤
- **建议**:① 状态分组成"草稿中/审核中/已发布/已下架"4 大类；② 操作列收到 Dropdown

#### 智能辅助工作台（Intelligence)
- **现状**：顶部"人机协同边界"提示 + 按工单生成建议 + 近 30 天热点聚类
- **问题**:① "未分类诉求·社区服务中心 42 件"无跳转；② 热点聚类只看工单 ID 列表，无主题词
- **建议**:① 聚类卡片可点击下钻；② 加关键词云

#### 申诉与回访（Aftercare)
- **现状**:Tab 切换
- **问题**:0 数据时无 Empty 状态引导
- **建议**：加 Empty 插画 + "如何产生申诉/回访数据"说明

### 8.3 通用 UI 问题

| 问题 | 建议 |
|---|---|
| antd `message`/`direction` 多处 deprecated 警告 | 升级到 antd 最新 minor 并按警告改属性 |
| 加载状态不统一 | 统一用 `<PageLoading/>` 骨架屏 |
| 错误状态文案不统一 | 统一用 `<ErrorState/>` 并加"重试"按钮 |
| 空状态无引导 | 每个列表页加 Empty 插画 + 操作引导 |
| 移动端未做响应式 | 桌面端为主，但至少在 1280px 下不水平滚动 |

---

## 九、最多两轮的最终优化方案

### Round 4 — 业务正确性收口（1~2 天）

**目标**：修复 P0 + P1 关键问题，让演示无脏数据、文档与代码一致。

| 任务 | 优先级 | 验收 |
|---|---|---|
| 修复 `_transition` 权限顺序 | P0 | 新增 pytest：非授权用户先收到 403（无论 version 对错） |
| 完善 demo_reset 清理规则 | P0 | reset 后 `users=4, departments=7, tickets=1`,admin 总览显示 1 工单 |
| 修正 README/ENGINEERING 的 API 路径 | P0 | 全文 grep `/api/` 都改为 `/api/v1/` |
| `tickets.status` default 改英文 | P1 | Alembic 迁移 + 现有中文值映射 |
| 删除或接入 sla_policies | P1 | 二选一，保持单一 SLA 来源 |
| 端到端跑一次完整闭环 | P1 | 产出 notifications/appeals/ticket_feedbacks 各 ≥1 条 |
| 清理 frontend 冗余配置文件 | P1 | 删除 `vite.config.{js,d.ts}`、`playwright.config.{js,d.ts}` |
| 清理仓库残留 | P1 | 删 `node_modules/`、`test-results/`、`e2e-result-*`、`models/` 旧版本 |
| `.git` 重新 init | P1 | `git init && git add . && git commit` |

### Round 5 — UI/UX 打磨 + 求职亮点（1~2 天）

**目标**：演示时给人"接近上线产品"的感觉。

| 任务 | 优先级 | 验收 |
|---|---|---|
| 工单列表页筛选器收抽屉 | P1 | 首屏只看到搜索框 + 状态 Tab |
| 工单详情页操作栏 sticky | P1 | 滚动时操作按钮始终在底部 |
| Admin Dashboard 统计卡加环比 | P1 | 显示"较昨日 +N" |
| KB 状态分组 + 操作收 Dropdown | P1 | 状态 4 大类，操作列 1 个按钮 |
| Empty 状态统一 | P2 | 每个列表页都有 Empty + 引导 |
| 升级 antd 消除 deprecation | P2 | vitest 无 antd warning |
| Landing 页重做 | P2 | 三栏特性卡 + 演示账号面板 |
| 补 token 持久化 | P1 | localStorage + 显式登出 |
| PRODUCT.md 修正 citizen 办结路径 | P1 | 描述与代码一致 |
| 移动端基本响应式 | P2 | 1280px 无水平滚动 |

**明确不做**（第三轮也不做）：三方通话、移动端 App、多租户、K8s、模型微调、真实短信/OIDC、疑难会商、纪检监察直转。

---

## 十、最终产品功能边界

### 10.1 核心定位（一句话）

> **面向市民诉求受理与跨部门协同办理的政务服务演示平台**，以"对话式入口 + 可信状态机 + advisory AI + 全程审计"为核心，**保持求职作品的合理范围，不追求真实政务生产系统的高可用与全渠道**。

### 10.2 业务边界

**做**:
- 4 角色（citizen/agent/department_staff/admin)
- 工单全生命周期（提交→受理→派发→处理→办结→评价→申诉→重办）
- 主协办 + 复核 work_order
- SLA（分类级）+ 临期通知 + 超时上报
- 政策 RAG(citations + no_evidence 兜底）
- AI 办件助手（advisory only，三态人工确认）
- KB 管理（PUBLIC/DEPARTMENT/INTERNAL 三态可见性）
- AI 用量审计（10 capability + token + cost + degrade)
- 审计日志（request_id 全链路）
- 降级机制（llm_unavailable/embedding_fallback/budget_exceeded)

**不做**:
- 三方通话 / 视频帮办 / 远程虚拟窗口
- 移动端 App / 小程序
- 多租户 SaaS / K8s / 微服务
- 模型训练 / 微调
- 真实短信 / OIDC / 地图 / 政务平台接入
- 疑难会商 / 纪检监察直转
- 知识图谱 / 父子工单 / 工单合并 / 富文本编辑器
- 完整 BPMN

### 10.3 数据边界

- 所有数据为演示种子数据
- 默认演示密码 `tingting-seed-demo-2026` 仅本地用
- AI API Key 由用户自配（DeepSeek + SiliconFlow)
- 外部适配器默认 disabled，未配置返回"未配置"，不伪造成功

---

## 十一、简历技术亮点（可直接用)

### 业务亮点

1. **可信工单状态机**：基于 `TRANSITIONS` 字典 + 乐观锁 version + 审计留痕，覆盖 6 状态 × 7 动作，非法转换返回 409，并发安全。
2. **四角色 RBAC**:`AuthorizationPolicy` 单一真相源，`can_view` + `require_transition` + `apply_query_scope` 三层管控，SQL 下推保证列表与详情一致。
3. **跨部门协同**:`work_orders` 支持 primary/support/review 三态，覆盖退回、转派、提交、汇总全流程。

### AI 亮点

4. **可信 RAG**:pgvector 语义检索 + 关键词回退（pg_trgm)，强制 citations 四要素（title/doc_number/issuing_authority/excerpt)，无证据返回 `no_evidence` 不编造。
5. **Advisory-only AI 边界**:AI 不调用状态变更接口，所有建议三态人工确认（accept/reject/modify)，与工单状态解耦。
6. **10 种 AI capability 全程审计**:`ai_usage_logs` 记录 provider/model/token/latency/cost/degrade_reason/session_id/request_id，管理员可筛选会话。
7. **分层 Orchestrator**：规则 → OOD → LLM 三层路由，支持 10 条路由（policy_rag/service_guide/ticket_intake/ticket_progress/human_handoff/out_of_scope 等）。
8. **降级机制**：三种 `degrade_reason`(llm_unavailable/embedding_fallback/budget_exceeded）统一标记，管理员可区分真实调用与降级调用。

### 工程亮点

9. **request_id 全链路追踪**:`X-Request-ID` 中间件 + contextvar + audit_logs + ai_usage_logs + integration_events 五处贯穿。
10. **可靠通知**:outbox 模式 + 6 字段幂等键 + 指数退避重试 + worker 异步投递。
11. **Alembic 18 个迁移**：可升降级，`alembic check` 无 diff。
12. **测试覆盖**：后端 pytest 80 + 前端 vitest 17 + Playwright 96 E2E。
13. **Docker Compose 8 服务一键启动**:frontend/backend/postgres/pgvector/minio/rasa/action_server/duckling/worker。
14. **CI 5 个 job**:static-checks/frontend-tests/backend-tests/e2e-three-browsers/docker-integration + action-tests + rasa-regression + dependency-security。

---

## 十二、危险面试追问（必须能答）

### Q1: "你的权限校验是怎么做的？"

**A**: 三层。
- `Principal`(frozen dataclass）携带 kind/user_id/role/department_id。
- `AuthorizationPolicy.can_view` 控制数据可见性（citizen 看本人、dept 看本部门+协办、agent 看非 closed/rejected、admin 看全部）。
- `require_transition` 按"角色 × action × 部门归属"三元组校验动作权限。
- `apply_query_scope` 把同一套规则下推到 SQLAlchemy WHERE 子句，保证列表与详情权限一致。
- 前端路由守卫只是 UX，后端在中间件 + service 层双重校验。

**追问**: 如果攻击者直接调 API 不带前端？
**A**: 后端中间件从 JWT 解出 Principal,service 层每个方法第一行就 `require_view` 或 `require_transition`，与前端解耦。

**追问**: 权限校验和 version 校验的顺序？
**A**: **(本轮发现 P0-1 Bug)** 当前是先 version 再权限，存在通过错误信息枚举 version 的风险。正确做法是先 `require_transition` 再校验 version。

### Q2: "AI 幻觉怎么防？"

**A**: 三层。
- **检索层**:RAG 强制 citations 四要素，无证据返回 `no_evidence`，不编造。
- **生成层**:prompt 中要求"仅基于给定 chunks 回答"，并返回 `citation_index` 数组。
- **业务层**:policy_rag 找到答案后**不自动建单**，由市民显式确认；service_guide 退化为"仅检索原文 + 引用"。
- **监督层**：所有 AI 调用记录 `ai_usage_logs`，管理员可审计 prompt_version + provider + tokens。

### Q3: "AI 会不会越权？"

**A**: 不会。
- AI 模块只输出建议，`advisory_only=true`，不调用 `accept/assign/resolve/close` 等状态变更接口。
- 建议落 `ai_suggestions` 表，与 `tickets` 表解耦。
- 三态人工确认（accept/reject/modify）由工作人员触发，仍走原有权限校验。
- AI 调用本身也有角色限制（citizen 不能调 case-advice,403)。

### Q4: "工单并发了怎么办？"

**A**:
- 乐观锁 version，每次 transition 都 `WHERE version=?`，不匹配返回 409。
- 业务层捕获 `VERSION_CONFLICT` 提示前端刷新。
- 不接悲观锁，因为工单操作低频。

### Q5: "幂等怎么做？"

**A**:
- 工单创建：`idempotency_key` 唯一索引，重复返回原单。
- 通知：6 字段幂等键（`event_type:ticket_id:r{handling_round}:{threshold_level}:{occurrence}:{user_id}`)。
- Outbox:worker 异步投递，指数退避最多 max_retries 次。

### Q6: "Rasa 和 Orchestrator 关系？"

**A**:
- Orchestrator 负责**高层路由**(10 条 route)：规则命中（confidence≥0.9)→ Guard 检查 → LLM(OOD/提取/生成）。
- Rasa 只做 NLU（意图识别）+ 槽位 + 表单，不做业务路由。
- Action Server 通过服务令牌调 Backend，不继承用户权限。

### Q7: "你的 SLA 怎么实现？"

**A**:
- 分类级 `accept_sla_minutes` + `resolve_sla_minutes`。
- `accept` 时按优先级（normal/expedited/urgent/major）乘系数（1.0/0.75/0.5/0.25）算 `accept_due_at` 和 `resolve_due_at`。
- worker 每 N 秒扫描临期工单，写 notification_outbox。
- SLA 暂停/恢复通过 `sla_paused_at` 字段。

### Q8: "数据库为什么选 PostgreSQL 不选 ES?"

**A**:
- 单机演示规模（千级工单），不需要 ES。
- pgvector 提供向量检索，避免引入 Qdrant/ES 重型组件。
- pg_trgm 提供关键词回退，保证 embedding 失败时仍能检索。
- 事务 + JSONB + 全文检索 + 向量，一库多用。

### Q9: "你的项目最大不足是什么？"

**A**（诚实回答）:
- **业务覆盖度**：只有 3 个分类，未实现延期申请、工单合并、父子工单、三方通话。
- **演示数据**：当前仓库有 pytest/e2e 残留脏数据，demo_reset 清理不完整（本轮 P0-2)。
- **规模**：未做压测，未验证高并发；登录限流是 DB 共享不是 Redis。
- **AI**：未做 prompt injection 检测，未做敏感性词库。
- **可观测性**：有结构化日志 + request_id，但无 metrics 聚合（Prometheus)、无 tracing(OpenTelemetry)。

### Q10: "你怎么验证 AI 输出可信？"

**A**:
- **引用可信**:citations 必须含 title/doc_number/issuing_authority/excerpt，前端可点击跳转到 KB 原文。
- **token 可信**：所有调用记录 `ai_usage_logs.total_tokens`，管理员可审计；usage_unavailable=true 时不当作 0 处理。
- **降级可信**：三种 degrade_reason 统一标记，前端可区分。
- **会话可信**:session_id 隔离，session1 的槽位不泄漏到 session2。

---

## 十三、是否已经达到高质量求职作品标准

### 结论：**基本达到，但有 3 个关键短板**

| 维度 | 评分 | 说明 |
|---|---|---|
| 业务闭环完整度 | ★★★★☆ | 闭环存在，但申诉/评价/回访/SLA 通知四张表 0 行，**未真实跑通** |
| AI 可信度 | ★★★★★ | 真实 DeepSeek 调用 + token + cost + citations + advisory_only + 降级 |
| 权限安全 | ★★★☆☆ | RBAC 三层管控完整，**但 P0-1 权限顺序 Bug 拉低** |
| 工程质量 | ★★★★☆ | 测试 80+17、Alembic 18、Docker 8、CI 5 job，但仓库卫生差 |
| 演示可信度 | ★★☆☆☆ | **脏数据严重** —— 57 工单 vs 声明 1 工单，演示时暴露 |
| 文档准确性 | ★★★☆☆ | README 总体准确，但 API 路径、citizen 办结路径、SLA 实现细节有偏差 |
| 求职亮点密度 | ★★★★★ | 状态机 + RBAC + RAG + advisory AI + 审计 + 降级 + outbox 幂等，亮点密集 |
| 仓库专业度 | ★★☆☆☆ | .git 空、重复配置、99M 测试产物、322M Rasa 模型冗余 |

### 与"高质量求职作品"的差距

- **P0-1 权限顺序 Bug**：面试官一旦深问权限，就会暴露。
- **脏数据**：截图一发，"57 工单 / 45 待受理"直接穿帮。
- **API 路径错误**:README 是最常被翻的文档，路径错是低级失误。
- **未跑通的 4 张表**：面试问"你的申诉流程能演示吗"，目前答案是"代码有但没跑过"。

**总评**:**修完 P0 三件事（权限顺序、demo_reset、API 路径）+ 跑通 4 张空表，即达到高质量求职作品标准**。

---

## 十四、是否应当停止继续扩展

### 结论：**应当停止业务扩展，进入收口与打磨阶段**

**理由**:

1. **范围已经足够**：状态机 + 4 角色 + RAG + advisory AI + 审计 + 降级 + outbox 幂等 + 主协办，**求职亮点已经密集**，再加功能边际收益递减。
2. **深度不足于广度**：与其加"父子工单/三方通话/工单合并"，不如把现有闭环跑得更稳、把脏数据清干净、把文档改准确。
3. **演示风险**:57 个脏工单、26 个脏部门、10+ 脏账号，任何扩展都会被这些数据拖累。
4. **面试风险**：与其被问"你做了 X 吗"（没做），不如把"你做过的"打磨到无懈可击。
5. **维护成本**:8 服务 + 18 迁移 + 80 测试 + 96 E2E 已经到个人能维护的极限，再扩展难以保持质量。

### 推荐的收口路径（不再加新功能）

| 轮次 | 目标 | 时长 |
|---|---|---|
| Round 4 | 修 P0(权限顺序/demo_reset/API 路径）+ 跑通 4 张空表 + 清仓库 | 1~2 天 |
| Round 5 | UI/UX 打磨 + 文档修正 + 简历亮点提炼 | 1~2 天 |
| 之后 | **停止**，只维护不新增 | — |

---

## 附录 A:实测证据索引

| 证据 | 位置 |
|---|---|
| 后端 pytest 80/80 | `docker compose exec -T backend pytest -q` 实测输出 |
| 前端 vitest 17/17 | `cd frontend; npx vitest run` 实测输出 |
| Alembic 0018 | `docker compose exec -T backend alembic current` |
| 数据库表 29 张 | `psql \dt` |
| ai_usage_logs 5 条真实 token | `SELECT * FROM ai_usage_logs ORDER BY created_at DESC` |
| Orchestrator 4 路由 | curl 实测（policy_rag/ticket_intake/out_of_scope/ticket_progress) |
| AI 权限隔离 | citizen 调 case-advice 返 403 |
| 截图约 80 张 | `E:\program0713\qingtingzhushou\.workbuddy\audit-shots\*.png` |

## 附录 B:联网调研来源

- 《四川省 12345 政务服务便民热线运行管理办法》(2026)
- 《丽水市 12345 政务服务便民热线管理办法》
- 《周口市 12345 政务服务便民热线运行管理细则》
- 《西昌市 12345 政务服务便民热线运行管理暂行办法》
- 《泸州市江阳区 12345 政务服务便民热线运行管理办法》
- 中央网信办、国家发改委《政务领域人工智能大模型部署应用指引》(2025-10)
- 上海市《推进"人工智能+"行动打造"智慧好办"政务服务实施方案》
- 深圳市《深入推进"人工智能+政务服务"工作方案》(20 条)
- Zendesk 官方文档（智能分类/SLA/触发器）
- ServiceNow / Freshdesk / Zoho Desk 官方文档

---

**报告完成时间**:2026-07-21
**审计者**:WorkBuddy
**下一步**:等待用户确认是否进入 Round 4 收口
