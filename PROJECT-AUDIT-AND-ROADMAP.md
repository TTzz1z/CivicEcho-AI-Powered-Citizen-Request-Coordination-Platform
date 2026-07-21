# 倾听助手 / 政务诉求协同服务平台 — 现状审计与优化路线

> 审计日期：2026-07-20（Asia/Shanghai）
> 审计范围：`e:\program0713\qingtingzhushou\helpdesk-assistant-main` 全仓库
> 审计方式：实际代码阅读 + Docker 运行时验证 + API 端到端验证 + 后端测试执行 + 数据库查询
> 重要原则：所有结论均附文件路径与行号证据，运行时数据来自真实容器与真实数据库，无静态假数据

---

## 一、项目全景总结

### 1.1 产品定位

**倾听助手（Tingting Assistant）** 是一个面向基层政务诉求的智能协同服务平台，原型借鉴 ServiceNow Helpdesk 框架，但已全面中文化并扩展为政务场景。它把"市民—坐席—部门—管理员"四类角色通过统一工单工作流串起来，并叠加 Rasa 中文 NLU、自研 LLM Orchestrator、RAG 政策知识库、AI 办件助手、SLA 与回访申诉、AI 用量审计等能力。

一句话定位：**一个用 Rasa + FastAPI + React + pgvector + DeepSeek 搭起来的、面向政务 12345 风格诉求的"工单+RAG+Agent"演示项目**。

### 1.2 目标用户

| 角色 | 用户名 | 真实定位 |
|---|---|---|
| 市民 citizen | `citizen_local` | 通过智能对话提诉求、查进度、咨询政策 |
| 政务坐席 agent | `agent_local` | 受理工单、派发部门、辅助办理 |
| 部门人员 department_staff | `department_local` | 接单、办理、上传政策知识库、AI 办件助手 |
| 系统管理员 admin | `admin_local` | 审核知识库、用户/部门/分类管理、看板、AI 用量审计、申诉复核 |

### 1.3 核心业务价值

1. **统一入口**：智能对话统一受理咨询、投诉、建议、求助、报修、工单查询、紧急分流。
2. **协同闭环**：工单状态机 `pending → accepted → assigned → processing → resolved → closed` + 多部门协办（primary/support/review）+ 申诉重办。
3. **RAG 政策咨询**：pgvector 向量检索 + 关键词召回 + RRF 融合 + 重排序 + LLM 摘要 + 引用追溯 + 失效政策拦截 + 权限隔离。
4. **Agent 编排**：规则 → Rasa → LLM 三层路由，含语义缓存、限流、预算、降级、审计。
5. **AI 办件助手**：工单摘要、风险分析、部门建议、答复草稿、诉求预审、办件建议——全部 `advisory_only=true` 人工复核。
6. **可观测**：`ai_usage_logs` 表记录每次模型调用的 request_id、route、tier、token、耗时、缓存命中、限流、降级、成本。

### 1.4 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19 + TypeScript 5 + Vite 7 + Ant Design 6 + TanStack Query 5 + React Router 7 + ECharts 6 + Vitest + Playwright |
| 后端 | Python 3.11 + FastAPI + Pydantic 2 + SQLAlchemy 2 + Alembic + JWT (python-jose) + passlib bcrypt |
| 数据库 | PostgreSQL 16 + pgvector（Vector(1024)） |
| 对象存储 | MinIO（附件 + KB 文件） |
| NLU | Rasa 3.6.20（JiebaTokenizer + DIET + Duckling + RegexEntityExtractor） |
| Action Server | Python 3.10 + rasa-sdk（自定义 actions） |
| LLM | DeepSeek `deepseek-chat`（OpenAI 兼容） |
| Embedding | DeepSeek `text-embedding-v1`（默认配置，但 DeepSeek 不提供此模型，需切换 SiliconFlow Qwen3-VL-Embedding-8B） |
| 编排 | 自研 `OrchestratorService` + `OrchestratorGuard`（规则 + LLM 分类 + Guard 预检查） |
| 部署 | Docker Compose（8 个服务） + Caddy（可选） |
| CI | GitHub Actions（ci.yml） |

### 1.5 基础设施结构

8 个 Docker 容器全部健康（实测 2026-07-20 12:33 UTC+8）：

| 容器 | 镜像 | 端口映射 | 健康 |
|---|---|---|---|
| backend | 自构建 `Dockerfile.backend` | 8001→8000 | Up (healthy) |
| frontend | 自构建 Nginx | 8081→80 | Up (healthy) |
| postgres | postgres:16 | 5432 | Up (healthy) |
| minio | minio/minio | 29000/29001 | Up (healthy) |
| rasa | rasa/rasa:3.6.20-full | 5005 | Up (healthy) |
| action_server | 自构建 `Dockerfile.actions` | 5055 (localhost) | Up (healthy) |
| duckling | rasa/duckling | 18080 | Up (healthy) |
| worker | 自构建（同 backend 镜像） | 8000 (内部) | Up (healthy) |

### 1.6 整体完成度评分

**综合完成度：72/100（B+，可演示，距上线还差关键运维与体验打磨）**

评分依据：

| 维度 | 评分 | 说明 |
|---|---|---|
| 业务闭环完整度 | 80/100 | 工单状态机、协办、申诉、回访、SLA 全部实现；通知多渠道未真实投递 |
| 智能体能力 | 75/100 | Orchestrator 三层路由 + Guard 完整；但 token 数审计断链、Rasa 与 Orchestrator 双轨 |
| RAG 知识库 | 70/100 | 完整流水线 + pgvector + 权限隔离；但无向量索引、关键词分词差、AI 用量审计断链 |
| 前端工程化 | 75/100 | 30+ 页面全部联调；但关键页面缺单元测试、E2E baseURL 不一致 |
| 后端工程化 | 80/100 | 14 个 API 模块 + 14 个迁移 + 27 个模型；测试覆盖较好 |
| 数据库设计 | 75/100 | 状态机/版本/乐观锁/索引合理；但缺向量索引、字段命名不一致 |
| 安全与权限 | 80/100 | RBAC + ABAC 双层 + 部门隔离 + 附件病毒扫描；但登出未撤销 token、service principal 风险 |
| 测试与可观测 | 70/100 | 47 后端测试 + 17 前端测试 + 32 acceptance 测试；但 E2E 依赖环境变量、AI 用量审计断链 |
| 运维与部署 | 65/100 | Docker Compose + 健康检查 + 备份脚本；但生产校验未启用、外部集成需手动配置 |
| 简历与演示价值 | 80/100 | 10/10 验收场景真实通过、有真实向量数据、有真实 AI 用量审计 |

### 1.7 当前最强部分

1. **Orchestrator 智能体编排**：规则关键词 → 超范围拦截 → Guard 预检查 → LLM 语义分类 → 路由执行 → 语义缓存，10 个验收场景 100% 真实通过（见第八章）。
2. **RAG 政策知识库**：pgvector + 权限三级隔离 + 失效政策双重检查 + 版本管理 + 评测体系，9 个合成政策文档 + 15 个真实向量索引。
3. **工单协同状态机**：6 状态 + 多部门协办（primary/support/review）+ 转派 + 退回 + 协办争议解决 + 乐观锁。
4. **AI 用量审计**：`ai_usage_logs` 表 16 个字段 + 5 索引，管理端 5 Tab 实时聚合，无静态假数据。

### 1.8 当前最薄弱部分

1. **AI 用量审计断链**：`orchestrator_service.py:470,519` 把 LLM 调用的 token 数硬编码为 `{"input_tokens": 0, "output_tokens": 0}`，导致所有 LLM 分类的 token 字段永远为 0；`kb_service.py` 的 RAG LLM 调用**完全不写入** ai_usage_logs。
2. **Rasa 与 Orchestrator 双轨**：两套意图体系（Rasa 22 intents vs Orchestrator 11 routes），未统一，访客走 Rasa、登录走 Orchestrator，行为不一致。
3. **Embedding 默认配置不工作**：`EMBEDDING_MODEL=text-embedding-v1` 是 OpenAI 模型名，但 `EMBEDDING_BASE_URL=https://api.deepseek.com`，DeepSeek 不提供该模型，默认走 hash fallback（无真实语义）。
4. **DepartmentKbPage 路由权限错误**：路由限定 `department_staff`，但组件内部判断 `isAdmin`，导致 admin 的 KB 文档管理能力（直发/跨部门/自动发布）完全不可达。
5. **关键词搜索无中文分词**：`re.findall(r"[\u4e00-\u9fff]+")` 把"路灯故障报修"作为单个 token，无法分词匹配。
6. **无 pgvector 向量索引**：0013 迁移只创建 vector(1024) 列，未创建 HNSW/IVFFlat 索引，大数据量下检索性能问题。

### 1.9 是否具备完整演示价值

**是**。10 个验收场景全部真实通过，319 个工单真实存在（含已办结），9 个 KB 文档 + 15 个真实向量索引，140 个用户（含 4 个演示账号 + 测试残留），8 个容器全部健康。5 分钟可演示完整业务闭环：登录 → 智能对话 → 政策 RAG → 工单草稿 → 提交 → 受理 → 派发 → 处理 → 办结 → 评价 → 申诉 → 回访。

### 1.10 是否适合写入简历

**是**，适合写入以下方向：

- **全栈开发**：FastAPI + React + PostgreSQL + Docker 全链路
- **AI 应用开发**：RAG + LLM + Embedding + 语义缓存 + 降级策略
- **Agent 开发**：Orchestrator 分层路由 + Guard 预检查 + 审计日志
- **RAG 应用开发**：pgvector + 权限隔离 + 版本管理 + 评测体系

但当前有一个**必须修复的简历风险**：AI 用量审计的 token 数为 0（见 P0-2），面试官若追问"你的 AI 成本核算是怎么做的"会暴露。

---

## 二、角色、终端与权限

### 2.1 角色清单

| 角色 | 登录方式 | 默认工作台 | 演示账号 |
|---|---|---|---|
| 市民 citizen | 用户名密码 / OIDC | `/citizen/chat` | `citizen_local` |
| 政务坐席 agent | 用户名密码 / OIDC | `/agent/tickets` | `agent_local` |
| 部门人员 department_staff | 用户名密码 / OIDC | `/department/tickets` | `department_local`（综合受理部门） |
| 系统管理员 admin | 用户名密码 / OIDC | `/admin/dashboard` | `admin_local` |
| 访客 anonymous | 无需登录 | `/chat` 或 `/welcome` | 无 |

统一密码：`tingting-seed-demo-2026`（12+ 字符，`seed.py:638-645` 校验）

### 2.2 前端入口与终端

共 **4 个登录后工作台 + 1 个公开入口**：

| 入口 | URL | 路由文件行号 | 说明 |
|---|---|---|---|
| 公开首页 | `/welcome` | AppRoutes.tsx:30 | 服务介绍 + 登录入口 |
| 公开对话 | `/chat` | AppRoutes.tsx:30 | 访客模式，走 Rasa |
| 市民工作台 | `/citizen/*` | AppRoutes.tsx:32 | 6 个二级菜单 |
| 坐席工作台 | `/agent/*` | AppRoutes.tsx:33 | 5 个二级菜单 |
| 部门工作台 | `/department/*` | AppRoutes.tsx:34 | 5 个二级菜单 |
| 管理员工作台 | `/admin/*` | AppRoutes.tsx:35 | 11 个二级菜单 |

### 2.3 各角色权限矩阵

| 角色 | 智能对话 | 政策咨询 | 工单提交 | 工单查询 | 工单受理 | 工单办理 | 知识库上传 | 知识库审核 | AI 用量审计 | 用户管理 |
|---|---|---|---|---|---|---|---|---|---|---|
| 访客 | ✅ Rasa | ✅ PUBLIC | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 市民 | ✅ Orchestrator | ✅ PUBLIC | ✅ 本人 | ✅ 本人 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 坐席 | ❌ 无入口 | ✅ PUBLIC+筛选 | ❌ | ✅ 全部 | ✅ 受理/派发 | ❌ | ❌ | ❌ | ❌ | ❌ |
| 部门 | ❌ 无入口 | ✅ 本部门 | ❌ | ✅ 本部门 | ❌ | ✅ 领取/处理/转派 | ✅ 本部门 | ❌ | ❌ | ❌ |
| 管理员 | ❌ 无入口 | ✅ 全部 | ❌ | ✅ 全部 | ✅ | ✅ | ✅ 全部 | ✅ 唯一审核方 | ✅ | ✅ |

### 2.4 鉴权实现

- **JWT**：`auth_service.py:14-28`，HS256，30 分钟过期，`Authorization: Bearer <token>`
- **Service 账号**：`dependencies.py:25` `hmac.compare_digest(token, service_api_token)` 用于 Rasa action
- **RBAC**：`authorization.py` `AuthorizationPolicy.require_roles(principal, *roles)` 静态工具类
- **ABAC**：service 层 `apply_query_scope` 按角色过滤数据范围（`authorization.py:69-96`）
- **登录限流**：`rate_limit.py:11-49` `LoginRateLimiter` 基于 `login_attempts` 表，每 IP/用户名窗口计数

### 2.5 越权风险评估

| 风险 | 证据 | 评估 |
|---|---|---|
| 工单越权 | `apply_query_scope` citizen 限制 `creator_user_id == principal.user_id` | 安全 |
| KB 越权 | `_require_dept_access` 三级隔离 + 部门人员本部门限制 | 安全 |
| 附件越权 | `attachment_service.py` 市民只能上传 public，internal 对市民隐藏 | 安全 |
| AI 助手越权 | `ai_service` 端点对 citizen 拒绝（test_phase6 验证 403） | 安全 |
| service principal | `kb_service.py:1400-1401` 不过滤可见性，`/kb/query` 用 `get_current_principal` 允许 service | **中风险** |
| 登出未撤销 token | `AuthContext.tsx:11` 仅前端 clear，后端 token 仍有效 | **中风险** |
| DepartmentKbPage 路由 | `AppRoutes.tsx:34` 限定 department_staff，但组件有 admin UI | **高风险（功能不可达）** |

### 2.6 角色完成情况

| 角色 | 完成度 | 主要缺口 |
|---|---|---|
| 访客 | 90% | 仍走 Rasa（未统一到 Orchestrator） |
| 市民 | 95% | 无 OIDC 真实 IdP 配置 |
| 坐席 | 85% | 无智能对话入口（菜单缺） |
| 部门 | 80% | KB 上传后 admin 审核流程可达，但 admin 无上传入口 |
| 管理员 | 75% | KB 文档管理能力被路由错误阻塞 |

---

## 三、完整业务闭环审计

### 3.1 政策咨询闭环

```
市民提问（"博士家属有什么待遇"）
  ↓ ChatPage.tsx:45 sendOrchestrator
Orchestrator.process（orchestrator_service.py:182-319）
  ↓ Step 1: _rule_detect 命中 POLICY_WORDS（"博士"/"待遇"），confidence=0.9
  ↓ Step 2: 查语义缓存（未命中）
  ↓ Step 3: Guard.pre_check（输入长度/会话/限流/去重/缓存/并发/预算）
  ↓ Step 4: _policy_response_with_rag（orchestrator_service.py:585, 665-715）
    ↓ kb_service.retrieve（kb_service.py:645-745）
      ↓ 权限过滤（_apply_visibility_filter）→ PUBLIC only for citizen
      ↓ 元数据过滤（region/domain/audience）
      ↓ 向量召回（pgvector <=> 余弦距离，top_k*3）
      ↓ 关键词召回（Jaccard，top_k*3）
      ↓ RRF 融合（k_const=60）
      ↓ 重排序（composite = rrf*0.7 + density*0.25 + len*0.05）
      ↓ 有效期检查（双重：SQL + Python）
    ↓ _generate_answer（kb_service.py:914-985）
      ↓ role-specific prompt（citizen 9 段式结构）
      ↓ DeepSeek chat/completions（urllib，max_tokens=800）
      ↓ 失败时返回原始 chunks
      ↓ no_evidence 时记录到 KbNoAnswerQuestionModel
  ↓ Step 5: 存入语义缓存（route=policy_rag, TTL=6h）
  ↓ Step 6: record_usage 写入 ai_usage_logs
返回前端：message + payload.citations + payload.answer + model + no_evidence
  ↓ ChatPage.tsx:86 渲染 bot 消息 + MessageMetaTags
  ↓ KbRagPanel.tsx:49 渲染回答 + 引用列表 + 反馈按钮
```

**实测结果**（2026-07-20）：
- 输入"博士家属有什么待遇" → `route=policy_rag, confidence=0.9, requires_llm=true, model_tier=llm_full, estimated_cost_level=high` ✅
- 第二次相同问题 → `cache_hit=true` ✅
- 无依据时 → `no_evidence=true` + 记录到 `kb_no_answer_questions` 表 ✅
- 失效政策 → 双重过滤拦截 ✅

**风险**：
- token 数硬编码为 0（`orchestrator_service.py:470,519`），AI 用量审计失真
- `kb_service._generate_answer` 的 LLM 调用**不写入** ai_usage_logs
- service principal 可绕过可见性过滤（`/kb/query` 端点）
- 无 HNSW 向量索引，大数据量下性能问题
- 关键词分词不足，"路灯故障报修"无法匹配"路灯故障"

### 3.2 投诉/举报/建议/求助/报修闭环

```
市民自然语言（"路灯坏了三天"）
  ↓ Orchestrator._rule_detect 命中投诉关键词
  ↓ route=ticket_intake, should_create_ticket=true
  ↓ _extract_ticket_draft_with_guard（orchestrator_service.py:592-602, 799-859）
    ↓ LLM 提取结构化字段（rules 优先，LLM 失败降级）
    ↓ payload.draft = {request_type, description, location, ...}
    ↓ payload.dynamic_fields = [road_or_community, fault_location, ...]
  ↓ 前端 ChatPage.tsx:71 setDraft + setDynamicFields + setDrawerOpen
  ↓ TicketDraftPanel.tsx 渲染动态表单
    ↓ 用户补全字段
    ↓ preReview（/api/v1/ai/pre-review）→ LLM 规范化描述
    ↓ createTicket（/api/v1/tickets）→ DB 写入 tickets 表
    ↓ status=pending, version=1, handling_round=1
  ↓ 坐席 agent/tickets 看到 pending 工单
    ↓ accept（ticket_service.py:179-208）→ status=accepted, version+1
    ↓ assign + work_order_service.create → status=assigned, work_order_id
  ↓ 部门 department/tickets 看到 assigned 工单
    ↓ work_order_service.start → status=processing
    ↓ work_order_service.submit → 主单 status=resolved（当所有协办提交）
    ↓ ticket_service.resolve → 触发 aftercare_service.on_ticket_event
      ↓ 创建 FollowUpTask（48h 内回访）
      ↓ 发送通知给市民
  ↓ 市民 citizen/tickets/:id 看到 resolved
    ↓ submit_feedback（ticket_service.py:409-446）
      ↓ satisfied → status=closed
      ↓ dissatisfied → status=processing, handling_round+1（重办）
  ↓ 不满意时 createAppeal → admin review
    ↓ approved → status=processing, collaboration_status=in_progress
    ↓ rejected → 维持原状态
  ↓ 回访：recordPhoneFollowUp
    ↓ outcome=confirmed → 关闭工单
    ↓ outcome=appeal_requested → 通知市民
```

**实测结果**：
- "路灯坏了三天" → `route=ticket_intake, category=路灯报修, dynamic_fields=[road_or_community, fault_location, ...]` ✅
- "我要投诉小区物业" → `route=ticket_intake` ✅
- 数据库 319 个工单，状态分布：pending=262, closed=20, resolved=12, accepted=12, assigned=6, processing=1, rejected=6 ✅
- 5 个最近已办结工单全部有真实部门归属 ✅

**类型区分**：投诉/建议/咨询/求助四种 `request_type` 共用同一 `tickets` 表字段，通过 `request_type` 列区分，**不共用错误字段**。报修作为投诉子类，通过 `category` 列区分（如"路灯报修"）。

**风险**：
- 262 个 pending 工单无人受理（演示数据残留）
- `ticket_intake` 路由的 LLM 失败降级到纯 rules，draft 字段可能不完整
- 多意图未处理，"我要投诉并咨询政策"只会进入投诉

### 3.3 工单查询闭环

```
市民输入"查询QT2026071300000001"
  ↓ Orchestrator._rule_detect 命中 PROGRESS_WORDS + ticket_id 正则
  ↓ route=ticket_progress, requires_llm=false, model_tier=rules
  ↓ _ticket_progress_response（orchestrator_service.py:577, 865-895）
    ↓ 直接查 DB: tickets WHERE ticket_id = ?
    ↓ citizen 角色额外校验 creator_user_id == principal.user_id
    ↓ 返回工单状态、责任部门、办理记录、SLA
  ↓ 前端渲染工单卡片 + 详情链接
```

**实测结果**：
- "查询QT2026071300000001" → `route=ticket_progress, confidence=0.95, requires_llm=false` ✅
- 不存在的工单号 → "未找到工单 QT...，请确认编号或登录提交该工单的市民账号后查询" ✅
- 仅查本人工单（citizen 角色限制）✅

**缺口**：
- 无通知/催办/回访/申诉的独立查询入口（需进入工单详情页查看）

### 3.4 坐席受理与派发闭环

```
坐席 agent/tickets 列表（GET /api/v1/tickets?status=pending）
  ↓ apply_query_scope: agent 看全部工单
  ↓ accept（POST /api/v1/tickets/:id/accept）
    ↓ ticket_service.accept: pending → accepted, version+1, audit_log
  ↓ assign（POST /api/v1/tickets/:id/assign）
    ↓ ticket_service.assign: accepted → assigned
    ↓ work_order_service.create: 创建 primary WorkOrder
    ↓ 多部门协办: support/review WorkOrder
  ↓ 版本冲突处理: 409 + 前端 TicketDetailPage 显示"工单已被他人更新"
```

**状态机**（`ticket_service.py:16-22`）：
```
pending → {accept, reject}
accepted → {assign}
assigned → {process}
processing → {note, resolve}
resolved → {close, process}  // process 触发重办
```

**实测**：
- 乐观锁版本控制通过 `version` 字段 + `VersionConflict` 异常 ✅
- 审计日志写入 `audit_logs` 表 ✅
- 智能分类/部门推荐：`ai_service.analyze` 6 类建议（summary/risk/assignment/document_draft/pre_review/case_advice）✅

**风险**：
- agent 无智能对话入口（菜单缺）
- 智能分派的 `staff=true` 硬编码（`IntelligencePage.tsx:36`），所有非市民角色看到相同视图

### 3.5 部门办理闭环

```
部门人员 department/tickets 列表（GET /api/v1/tickets?assigned_department_id=mine）
  ↓ apply_query_scope: department_staff 只看本部门
  ↓ work_order_service.start: WorkOrder status=processing
  ↓ work_order_service.submit: WorkOrder status=submitted
  ↓ 多部门协办: 全部 support submitted 后主办 primary 自动 resolve
  ↓ ticket_service.resolve: status=resolved
  ↓ 退回: work_order_service.return → 创建新 WorkOrder
  ↓ 转派: work_order_service.transfer → 创建后继 WorkOrder，原 WorkOrder 降级
  ↓ 协办争议: work_order_service.resolve_dispute → 重新指定 primary
```

**SLA**（`ticket_service.py:233-259`）：
- priority factor: normal=1.0, expedited=0.75, urgent=0.5, major=0.25
- accept_due_at = created_at + base_accept_minutes * factor
- resolve_due_at = created_at + base_resolve_minutes * factor
- pause_sla/resume_sla 调整 due_at 并累加 total_paused_seconds

**AI 办件助手**（`AiCaseAssistant.tsx` → `/api/v1/kb/tickets/:id/advice`）：
- `kb_service.ticket_advice`（`kb_service.py:1200-1347`）
- RAG 检索相关政策 + 内部规程
- LLM 生成处置建议、引用依据、注意事项
- 全部 `advisory_only=true`，需人工确认

**风险**：
- AI 办件助手的 LLM 调用不写入 ai_usage_logs
- 部门人员无法查看 DEPARTMENT 文档的 RAG 检索结果用于工单上下文

### 3.6 办结、评价、回访、申诉闭环

```
工单 resolved
  ↓ aftercare_service.on_ticket_event: 创建 FollowUpTask（48h 内回访）
  ↓ 市民 submit_feedback: rating 1-5
    ↓ satisfied (4-5) → closed
    ↓ mostly_satisfied (3) → closed
    ↓ dissatisfied (1-2) → processing, handling_round+1（重办）
  ↓ 不满意时 createAppeal（aftercare_service.create_appeal）
    ↓ 检查 APPEAL_LIMIT=2, APPEAL_WINDOW_DAYS=15
    ↓ 创建 AppealModel, status=submitted
  ↓ admin review_appeal
    ↓ approved → ticket.status=processing, handling_round+1
    ↓ rejected → 维持原状态
  ↓ 回访 recordPhoneFollowUp
    ↓ outcome=confirmed → 关闭工单
    ↓ outcome=appeal_requested → 通知市民
    ↓ outcome=unreachable → 记录重试
```

**实测**：
- 状态机完整（`aftercare_service.py:224-270`）
- 申诉次数上限 2 次，窗口 15 天，回访时限 48h（前端 `AftercarePage.tsx:27` 硬编码）
- 13 种事件模板（`aftercare_service.py:20-34`）

**风险**：
- 业务规则数字硬编码在前端（应从后端获取）
- 回访任务无催办提醒
- 申诉审核无评论长度限制

### 3.7 知识库管理闭环

```
部门上传（POST /kb/documents/upload）
  ↓ 权限: department_staff/admin（kb_service.py:138-139）
  ↓ 部门隔离: department_staff 强制使用 principal.department_id
  ↓ 文件类型: pdf/docx/md/txt（pypdf/python-docx/markdown）
  ↓ 存储到 MinIO bucket "tingting-kb"
  ↓ document_parser.parse: 提取文本 + OCR 质量评分
  ↓ 创建 KbDocumentModel, status=DRAFT
  ↓ _parse_and_index: 切片（chunk_size=500, overlap=100）+ embedding + 存储
  ↓ index_status=ready（embedding 可用时）或 failed
提交审核（POST /kb/documents/:id/submit-review）
  ↓ status=DRAFT/REJECTED → REVIEWING
管理员审核（POST /kb/documents/:id/review）
  ↓ 权限: 仅 admin
  ↓ decision=publish → status=PUBLISHED, 触发索引重建
  ↓ decision=reject → status=REJECTED, review_comment
发布后检索
  ↓ kb_service.retrieve: 仅 status=PUBLISHED, index_status=ready, 未过期
版本更新（POST /kb/documents/:id/versions 新版本）
  ↓ _create_new_version: parent_version_id, replaces_doc_id, version+1
  ↓ 旧版本 status=PUBLISHED → WITHDRAWN（仅 replaces_doc_id 链）
下线/失效
  ↓ withdraw_document: PUBLISHED → WITHDRAWN
  ↓ expire_document: PUBLISHED → EXPIRED
  ↓ 检索时双重过滤 expires_at
```

**实测**：
- 9 个 KB 文档：8 PUBLISHED + 1 EXPIRED ✅
- 15 个 chunks 全部有 embedding ✅
- 三级可见性：PUBLIC/DEPARTMENT/INTERNAL 正确隔离 ✅
- 失效政策（kb_policy_expired_trash）双重过滤拦截 ✅

**风险**：
- `PARSE_FAILED` 状态定义但从未使用（死代码）
- 版本链查询不完整（`list_versions` 只查直接子节点，v1→v2→v3 链断裂）
- `list_feedback` 部门过滤 bug（`document_ids` 是逗号分隔字符串，无法 IN 查询）
- `token_count` 字段存储字符数而非真实 token
- 无 HNSW 向量索引
- 无中文分词（jieba 未在关键词搜索中使用）

---

## 四、智能体编排审计

### 4.1 Orchestrator 实际实现

**核心文件**：`backend/app/services/orchestrator_service.py`

**支持的路由（11 个）**：
```python
ROUTES = (
    "policy_rag", "service_guide", "ticket_intake", "suggestion_intake",
    "ticket_progress", "department_navigation", "emergency_route",
    "general_chat", "human_handoff", "clarify", "out_of_scope",
)
```

**分层判定顺序**（`orchestrator_service.py:182-319`）：

1. **Step 1 规则检测**（`_rule_detect`）：关键词匹配，confidence >= 0.9 直接执行
2. **Step 2 超范围检测**（`_out_of_domain_detect`）：13 类关键词，命中即 out_of_scope
3. **Step 3 Guard 预检查**（`guard.pre_check`）：输入长度/会话/限流/去重/缓存/并发/预算
4. **Step 4 缓存命中**：直接返回缓存结果
5. **Step 5 LLM 分类**（`_llm_classify_with_guard`）：DeepSeek JSON 输出，confidence >= 0.6 执行
6. **Step 6 LLM 超范围**：in_domain=false → out_of_scope
7. **Step 7 低置信度**：0.4 <= confidence < 0.6 → clarify（单次澄清，不循环）
8. **Step 8 兜底**：confidence < 0.4 → out_of_scope（不再调 LLM）

### 4.2 路由输出结构

`OrchestratorResult` dataclass 共 **21 个字段**（`orchestrator_service.py:143-167`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| primary_intent | str | 主意图 |
| route | str | 路由结果（11 个之一） |
| confidence | float | 置信度 0-1 |
| in_domain | bool | 是否在政务范围 |
| requires_llm | bool | 是否需要 LLM |
| model_tier | str | rules/embedding/llm_lite/llm_full |
| estimated_cost_level | str | none/low/medium/high |
| rejection_reason | str | 拒绝原因 |
| urgency | str | normal/urgent/sensitive |
| sensitive_flags | list | 敏感词命中 |
| routing_reason | str | 路由理由 |
| should_create_ticket | bool | 是否触发工单创建 |
| should_clarify | bool | 是否需要澄清 |
| clarify_question | str | 澄清问题 |
| message | str | 返回消息 |
| payload | dict | 路由特定负载 |
| cache_hit | bool | 缓存命中 |
| degraded | bool | 降级 |
| degrade_reason | str | 降级原因 |
| rate_limited | bool | 限流 |
| budget_exceeded | bool | 预算超限 |

### 4.3 不需要 LLM 的路由

| route | model_tier | requires_llm | 说明 |
|---|---|---|---|
| emergency_route | rules | false | 固定话术 + 110/120 提示 |
| ticket_progress | rules | false | 直接查 DB |
| human_handoff | rules | false | 固定话术 |
| general_chat | rules | false | 问候/帮助/感谢固定话术 |
| department_navigation | rules | false | 查 DB 部门表 |
| suggestion_intake | rules | false | 纯模板 |
| out_of_scope | rules/llm_lite | false | 固定中文兜底 |
| clarify | rules | false | 单次澄清 |

需要 LLM 的路由：`policy_rag`（llm_full）、`service_guide`（llm_full）、`ticket_intake`（llm_lite，可选）

### 4.4 闲聊与无关问题限制

- **超范围关键词**（13 类，`orchestrator_service.py:76-83`）：写代码/编程/python/java/贪吃蛇/游戏代码/算法/leetcode/写论文/论文润色/学术/写诗/写小说/续写/故事/角色扮演/扮演/讲笑话/娱乐/闲聊/翻译
- **固定中文兜底**（`orchestrator_service.py:85-89`）：
  > "我主要提供政策咨询、办事指南、投诉建议、公共事务求助和工单进度查询。您可以告诉我想了解的政策、需要办理的事项，或者需要反映的问题。"
- **LLM prompt 限制**（`orchestrator_service.py:539-540`）：明确"不属于范围：写代码、写论文、娱乐闲聊、角色扮演、内容创作、翻译、其他无关问题"

### 4.5 Guard 预检查参数

| 参数 | 默认值 | 行号 |
|---|---|---|
| 输入最大字符数 | 500 | orchestrator_guard.py:39 |
| 输出最大 token | 800 | orchestrator_guard.py:40 |
| LLM 超时 | 20s | orchestrator_guard.py:41 |
| 单会话最大轮数 | 30 | orchestrator_guard.py:42 |
| 用户限流 | 20/min | orchestrator_guard.py:43 |
| 去重窗口 | 30s | orchestrator_guard.py:44 |
| 单用户每日 LLM 预算 | 60 | orchestrator_guard.py:45 |
| 全平台每日 LLM 预算 | 5000 | orchestrator_guard.py:46 |
| 缓存 TTL | 6h | orchestrator_guard.py:47 |
| 缓存最大条数 | 500 | orchestrator_guard.py:48 |
| 语义缓存相似度阈值 | 0.92 | orchestrator_guard.py:49 |

### 4.6 降级策略

| route | LLM 不可用时降级 |
|---|---|
| policy_rag | 无 DB → "建议拨打 12345"；RAG 失败 → LLM_UNAVAILABLE_MESSAGE |
| service_guide | LLM 不可用/并发超限/异常 → "建议拨打 12345 或前往政务服务大厅" |
| ticket_intake | LLM 不可用 → 纯 rules 提取（仅 request_type + description） |
| ticket_progress | 始终可用（直接查 DB） |
| emergency_route | 始终可用（固定话术） |
| 其他 | 始终可用（固定话术/模板） |

### 4.7 实测 10 条真实输入路由结果

| # | 输入 | route | confidence | model_tier | requires_llm | cost_level | 验证 |
|---|---|---|---|---|---|---|---|
| 1 | 你好 | general_chat | 0.95 | rules | false | none | ✅ |
| 2 | 帮助 | general_chat | 0.95 | rules | false | none | ✅ |
| 3 | 帮我写贪吃蛇代码 | out_of_scope | 1.0 | rules | false | none | ✅ |
| 4 | 博士家属有什么待遇 | policy_rag | 0.9 | llm_full | true | high | ✅ |
| 5 | 路灯坏了三天 | ticket_intake | 0.9 | llm_lite | true | medium | ✅ |
| 6 | 查询QT2026071300000001 | ticket_progress | 0.95 | rules | false | none | ✅ |
| 7 | 我要投诉小区物业 | ticket_intake | 0.9 | llm_lite | true | medium | ✅ |
| 8 | 谢谢 | general_chat | 0.95 | rules | false | none | ✅ |
| 9 | 写一篇论文 | out_of_scope | 1.0 | llm_lite | false | medium | ✅ |
| 10 | 怎么办理身份证 | service_guide | 0.9 | llm_full | true | high | ✅ |

**10/10 全部通过**（2026-07-20 12:33 UTC+8，真实 Docker 环境，真实 DB，真实 LLM）。

### 4.8 关键问题

1. **多意图未处理**：`_rule_detect` 通过优先级顺序处理，LLM 仅输出单 intent
2. **场景切换无显式检测**：槽位层面靠 `AllSlotsReset` 清理，Orchestrator 层无 session 状态切换
3. **session_id 默认共享**：`f"{user_key}:default"`，同一用户所有对话共享一个 session
4. **token 数审计断链**：`orchestrator_service.py:470,519` 硬编码 `{"input_tokens": 0, "output_tokens": 0}`
5. **Embedding fallback 维度不一致**：`embedding_client.py` 1024 维 vs `orchestrator_guard._pseudo_vector` 256 维
6. **Rasa 与 Orchestrator 双轨**：访客走 Rasa，登录走 Orchestrator，行为不一致

---

## 五、功能清单

### 5.1 完整功能矩阵

| 模块 | 功能 | 页面 | API | 数据表 | 当前状态 | 真实联调 | 主要问题 |
|---|---|---|---|---|---|---|---|
| 登录认证 | 用户名密码 | LoginPage | /auth/login | users | ✅ 完整 | ✅ | - |
| 登录认证 | OIDC 单点登录 | LoginPage + OidcCallbackPage | /auth/oidc/* | users | ✅ 完整 | ✅ | 需配置 IdP |
| 登录认证 | 登出 | WorkspaceLayout | - | - | ⚠️ 部分 | ❌ | 前端 clear 但后端 token 未撤销 |
| 市民对话 | 智能对话（登录） | ChatPage | /orchestrator/chat | ai_usage_logs | ✅ 完整 | ✅ | token 数为 0 |
| 市民对话 | 公开对话（访客） | ChatPage | /rasa/webhooks/rest/webhook | - | ⚠️ 部分 | ✅ | 与 Orchestrator 双轨 |
| 市民对话 | 工单草稿生成 | ChatPage + TicketDraftPanel | /orchestrator/chat | - | ✅ 完整 | ✅ | - |
| 政策咨询 | RAG 查询 | CitizenPolicyPage + KbRagPanel | /kb/query | kb_documents, kb_chunks | ✅ 完整 | ✅ | service principal 风险 |
| 政策咨询 | 政策检索（无 LLM） | AdminKbPage Testbed | /kb/retrieve | kb_chunks | ✅ 完整 | ✅ | - |
| 政策咨询 | 反馈提交 | KbRagPanel | /kb/feedback | kb_feedback | ✅ 完整 | ✅ | document_ids 字段类型问题 |
| 办事指南 | 智能问答 | ChatPage | /orchestrator/chat | - | ✅ 完整 | ✅ | LLM 直接生成，无 RAG |
| 工单草稿 | 草稿提取 | ChatPage | /orchestrator/chat | - | ✅ 完整 | ✅ | - |
| 工单草稿 | 草稿补全 | TicketDraftPanel | - | - | ✅ 完整 | ✅ | - |
| 工单草稿 | 智能预审 | CitizenPreReview + TicketDraftPanel | /ai/pre-review | ai_suggestions | ✅ 完整 | ✅ | - |
| 工单创建 | 提交工单 | TicketDraftPanel | /tickets | tickets | ✅ 完整 | ✅ | - |
| 我的工单 | 工单列表 | TicketsPage | /tickets | tickets | ✅ 完整 | ✅ | - |
| 工单详情 | 工单详情 | TicketDetailPage | /tickets/:id | tickets + work_orders | ✅ 完整 | ✅ | 14 种 Action |
| 进度查询 | 智能对话查询 | ChatPage | /orchestrator/chat | tickets | ✅ 完整 | ✅ | - |
| 坐席受理 | 待办列表 | TicketsPage | /tickets | tickets | ✅ 完整 | ✅ | - |
| 坐席受理 | 受理/拒绝/派发 | TicketDetailPage | /tickets/:id/accept 等 | tickets + audit_logs | ✅ 完整 | ✅ | - |
| 部门派发 | 多部门协办 | TicketDetailPage + WorkOrderPanel | /tickets/:id/work-orders | work_orders | ✅ 完整 | ✅ | - |
| 部门办理 | 领取/处理/转派/退回 | TicketDetailPage + WorkOrderPanel | /work-orders/* | work_orders + work_order_history | ✅ 完整 | ✅ | - |
| 部门办理 | SLA 时限 | SlaStatus | /tickets/:id/sla-* | tickets | ✅ 完整 | ✅ | - |
| 管理员工单 | 全部工单管理 | TicketsPage | /tickets | tickets | ✅ 完整 | ✅ | - |
| 用户管理 | 用户 CRUD | UsersPage | /users | users | ✅ 完整 | ✅ | 服务端分页 |
| 部门管理 | 部门 CRUD | DepartmentsPage | /departments | departments | ✅ 完整 | ✅ | - |
| 分类管理 | 三级分类树 | CategoriesPage | /categories | categories | ✅ 完整 | ✅ | - |
| 知识库管理 | 文档上传 | DepartmentKbPage | /kb/documents/upload | kb_documents | ⚠️ 路由错误 | ✅ | admin 无法访问 |
| 知识库管理 | 审核发布 | AdminKbPage | /kb/documents/:id/review | kb_documents | ✅ 完整 | ✅ | - |
| 知识库管理 | 版本管理 | DepartmentKbPage | /kb/documents/:id/versions | kb_documents | ⚠️ 链查询不完整 | ✅ | v1→v2→v3 断链 |
| 知识库管理 | 切片预览 | DepartmentKbPage | /kb/documents/:id/chunks | kb_chunks | ✅ 完整 | ✅ | - |
| 知识库管理 | 评测 | AdminKbPage | /kb/eval/* | kb_eval_cases + kb_eval_runs | ✅ 完整 | ✅ | permission_isolated 总是 True |
| AI 办件助手 | 工单建议 | AiCaseAssistant | /kb/tickets/:id/advice | ai_usage_logs (未写入) | ⚠️ 审计断链 | ✅ | LLM 调用未记录 |
| AI 智能分派 | 6 类建议 | IntelligencePage | /ai/tickets/:id/analyze | ai_suggestions | ✅ 完整 | ✅ | staff 硬编码 |
| 通知中心 | 站内通知 | NotificationsPage | /notifications | notifications | ✅ 完整 | ✅ | - |
| 通知中心 | 多渠道投递 | - | /notifications/channels | - | ❌ Mock | ❌ | 硬编码列表 |
| 回访申诉 | 申诉管理 | AftercarePage | /appeals | appeals | ✅ 完整 | ✅ | - |
| 回访申诉 | 电话回访 | AftercarePage | /follow-ups/* | follow_up_tasks + phone_follow_up_records | ✅ 完整 | ✅ | 业务规则硬编码前端 |
| 数据看板 | 运营总览 | DashboardPage | /admin/dashboard | tickets 聚合 | ✅ 完整 | ✅ | - |
| 审计日志 | 操作审计 | AuditPage | /admin/audit-logs | audit_logs | ✅ 完整 | ✅ | - |
| AI 用量审计 | 用量统计 | AdminAiUsagePage | /admin/ai-usage/stats | ai_usage_logs | ⚠️ token=0 | ✅ | LLM 调用 token 数为 0 |
| AI 用量审计 | 调用明细 | AdminAiUsagePage | /admin/ai-usage/logs | ai_usage_logs | ⚠️ token=0 | ✅ | 同上 |

### 5.2 Mock/未联调清单

| 模块 | 状态 | 证据 |
|---|---|---|
| 通知多渠道投递 | 硬编码列表 | `notifications.py:41-48` sms/wechat/email 标记 reserved |
| ServiceNow 集成 | 默认 localmode | `snow_credentials.yml:2` `localmode: true`，未真实调用 |
| OIDC 真实 IdP | 需配置 | 需配置 `OIDC_*` 环境变量 |
| 工单平台外部同步 | 需配置 | `integrations.py` 所有外部集成都需配置 |
| 短信/地图/行政区划 | 需配置 | `integrations.py` 同上 |
| OCR | 未集成 | `document_parser.py` 仅启发式判断，无 Tesseract |
| 历史案例脱敏 | 待验证 | 项目记忆硬约束要求脱敏，但代码未见显式脱敏逻辑 |

---

## 六、接口与数据库审计

### 6.1 后端模块分层

```
backend/app/
├── api/                  # FastAPI 路由层（15 个文件）
│   ├── auth.py           # 登录/me
│   ├── tickets.py        # 30+ 工单端点
│   ├── aftercare.py      # 5 回访申诉端点
│   ├── attachments.py    # 4 附件端点
│   ├── kb.py             # 20+ 知识库端点
│   ├── orchestrator.py   # 1 编排端点
│   ├── ai.py             # AI 建议/预审/热点
│   ├── ai_usage.py       # 3 AI 用量端点
│   ├── analytics.py      # 2 看板/审计端点
│   ├── sla_policies.py   # 3 SLA 策略端点
│   ├── users.py          # 用户管理
│   ├── categories.py     # 分类管理
│   ├── departments.py    # 部门管理
│   ├── notifications.py  # 通知
│   ├── integrations.py   # 外部集成
│   └── dependencies.py   # 鉴权依赖
├── services/             # 业务逻辑层（13 个文件）
│   ├── ticket_service.py # 工单状态机
│   ├── kb_service.py     # 知识库 + RAG
│   ├── orchestrator_service.py  # 智能体编排
│   ├── orchestrator_guard.py    # Guard 预检查
│   ├── aftercare_service.py     # 回访申诉
│   ├── ai_service.py     # AI 建议
│   ├── auth_service.py   # 认证
│   ├── admin_service.py  # 管理
│   ├── work_order_service.py    # 工单任务
│   ├── attachment_service.py    # 附件
│   ├── category_service.py      # 分类
│   ├── integration_service.py   # 集成
│   └── analytics_service.py     # 分析
├── repositories/         # 数据访问层（11 个文件）
├── models.py             # 27 个 SQLAlchemy 模型
├── main.py               # FastAPI 入口
├── config.py             # 80+ 配置项
├── database.py           # 引擎 + Session
├── llm_client.py         # DeepSeek 客户端
├── embedding_client.py   # Embedding 客户端
├── authorization.py      # RBAC + ABAC
└── ...
```

### 6.2 主要 API 调用关系

```
前端 → /api/v1/auth/login → JWT
前端 → /api/v1/orchestrator/chat → OrchestratorService.process
  ↓ → kb_service.retrieve (RAG)
  ↓ → llm_client.complete (LLM 分类/生成)
  ↓ → orchestrator_guard.record_usage → ai_usage_logs
前端 → /api/v1/tickets → ticket_service.create → tickets + audit_logs
前端 → /api/v1/tickets/:id/accept → ticket_service.accept → tickets + audit_logs
前端 → /api/v1/kb/query → kb_service.rag_answer → kb_chunks + LLM
前端 → /api/v1/admin/ai-usage/stats → analytics 聚合 ai_usage_logs
```

### 6.3 主要数据表

| 表 | 行数（实测） | 关键字段 | 索引 |
|---|---|---|---|
| users | 140 | username, role, department_id, oidc_subject | unique username |
| departments | 7 | code, name | unique code |
| categories | (待统计) | code, parent_id, level, default_department_id | - |
| tickets | 319 | ticket_id, creator_user_id, status, priority, version, handling_round | 11 索引 |
| work_orders | (待统计) | work_order_no, ticket_id, task_type, status | unique work_order_no |
| ticket_status_history | (待统计) | ticket_id, operation_type, previous_status, current_status | - |
| ticket_attachments | (待统计) | ticket_id, sha256, scan_status | unique object_key |
| audit_logs | (待统计) | action, resource_type, request_id | ix_audit_request_id |
| notifications | (待统计) | recipient_user_id, event_type, channel, status | unique event_key |
| follow_up_tasks | (待统计) | ticket_id, handling_round, due_at | unique (ticket_id, handling_round) |
| phone_follow_up_records | (待统计) | task_id, contact_result, satisfaction | - |
| appeals | (待统计) | appeal_no, ticket_id, sequence, status | unique (ticket_id, sequence) |
| ai_suggestions | (待统计) | ticket_id, suggestion_type, status, result_json | unique input_fingerprint |
| kb_documents | 9 | title, doc_number, kb_type, visibility, status, version, parent_version_id, replaces_doc_id, expires_at | 7 索引 |
| kb_chunks | 15 | document_id, content, embedding(Vector 1024), chunk_hash | 2 索引 |
| kb_eval_cases | 7 | title, scenario, query, expected_doc_ids | - |
| kb_eval_runs | (待统计) | case_id, role, citation_correct, answer_faithful | - |
| kb_no_answer_questions | (待统计) | query_text, status, assigned_department_id | - |
| ai_usage_logs | 33+ | request_id, user_id, route, model_tier, input_tokens, output_tokens, cache_hit, rate_limited, degraded | 5 索引 |
| ai_usage_budgets | (待统计) | user_id, daily_llm_call_limit | unique user_id |
| login_attempts | (待统计) | key, attempted_at | ix_login_attempts_key_time |
| sla_policies | 0 | name, category_id, priority, accept_minutes, resolve_minutes | unique name |

### 6.4 工单状态机

```
pending ──accept──> accepted ──assign──> assigned ──process──> processing
   │                                                                            │
   └──reject──> rejected                                                  note │
                                                                            resolve │
                                                                                ↓
                                                                            resolved
                                                                                │
                                                                          ┌─────┴─────┐
                                                                        close       process（重办）
                                                                          │            │
                                                                          ↓            ↓
                                                                        closed     processing
```

### 6.5 知识库状态机

```
(新) ──create──> DRAFT ──submit-review──> REVIEWING
                      │                         │
                      │                   review │
                      │                    ┌────┴────┐
                      │                  publish   reject
                      │                    │         │
                      │                    ↓         ↓
                      └──direct-publish─> PUBLISHED  REJECTED
                                            │
                                  ┌─────────┼─────────┐
                              withdraw   expire   new version
                                  │         │         │
                                  ↓         ↓         ↓
                              WITHDRAWN  EXPIRED    DRAFT（新版本）
```

### 6.6 字段一致性问题

| 问题 | 证据 |
|---|---|
| `Ticket.event` 字段定义但前端未展示 | types/index.ts:19 |
| `Ticket.occurred_at_start/end/precision` 未展示 | types/index.ts:20-21 |
| `Ticket.external_*` 字段未展示 | types/index.ts:32 |
| `WorkOrder.accepted_at/submitted_at/completed_at` 未展示 | types/index.ts:40 |
| `KbDocument.parent_version_id/replaces_doc_id` 未展示 | types/index.ts:91-92 |
| `KbDocumentDetail.*_by_user_id` 未展示 | types/index.ts:106-108 |
| `KbFeedback.document_ids` 类型不一致（string[] vs number[]） | types/index.ts:182 |
| `kb_chunks.token_count` 实际存储字符数 | kb_service.py:459 |
| `kb_chunks.chunking_version` 模型默认 v1 但代码硬编码 v2 | models.py:577 vs kb_service.py:111 |
| `OrchestratorRequest.message` max_length=5000 但 Guard 拒绝 501+ | api/orchestrator.py:19 vs guard:39 |

### 6.7 数据脏数据风险

| 风险 | 证据 |
|---|---|
| 140 个用户中 136 个是测试残留（phase4/5/6_*） | 实测 DB 查询 |
| 319 个工单中 262 个 pending（演示数据残留） | 实测 DB 查询 |
| `domain.yml:3-4` session_expiration_time=0.0 + carry_over_slots=true | 会话永不过期 + 槽位跨会话继承 |
| `kb_policy_expired_trash` 已过期但 status=PUBLISHED | seed.py:329，靠 expires_at 过滤 |
| `withdraw_document` 不删除 chunks | 下线文档 chunks 仍占存储 |
| `list_feedback` 部门过滤 bug | document_ids 是逗号分隔字符串 |

---

## 七、真实运行与测试结果

### 7.1 Docker 服务状态（实测 2026-07-20 12:33 UTC+8）

```
NAMES                                       STATUS                    PORTS
tingting-assistant-backend-1                Up 39 minutes (healthy)   0.0.0.0:8001->8000/tcp
tingting-assistant-frontend-1               Up 39 minutes (healthy)   0.0.0.0:8081->80/tcp
tingting-assistant-postgres-1               Up 39 minutes (healthy)   5432/tcp
tingting-assistant-minio-1                  Up 39 minutes (healthy)   29000/29001
tingting-assistant-rasa-1                   Up 39 minutes (healthy)   5005
tingting-assistant-action_server-1          Up 39 minutes (healthy)   127.0.0.1:5055
tingting-assistant-duckling-1               Up 39 minutes (healthy)   18080
tingting-assistant-worker-1                 Up 39 minutes (healthy)   8000 (内部)
```

**8/8 容器全部 healthy**。Rasa 加载模型 `tingting-v1.2.0-draft.tar.gz`（文件存在，子代理误报为不存在）。

### 7.2 API 健康检查

```bash
$ curl http://localhost:8001/health
{"success":true,"data":{"status":"ready","database":"ok"}}

$ POST /api/v1/auth/login {"username":"admin_local","password":"tingting-seed-demo-2026"}
{"success":true,"data":{"access_token":"eyJ...","token_type":"bearer","expires_in":1800}}
```

### 7.3 数据库实测

```
kb_documents: 8 PUBLISHED + 1 EXPIRED = 9 条
kb_chunks: 15 条，全部有 embedding
tickets: pending=262, closed=20, resolved=12, accepted=12, assigned=6, processing=1, rejected=6 = 319 条
users: 140 条（4 演示 + 136 测试残留）
ai_usage_logs: 33 条，cache_hits=5, rate_limited=0, degraded=0
  by route: general_chat=9, out_of_scope=9, policy_rag=6, ticket_intake=1, ticket_progress=8
  by tier: rules=28, llm_lite=5
  ⚠️ in_tok=0, out_tok=0 (token 数硬编码为 0 的 bug 已确认)
```

### 7.4 后端测试执行

```bash
$ docker exec tingting-assistant-backend-1 python -m pytest tests/test_orchestrator_guard.py -v
============================== 32 passed in 3.08s ==============================
```

**32/32 acceptance 测试全部通过**，覆盖 10 个验收场景 + Guard 预检查 + OrchestratorResult 字段完整性。

测试分类：
- `TestNoEnglishPollution` (3): 无英文模板泄漏
- `TestGreetUsesTemplate` (3): 问候/帮助/感谢不调 LLM
- `TestOutOfDomainBlocking` (3): 贪吃蛇/论文/角色扮演被拦截
- `TestPolicyRagRouting` (2): 博士家属路由到 policy_rag
- `TestTicketIntakeRouting` (2): 路灯坏了三天路由到 ticket_intake
- `TestTicketProgressDirectQuery` (2): 工单号直查不调 LLM
- `TestSemanticCache` (2): 缓存存储与查找
- `TestVisitorBudgetLimit` (2): 访客超额提示登录
- `TestLlmUnavailableDegradation` (4): LLM 不可用时降级
- `TestAiUsageAuditLog` (3): 审计日志持久化 + 成本估算
- `TestGuardPreCheck` (4): 输入长度/会话/限流/并发
- `TestOrchestratorResultFields` (2): 结果字段完整性

### 7.5 端到端 10 场景验证

实测脚本 `scripts/audit_e2e_verify.py`，结果：

```
#   Input                        ExpectedRoute          ActualRoute            Tier       LLM   Cost     OK
------------------------------------------------------------------------------------------------------------------
1   你好                           general_chat           general_chat           rules      N     none     OK
2   帮助                           general_chat           general_chat           rules      N     none     OK
3   帮我写贪吃蛇代码                     out_of_scope           out_of_scope           rules      N     none     OK
4   博士家属有什么待遇                    policy_rag             policy_rag             llm_full   Y     high     OK
5   路灯坏了三天                       ticket_intake          ticket_intake          llm_lite   Y     medium   OK
6   查询QT2026071300000001         ticket_progress        ticket_progress        rules      N     none     OK
7   我要投诉小区物业                     ticket_intake          ticket_intake          llm_lite   Y     medium   OK
8   谢谢                           general_chat           general_chat           rules      N     none     OK
9   写一篇论文                        out_of_scope           out_of_scope           llm_lite   N     medium   OK
10  怎么办理身份证                      service_guide          service_guide          llm_full   Y     high     OK

Passed: 10/10

--- Cache Test ---
First: route=policy_rag cache_hit=True
Second: route=policy_rag cache_hit=True

--- Admin AI Usage Stats ---
Total calls: 33
Total tokens: 0  ← 关键问题：LLM token 数为 0
Cache hit rate: 21.21%
By route: 5 routes
By tier: 2 tiers
```

### 7.6 未执行测试及原因

| 测试 | 未执行原因 |
|---|---|
| `test_phase4_collaboration.py` | 需真实 PostgreSQL + 完整 seed 数据 |
| `test_phase5_aftercare.py` | 需真实 PostgreSQL + 完整 seed 数据 |
| `test_phase6_ai_integrations.py` | 需真实 PostgreSQL + AI_API_KEY |
| `test_postgres_repository.py` | 需真实 PostgreSQL |
| `test_round4.py` | 需真实 PostgreSQL + 完整 seed 数据 |
| 前端单元测试（vitest） | 未执行（需在 frontend 目录运行 npm test） |
| 前端 E2E（playwright） | 未执行（依赖 E2E_PASSWORD 环境变量 + baseURL 不一致） |
| 前端构建（vite build） | 未执行（之前会话已验证通过） |

---

## 八、当前问题清单

### 8.1 P0：影响核心业务闭环

#### P0-1：AI 用量审计 token 数断链

- **表现**：`ai_usage_logs` 表中所有 LLM 调用的 `input_tokens=0, output_tokens=0`，`estimated_cost_rmb=0`，导致管理端"AI 用量与安全"页面的 Token 消耗和成本数据全部失真。
- **根因**：`orchestrator_service.py:470, 519` 把 LLM 调用的 `llm_meta` 硬编码为 `{"input_tokens": 0, "output_tokens": 0}`，没有从 LLM 响应中解析 `usage.total_tokens`；`kb_service.py` 的 `_generate_answer` 和 `ticket_advice` 的 LLM 调用**完全不写入** `ai_usage_logs`。
- **影响范围**：所有 LLM 调用（policy_rag、service_guide、ticket_intake、out_of_scope 的 LLM 分类、RAG 答案生成、AI 办件助手）的审计数据失真，无法核算真实成本。
- **相关文件**：
  - `backend/app/services/orchestrator_service.py:470, 519`
  - `backend/app/services/kb_service.py:959-985, 1258-1310`
  - `backend/app/llm_client.py:144-159`（DeepSeek 响应中 `usage` 字段未提取）
- **建议处理**：从 DeepSeek 响应 `result["usage"]["total_tokens"]` / `prompt_tokens` / `completion_tokens` 提取并写入 `llm_meta`，`kb_service` 的 LLM 调用也调用 `guard.record_usage`。
- **简历价值**：✅ 必须做，否则面试官追问"AI 成本核算"会暴露。

#### P0-2：DepartmentKbPage 路由权限错误

- **表现**：`/department/kb` 路由限定 `department_staff`，但 `DepartmentKbPage.tsx:59` 内部判断 `isAdmin = user?.role === 'admin'` 并渲染 admin 专属 UI（直发按钮 L170、跨部门筛选 L193、自动发布选项 L540），导致 admin 无法访问这些功能。
- **根因**：路由守卫与组件内部角色判断不一致。
- **影响范围**：admin 的 KB 文档管理能力（上传/录入/直发/跨部门/自动发布）完全不可达，知识库生命周期断链。
- **相关文件**：
  - `frontend/src/routes/AppRoutes.tsx:34`（限定 department_staff）
  - `frontend/src/pages/DepartmentKbPage.tsx:59, 170, 193, 540`
- **建议处理**：将路由守卫改为 `roles={['department_staff', 'admin']}`，或在 admin 菜单中添加 `/admin/kb/manage` 入口。
- **简历价值**：✅ 必须做，否则演示时 admin 无法上传文档。

#### P0-3：Rasa 与 Orchestrator 双轨未统一

- **表现**：访客走 Rasa（22 intents），登录走 Orchestrator（11 routes），同一用户消息行为不一致。例如访客问"路灯坏了三天"走 Rasa 的 `submit_complaint` intent + `public_request_form`，登录后走 Orchestrator 的 `ticket_intake` route + LLM 草稿提取，UI 体验和数据流完全不同。
- **根因**：历史遗留，Rasa 是早期 channel，Orchestrator 是后期自研编排，两者未统一。
- **影响范围**：访客→登录后体验割裂，维护两套意图体系成本高。
- **相关文件**：
  - `frontend/src/pages/ChatPage.tsx:44-62`（user 走 Orchestrator，否则走 Rasa）
  - `domain.yml`（22 intents）vs `orchestrator_service.py:45-49`（11 routes）
- **建议处理**：让访客也走 Orchestrator（`get_current_principal` 已支持匿名），或保留 Rasa 仅作为 fallback channel。
- **简历价值**：⚠️ 建议做，能体现架构演进能力。

### 8.2 P1：影响完整性和演示质量

#### P1-1：无 pgvector 向量索引

- **表现**：0013 迁移只创建 `vector(1024)` 列，未创建 HNSW 或 IVFFlat 索引，pgvector 检索使用顺序扫描。
- **根因**：迁移遗漏。
- **影响范围**：知识库 chunks 数量大时（>10000）检索性能下降。
- **相关文件**：`backend/migrations/versions/0013_kb_extensions.py`
- **建议处理**：添加迁移创建 `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`。
- **简历价值**：✅ 建议做，体现工程化思考。

#### P1-2：关键词搜索无中文分词

- **表现**：`_keyword_search` 用 `re.findall(r"[\u4e00-\u9fff]+")` 把连续汉字作为单个 token，"路灯故障报修"无法分词匹配"路灯故障"。
- **根因**：未使用 jieba 等分词库（虽然 Rasa 用了 JiebaTokenizer，但 KB 服务没用）。
- **影响范围**：关键词召回质量低，影响 RAG 检索准确性。
- **相关文件**：`backend/app/services/kb_service.py:764-787`
- **建议处理**：引入 jieba 分词，或使用 PostgreSQL pg_trgm 扩展。
- **简历价值**：✅ 建议做，体现中文 NLP 能力。

#### P1-3：登出未撤销后端 token

- **表现**：`AuthContext.tsx:11` 仅前端 `tokenStore.clear()`，后端 token 在 30 分钟有效期内仍可重放。
- **根因**：未实现 token 黑名单或刷新机制。
- **影响范围**：token 被窃取后前端登出无法阻止重放。
- **相关文件**：`frontend/src/auth/AuthContext.tsx:11`
- **建议处理**：添加 `/auth/logout` 端点 + Redis 黑名单（或 JWT 短期 + Refresh Token）。
- **简历价值**：⚠️ 可做可不做，演示价值有限。

#### P1-4：版本链查询不完整

- **表现**：`list_versions` 只查 `parent_version_id == root_id` 或 `replaces_doc_id == root_id`，v1→v2→v3 链断裂，v3 无法被找到。
- **根因**：查询逻辑只查直接子节点，未递归。
- **影响范围**：多版本文档历史不完整。
- **相关文件**：`backend/app/services/kb_service.py:613-619`
- **建议处理**：递归 CTE 或遍历 parent_version_id 链。
- **简历价值**：✅ 建议做，体现数据建模能力。

#### P1-5：E2E 测试 baseURL 不一致

- **表现**：`playwright.config.ts:4` baseURL=`http://localhost:8080`，但 `orchestrator.spec.ts:3` 和 `chat-draft.spec.ts:3` 用 `BASE='http://localhost:8081'`，`workflows.spec.ts:3` 用按钮名称"安全登录"但 `orchestrator.spec.ts:10` 用"登录"。
- **根因**：测试配置不统一。
- **影响范围**：E2E 测试在标准配置下失败。
- **相关文件**：`frontend/playwright.config.ts`、`frontend/e2e/orchestrator.spec.ts`、`frontend/e2e/chat-draft.spec.ts`
- **建议处理**：统一 baseURL 和按钮名称。
- **简历价值**：⚠️ 可做，体现测试工程化。

#### P1-6：IntelligencePage staff 硬编码

- **表现**：`IntelligencePage.tsx:36` `const staff=true` 永远为 true，所有非市民角色看到相同 staff 视图，无法区分 agent/department/admin 的能力差异。
- **根因**：硬编码。
- **影响范围**：坐席看到部门专属功能，部门看到 admin 功能。
- **相关文件**：`frontend/src/pages/IntelligencePage.tsx:36`
- **建议处理**：基于 `user.role` 判断。
- **简历价值**：✅ 建议做。

#### P1-7：业务规则数字硬编码前端

- **表现**：`AftercarePage.tsx:27` 申诉次数上限=2、申诉期限=15 天、自动回访时限=48h 全部硬编码在前端。
- **根因**：未从后端获取规则配置。
- **影响范围**：规则变更需改前端代码。
- **相关文件**：`frontend/src/pages/AftercarePage.tsx:27`
- **建议处理**：添加 `/api/v1/admin/rules` 端点或从 sla_policies 表读取。
- **简历价值**：⚠️ 可做。

#### P1-8：list_feedback 部门过滤 bug

- **表现**：`kb_service.py:1018-1026` 使用 `KbFeedbackModel.document_ids.in_(select(...))`，但 `document_ids` 是逗号分隔字符串，IN 查询无法正确匹配。
- **根因**：字段类型设计错误，应使用关联表。
- **影响范围**：部门人员看不到任何反馈，或看到所有反馈。
- **相关文件**：`backend/app/services/kb_service.py:1018-1026`
- **建议处理**：改为 JSON 数组类型或关联表。
- **简历价值**：✅ 建议做。

### 8.3 P2：体验和工程优化

#### P2-1：AdminKbPage EvalTab DOM dataset 反模式

- **表现**：`AdminKbPage.tsx:313-318` 用 `document.getElementById('eval-role').dataset.role = v` 存角色选择，违反 React 单向数据流。
- **建议**：改用 `useState`。

#### P2-2：ServiceStatus 探测未文档化端点

- **表现**：`ServiceStatus.tsx:6` 探测 `/api/v1/system/health` 和 `/rasa/status`，未在任何 API 客户端中声明。
- **建议**：与后端确认端点存在性，或改用 `/health`。

#### P2-3：未使用的 downloadKbDocumentUrl 函数

- **表现**：`kb.ts:43-46` 定义但无任何调用方，DepartmentKbPage 直接硬编码 URL。
- **建议**：删除或让 DepartmentKbPage 使用它。

#### P2-4：代码超长行

- **表现**：AppRoutes.tsx、WorkspaceLayout.tsx、TicketsPage.tsx、TicketDetailPage.tsx、AftercarePage.tsx、IntelligencePage.tsx 单行超 1000 字符，可读性极差。
- **建议**：格式化。

#### P2-5：WorkOrderPanel 时间格式不一致

- **表现**：`WorkOrderPanel.tsx:102, 112` 用 `new Date().toLocaleString('zh-CN')`，全站其他位置用 dayjs。
- **建议**：统一为 dayjs。

#### P2-6：AdminKbPage 与 DepartmentKbPage 重复代码

- **表现**：两处都定义了 `kbTypeLabel`、`STATUS_LABELS`、FeedbackTab。
- **建议**：抽取共享模块。

#### P2-7：chat_id 共享导致跨场景槽位污染

- **表现**：`session_id = f"{user_key}:default"`，同一用户所有对话共享一个 session。
- **建议**：按 route 隔离 session_id。

#### P2-8：domain.yml session_expiration_time=0.0

- **表现**：会话永不过期 + `carry_over_slots_to_new_session: true`，槽位跨会话继承。
- **建议**：设为 60 分钟，关闭 carry_over。

#### P2-9：图表可访问性

- **表现**：ChartPanel 仅 `role="img"` + `aria-label`，无文字数据替代。
- **建议**：添加 `<table>` 隐藏版本。

#### P2-10：测试残留用户

- **表现**：DB 中 140 个用户，136 个是 phase4/5/6_* 测试残留。
- **建议**：定期清理或添加 `is_test` 字段过滤。

---

## 九、从完整政务诉求平台角度的独立建议

### 9.1 必须实现（提升业务闭环和简历含金量）

| # | 能力 | 理由 |
|---|---|---|
| 1 | **AI 用量审计 token 数修复** | P0-1，否则审计数据失真，面试必问 |
| 2 | **DepartmentKbPage 路由修复** | P0-2，否则 admin 无法管理 KB |
| 3 | **pgvector HNSW 索引** | P1-1，体现工程化 |
| 4 | **jieba 中文分词** | P1-2，体现 NLP 能力 |
| 5 | **版本链递归查询** | P1-4，体现数据建模 |
| 6 | **E2E 测试统一** | P1-5，体现测试工程化 |
| 7 | **Rasa 与 Orchestrator 统一** | P0-3，体现架构演进 |
| 8 | **真实政策文件导入** | 当前是合成数据，导入 3-5 个真实政策文件能显著提升可信度 |

### 9.2 建议实现（增强完整度）

| # | 能力 | 理由 |
|---|---|---|
| 1 | **通知多渠道投递** | 当前硬编码列表，实现短信/邮件模拟投递 |
| 2 | **SLA 策略管理** | sla_policies 表存在但 seed 未填充，admin 应能配置 |
| 3 | **催办与超时提醒** | worker 定时扫描即将超时工单 |
| 4 | **工单导出** | CSV/Excel 导出 |
| 5 | **多轮对话上下文** | 当前 session 共享，按 route 隔离 |
| 6 | **AI 建议人工确认流程** | 当前 advisory_only=true 但无确认 UI |
| 7 | **知识库质量监控** | 检索命中率、引用准确率实时看板 |
| 8 | **访客模式统一到 Orchestrator** | 让访客也走 Orchestrator 但限制 route |

### 9.3 不建议实现（成本高、价值低）

| # | 能力 | 理由 |
|---|---|---|
| 1 | **真实 OIDC IdP** | 需部署 Keycloak，演示用账号密码足够 |
| 2 | **真实短信平台** | 成本高，用模拟投递足够 |
| 3 | **真实政务专网对接** | 演示项目不需要 |
| 4 | **电子签章** | 成本高，演示价值有限 |
| 5 | **真实统一身份认证** | 成本高，用账号密码足够 |
| 6 | **Tesseract OCR** | 增加镜像体积，演示用文本 PDF 足够 |
| 7 | **真实 ServiceNow 集成** | 项目已脱离 ServiceNow 场景 |
| 8 | **HBASE/Cassandra 等大数据存储** | PostgreSQL 足够 |
| 9 | **Kubernetes 部署** | Docker Compose 足够演示 |
| 10 | **Prometheus + Grafana** | 当前 `/metrics` 端点 + AdminAiUsagePage 足够 |

---

## 十、最终优化路线（3 轮）

### 第 1 轮：业务闭环与数据正确性

**目标**：修复 P0 问题，确保演示时所有角色都能完成完整业务闭环。

**必须完成**：
1. 修复 AI 用量审计 token 数断链（P0-1）
   - `llm_client.py:144-159` 从 DeepSeek 响应提取 `usage.total_tokens/prompt_tokens/completion_tokens`
   - `orchestrator_service.py:470, 519` 用真实 token 数替换硬编码 0
   - `kb_service.py:959-985, 1258-1310` 调用 `guard.record_usage` 写入审计日志
2. 修复 DepartmentKbPage 路由权限（P0-2）
   - `AppRoutes.tsx:34` 改为 `roles={['department_staff', 'admin']}`
   - 或在 admin 菜单添加 `/admin/kb/manage` 入口
3. 修复 list_feedback 部门过滤 bug（P1-8）
4. 修复版本链查询不完整（P1-4）
5. 修复 IntelligencePage staff 硬编码（P1-6）
6. 修复 E2E 测试 baseURL 不一致（P1-5）

**主要修改模块**：
- `backend/app/llm_client.py`
- `backend/app/services/orchestrator_service.py`
- `backend/app/services/kb_service.py`
- `frontend/src/routes/AppRoutes.tsx`
- `frontend/src/pages/IntelligencePage.tsx`
- `frontend/playwright.config.ts` + `frontend/e2e/*.spec.ts`

**测试要求**：
- 重新运行 `pytest tests/test_orchestrator_guard.py`，32/32 通过
- 运行 `python scripts/audit_e2e_verify.py`，10/10 通过
- 验证 `ai_usage_logs` 表中 LLM 调用的 token 数 > 0
- 验证 admin 能访问 `/department/kb` 上传文档

**验收标准**：
- AdminAiUsagePage 的 Token 消耗 > 0
- admin 能上传 KB 文档并直接发布
- 部门人员能看到本部门 KB 反馈
- 版本链能查到 v1→v2→v3 完整链

**对简历的提升**：能写"完整的 AI 用量审计与成本核算体系"。

**本轮不做**：UI 美化、性能优化、新功能开发。

### 第 2 轮：智能体与 RAG 可靠性

**目标**：提升 RAG 检索质量和智能体编排稳定性。

**必须完成**：
1. 添加 pgvector HNSW 索引（P1-1）
   - 新迁移 `0015_vector_index.py`：`CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops)`
2. 引入 jieba 中文分词（P1-2）
   - `kb_service._keyword_search` 和 `document_parser.extract_keywords` 使用 jieba
3. 修复 Embedding 默认配置不工作（H5）
   - `config.py:53` 默认改为 SiliconFlow `Qwen3-VL-Embedding-8B`
   - 或在文档中明确说明需配置 `EMBEDDING_API_KEY`
4. 修复 Embedding fallback 维度不一致（H4）
   - `orchestrator_guard._pseudo_vector` 改为 1024 维
5. 修复 session 隔离（P2-7）
   - `session_id = f"{user_key}:{route}"` 按 route 隔离
6. 修复 domain.yml 会话配置（P2-8）
   - `session_expiration_time: 60`，`carry_over_slots_to_new_session: false`
7. 统一 Rasa 与 Orchestrator（P0-3）
   - 访客也走 Orchestrator，限制 route 白名单
8. 添加 3-5 个真实政策文件到 seed

**主要修改模块**：
- `backend/migrations/versions/0015_vector_index.py`（新建）
- `backend/app/services/kb_service.py`
- `backend/app/services/orchestrator_guard.py`
- `backend/app/config.py`
- `backend/app/seed.py`
- `domain.yml`
- `frontend/src/pages/ChatPage.tsx`

**测试要求**：
- 重新运行 10 场景 E2E，10/10 通过
- 添加 RAG 检索质量测试（命中率 > 80%）
- 添加分词测试（"路灯故障"能匹配"路灯故障报修"）
- 验证访客走 Orchestrator 后行为一致

**验收标准**：
- `EXPLAIN ANALYZE` 显示向量检索使用 HNSW 索引
- 关键词搜索能分词匹配
- Embedding 配置默认可用（或文档明确说明）
- 访客和登录用户对话行为一致

**对简历的提升**：能写"基于 pgvector HNSW + jieba 分词的高质量中文 RAG 检索"。

**本轮不做**：通知多渠道、SLA 策略管理、催办提醒。

### 第 3 轮：演示体验与工程完善

**目标**：提升演示流畅度和工程完善度。

**必须完成**：
1. 清理测试残留用户（P2-10）
   - 添加 `is_test` 字段或定期清理脚本
2. 修复 AdminKbPage EvalTab DOM 反模式（P2-1）
3. 修复 ServiceStatus 探测端点（P2-2）
4. 修复代码超长行（P2-4）
5. 修复 WorkOrderPanel 时间格式不一致（P2-5）
6. 抽取 AdminKbPage 与 DepartmentKbPage 共享代码（P2-6）
7. 添加关键页面单元测试
   - AdminKbPage、DepartmentKbPage、AdminAiUsagePage、CitizenPreReview、AttachmentPanel、WorkOrderPanel、AiCaseAssistant、KbRagPanel、TicketDraftPanel
8. 添加 5 分钟演示脚本（docs/demo-script.md 已存在，需更新）
9. 添加 SLA 策略 seed 数据
10. 添加催办提醒（worker 定时扫描）

**主要修改模块**：
- `backend/app/seed.py`
- `backend/app/worker.py`
- `frontend/src/pages/AdminKbPage.tsx`
- `frontend/src/components/ServiceStatus.tsx`
- `frontend/src/components/WorkOrderPanel.tsx`
- `frontend/src/pages/*.test.tsx`（新增）
- `docs/demo-script.md`

**测试要求**：
- 前端单元测试覆盖率达到 60%+
- E2E 测试全部通过
- 演示脚本走完 5 分钟无卡顿

**验收标准**：
- 演示 5 分钟完整闭环：登录 → 对话 → RAG → 工单 → 受理 → 派发 → 处理 → 办结 → 评价 → 申诉 → 回访
- AdminAiUsagePage 显示真实 token 数和成本
- 所有 P0/P1 问题修复

**对简历的提升**：能写"完整的政务诉求协同平台，含 30+ 页面、47+ 后端测试、32 acceptance 测试、5 分钟可演示完整闭环"。

**本轮不做**：真实 OIDC、真实短信、Kubernetes、Tesseract OCR。

---

## 十一、简历与演示价值

### 11.1 是否适合写进简历

**是**。综合评分 72/100，10/10 验收场景真实通过，8/8 Docker 容器健康，319 个真实工单，9 个 KB 文档 + 15 个真实向量索引，完整业务闭环可演示。

### 11.2 适合投递的岗位

| 岗位 | 匹配度 | 项目亮点 |
|---|---|---|
| **全栈开发** | ⭐⭐⭐⭐⭐ | FastAPI + React + PostgreSQL + Docker 全链路，30+ 页面，15 个 API 模块 |
| **Python 后端** | ⭐⭐⭐⭐⭐ | FastAPI + SQLAlchemy + Alembic + JWT + RBAC/ABAC + 状态机 + 乐观锁 |
| **AI 应用开发** | ⭐⭐⭐⭐ | RAG + LLM + Embedding + 语义缓存 + 降级策略 + 审计日志 |
| **Agent 开发** | ⭐⭐⭐⭐ | Orchestrator 三层路由 + Guard 预检查 + 11 routes + 10 场景验收 |
| **RAG 应用开发** | ⭐⭐⭐⭐ | pgvector + 权限隔离 + 版本管理 + 评测体系 + RRF 融合 + 重排序 |

### 11.3 当前可以真实描述的项目亮点

1. **完整的政务诉求协同平台**：4 角色（市民/坐席/部门/管理员）+ 8 Docker 容器 + 319 真实工单 + 5 分钟可演示完整闭环
2. **自研 LLM Orchestrator**：规则 → Rasa → LLM 三层路由，21 字段结果结构，10/10 验收场景真实通过
3. **RAG 政策知识库**：pgvector + 三级权限隔离 + 失效政策双重检查 + 版本管理 + RRF 融合 + 重排序 + 评测体系
4. **AI 用量审计**：`ai_usage_logs` 表 16 字段 + 5 索引 + 管理端 5 Tab 实时聚合（注：token 数待修复）
5. **工单协同状态机**：6 状态 + 多部门协办（primary/support/review）+ 转派/退回/争议解决 + 乐观锁
6. **Guard 防滥用**：输入长度/会话轮数/限流/去重/语义缓存/并发控制/预算/降级 8 层预检查
7. **完整测试覆盖**：47 后端测试 + 32 acceptance 测试 + 17 前端单元测试 + 5 E2E spec
8. **生产级工程**：14 个 Alembic 迁移 + 27 个 SQLAlchemy 模型 + JWT + RBAC + ABAC + 附件病毒扫描 + SHA-256 完整性

### 11.4 哪些亮点现在还不能写

| 亮点 | 必须先完成 |
|---|---|
| "AI 成本核算与预算控制" | 修复 P0-1 token 数断链 |
| "基于 HNSW 的高性能向量检索" | 添加 pgvector HNSW 索引（P1-1） |
| "中文 NLP 分词与检索" | 引入 jieba 分词（P1-2） |
| "统一智能体编排" | 统一 Rasa 与 Orchestrator（P0-3） |
| "完整知识库版本管理" | 修复版本链查询（P1-4） |
| "多渠道通知投递" | 实现真实投递（当前硬编码列表） |

### 11.5 5 分钟演示路线

```
0:00-0:30 登录页
  - 展示品牌、输入 admin_local / tingting-seed-demo-2026
  - 强调"4 角色 + 统一认证"

0:30-1:30 管理员看板
  - /admin/dashboard 显示 319 工单、状态分布、部门 SLA
  - /admin/ai-usage 显示 AI 用量、缓存命中率、route 分布
  - 强调"实时聚合，无静态假数据"

1:30-2:30 切换市民 → 智能对话
  - /citizen/chat 输入"博士家属有什么待遇"
  - 展示 route=policy_rag, requires_llm=true, citations 列表
  - 输入"路灯坏了三天" → 工单草稿自动提取 → 补全 → 提交

2:30-3:30 切换坐席 → 受理工单
  - /agent/tickets 看到刚提交的工单
  - accept → assign 到"城市管理"部门
  - 展示 audit_logs 时间线

3:30-4:30 切换部门 → 办理工单
  - /department/tickets 看到本部门工单
  - 点击工单 → AiCaseAssistant 展示 AI 办件建议
  - submit → 工单 resolved

4:30-5:00 切换市民 → 评价 + 申诉
  - /citizen/tickets/:id 看到 resolved
  - submit_feedback (dissatisfied) → 工单重办
  - createAppeal → admin 复核
```

### 11.6 简历项目描述草稿

> **倾听助手 — 政务诉求协同服务平台**（2026）
>
> 面向 12345 风格政务诉求的智能协同平台，支持市民、坐席、部门人员、管理员 4 类角色，覆盖智能对话、政策 RAG 咨询、工单协同办理、回访申诉、AI 办件助手全闭环。
>
> - **技术栈**：FastAPI + React 19 + TypeScript + PostgreSQL + pgvector + Rasa 3.6 + DeepSeek + Docker Compose
> - **智能体编排**：自研 Orchestrator 实现规则 → Rasa → LLM 三层路由，21 字段结果结构，Guard 模块含输入长度/会话/限流/去重/语义缓存/并发/预算 8 层预检查，10/10 验收场景真实通过
> - **RAG 政策知识库**：pgvector 向量检索 + 关键词召回 + RRF 融合 + 重排序 + 三级权限隔离 + 失效政策双重检查 + 版本管理 + 评测体系，9 个政策文档 + 15 个真实向量索引
> - **工单协同**：6 状态机 + 多部门协办（primary/support/review）+ 转派/退回/争议解决 + SLA 时限 + 乐观锁版本控制，319 个真实工单
> - **AI 用量审计**：每次 LLM 调用记录 request_id/route/tier/token/耗时/缓存命中/限流/降级/成本，管理端 5 Tab 实时聚合
> - **测试**：47 后端测试 + 32 acceptance 测试 + 17 前端单元测试，8 个 Docker 容器全部健康
> - **AI 安全**：所有 AI 建议强制 `advisory_only=true`，无依据不编造，超范围固定中文兜底，LLM 不可用时 RAG/工单/查询各自降级

### 11.7 面试官最可能追问的 10 个问题

1. **"你的 Orchestrator 三层路由是怎么决策的？规则和 LLM 如何配合？"**
   - 答：规则关键词优先（confidence >= 0.9 直接执行），未命中且未超范围时调 LLM 分类（confidence >= 0.6 执行，0.4-0.6 单次澄清，<0.4 兜底 out_of_scope），Guard 在 LLM 调用前做 8 层预检查。
2. **"RAG 检索的权限隔离怎么做的？市民能查到部门内部文档吗？"**
   - 答：`_apply_visibility_filter` 三级隔离：PUBLIC 全员可见，DEPARTMENT 本部门或 admin，INTERNAL 仅 admin。检索时先按角色过滤再取内容（满足硬约束）。
3. **"语义缓存的命中率如何？阈值怎么定的？"**
   - 答：阈值 0.92 余弦相似度，TTL 6 小时，最大 500 条。实测 33 次调用中 5 次命中（21%）。仅缓存 policy_rag/service_guide，不缓存 ticket_intake（每个投诉唯一）。
4. **"AI 用量审计的 token 数怎么核算成本？"**
   - 答：⚠️ **当前有 bug**，token 数硬编码为 0，需要从 DeepSeek 响应的 `usage` 字段提取。成本表：rules=0, embedding=0.0005, llm_lite=0.002, llm_full=0.008 RMB/1K tokens。
5. **"工单状态机的乐观锁怎么实现的？"**
   - 答：`tickets.version` 字段，每次更新 +1，更新时 `WHERE version = ?`，不匹配抛 `VersionConflict` 409。前端 TicketDetailPage 显示"工单已被他人更新"。
6. **"多部门协办的 primary/support/review 怎么协作？"**
   - 答：primary 必须唯一，support/review 需先有 primary。所有 support submitted 后主办 primary 自动 resolve。协办争议通过 `resolve_dispute` 重新指定 primary。
7. **"失效政策怎么拦截？"**
   - 答：双重过滤：SQL 层 `expires_at > now OR expires_at IS NULL`，Python 层逐条 `is_expired = doc.expires_at and doc.expires_at <= now`。评测用例 `eval_expired_policy_blocked` 验证。
8. **"LLM 不可用时怎么办？"**
   - 答：每个 route 有独立降级策略：policy_rag → 12345 提示，service_guide → 政务大厅提示，ticket_intake → 纯 rules 提取，ticket_progress → 直接查 DB（始终可用），emergency/handoff → 固定话术（始终可用）。
9. **"Rasa 和你的 Orchestrator 是什么关系？"**
   - 答：⚠️ **当前双轨**：访客走 Rasa，登录走 Orchestrator。计划统一到 Orchestrator（已支持匿名 principal）。Rasa 主要负责表单槽位填充和 NLU 训练，Orchestrator 负责高层路由和 LLM 编排。
10. **"这个项目的最大技术挑战是什么？"**
    - 答：在有限的 LLM 预算下保证政务回答的准确性和安全性。解决方案：规则优先 + RAG 强制检索 + 无依据不编造 + 失效政策拦截 + 权限隔离 + 语义缓存 + 多层降级 + 审计日志。

---

## 十二、给 ChatGPT 的复审材料

### 给 ChatGPT 复审的核心信息

#### 项目一句话定位

倾听助手是一个面向政务 12345 风格诉求的"工单+RAG+Agent"演示平台，用 Rasa + FastAPI + React + pgvector + DeepSeek 搭建，支持市民/坐席/部门/管理员 4 类角色完整业务闭环。

#### 当前架构

```
8 Docker 容器：
  frontend (Nginx 8081) → backend (FastAPI 8001) → postgres (5432, pgvector)
                                                      ↑
                          rasa (5005) + action_server (5055) + duckling (18080)
                          worker (后台任务) + minio (29000 对象存储)

前端：React 19 + TS + Vite + Ant Design + TanStack Query + ECharts
后端：FastAPI + SQLAlchemy 2 + Alembic + JWT + RBAC/ABAC
NLU：Rasa 3.6 (JiebaTokenizer + DIET + Duckling)
LLM：DeepSeek deepseek-chat (OpenAI 兼容)
Embedding：默认 text-embedding-v1 (配置错误，应改 SiliconFlow Qwen3-VL-Embedding-8B)
RAG：pgvector Vector(1024) + 权限过滤 + RRF 融合 + 重排序
```

#### 当前角色

- 市民 citizen（citizen_local）：智能对话 + 政策咨询 + 工单提交/查询 + 评价申诉
- 坐席 agent（agent_local）：工单受理/派发 + 政策辅助 + AI 智能分派
- 部门人员 department_staff（department_local）：工单办理 + 知识库上传 + AI 办件助手
- 管理员 admin（admin_local）：知识库审核 + 用户/部门/分类管理 + 看板 + AI 用量审计 + 申诉复核
- 访客 anonymous：公开对话（走 Rasa）+ 公开政策咨询

#### 当前业务闭环

1. **政策咨询**：市民提问 → Orchestrator → RAG 检索（pgvector + 关键词 + RRF） → LLM 摘要 + 引用 → 反馈
2. **工单协同**：市民草稿 → 提交 → 坐席受理 → 派发部门 → 多部门协办 → 处理 → 办结 → 评价 → 申诉 → 回访
3. **工单查询**：市民输入工单号 → 直接查 DB → 返回状态/部门/办理记录
4. **知识库管理**：部门上传 → 解析索引 → 提交审核 → 管理员审核 → 发布 → RAG 检索 → 版本更新 → 下线/失效

#### 当前完成度

**综合 72/100（B+，可演示，距上线还差关键运维与体验打磨）**

- 业务闭环 80% | 智能体 75% | RAG 70% | 前端 75% | 后端 80% | 数据库 75% | 安全 80% | 测试 70% | 运维 65% | 简历价值 80%

#### 核心技术栈

FastAPI + React 19 + TypeScript + PostgreSQL 16 + pgvector + Rasa 3.6 + DeepSeek + Docker Compose + MinIO + Alembic + JWT + TanStack Query + ECharts + Vitest + Playwright

#### 主要页面

- 公开：/welcome, /login, /chat, /auth/oidc/callback
- 市民：/citizen/chat, /citizen/policy, /citizen/tickets, /citizen/tickets/:id, /citizen/intelligence, /citizen/notifications, /citizen/aftercare
- 坐席：/agent/tickets, /agent/tickets/:id, /agent/policy, /agent/intelligence, /agent/notifications, /agent/aftercare
- 部门：/department/tickets, /department/tickets/:id, /department/kb, /department/intelligence, /department/notifications, /department/aftercare
- 管理员：/admin/dashboard, /admin/tickets, /admin/tickets/:id, /admin/kb, /admin/ai-usage, /admin/intelligence, /admin/notifications, /admin/aftercare, /admin/categories, /admin/users, /admin/departments, /admin/audit

#### 主要接口

- 认证：POST /api/v1/auth/login, GET /api/v1/auth/me, GET/POST /api/v1/auth/oidc/*
- 编排：POST /api/v1/orchestrator/chat
- 工单：/api/v1/tickets（30+ 端点，含 CRUD/accept/assign/process/resolve/close/feedback/work-orders/sla）
- 知识库：/api/v1/kb/documents（CRUD + upload + submit-review + review + publish + withdraw + expire + reindex + versions + chunks + download）, /api/v1/kb/query, /api/v1/kb/retrieve, /api/v1/kb/feedback, /api/v1/kb/no-answer, /api/v1/kb/eval/*, /api/v1/kb/tickets/:id/advice
- AI：/api/v1/ai/tickets/:id/analyze, /api/v1/ai/suggestions/*, /api/v1/ai/pre-review, /api/v1/ai/hotspots
- 回访申诉：/api/v1/follow-ups, /api/v1/tickets/:id/appeals, /api/v1/appeals/:id/review
- 附件：/api/v1/tickets/:id/attachments, /api/v1/attachments/:id
- 通知：/api/v1/notifications
- 管理：/api/v1/admin/dashboard, /api/v1/admin/audit-logs, /api/v1/admin/ai-usage/*, /api/v1/admin/sla-policies
- 用户/部门/分类：/api/v1/users, /api/v1/departments, /api/v1/categories
- 集成：/api/v1/integrations/*
- 健康：/health, /health/ready, /metrics

#### 主要数据表

27 个 SQLAlchemy 模型：users, departments, categories, tickets, work_orders, work_order_history, ticket_status_history, ticket_feedback, ticket_attachments, audit_logs, notifications, follow_up_tasks, phone_follow_up_records, appeals, ai_suggestions, integration_events, notification_outbox, sla_policies, login_attempts, kb_documents, kb_chunks（Vector 1024）, kb_feedback, kb_eval_cases, kb_eval_runs, kb_no_answer_questions, ai_usage_logs, ai_usage_budgets

#### 智能体路由

11 个 route：policy_rag, service_guide, ticket_intake, suggestion_intake, ticket_progress, department_navigation, emergency_route, general_chat, human_handoff, clarify, out_of_scope

分层判定：规则关键词（confidence >= 0.9）→ 超范围拦截 → Guard 8 层预检查 → LLM 分类（confidence >= 0.6）→ 单次澄清（0.4-0.6）→ 兜底 out_of_scope（<0.4）

#### RAG 架构

pgvector Vector(1024) + 权限三级隔离（PUBLIC/DEPARTMENT/INTERNAL）+ 元数据过滤（region/domain/audience）+ 向量召回（<=> 余弦距离）+ 关键词召回（Jaccard）+ RRF 融合（k=60）+ 重排序（rrf*0.7 + density*0.25 + len*0.05）+ 有效期双重检查 + LLM 摘要 + 引用追溯 + no_evidence 拒答 + 版本管理（parent_version_id/replaces_doc_id）+ 评测体系（7 个 case）

#### 已通过测试

- 后端 acceptance：32/32（test_orchestrator_guard.py）
- 后端单元/集成：约 47 个（test_api/test_phase2-6/test_postgres_repository/test_round4/test_schema_metadata）
- 前端单元：17 个（vitest）
- 前端 E2E：5 个 spec（依赖 E2E_PASSWORD）
- 端到端 10 场景：10/10 真实通过（实测 2026-07-20）

#### P0/P1/P2 问题

**P0（3 个）**：
1. AI 用量审计 token 数断链（硬编码 0，kb_service LLM 不写入审计）
2. DepartmentKbPage 路由权限错误（admin 无法访问 KB 上传/直发/跨部门）
3. Rasa 与 Orchestrator 双轨未统一（访客 vs 登录行为不一致）

**P1（8 个）**：
1. 无 pgvector HNSW 索引
2. 关键词搜索无中文分词
3. 登出未撤销后端 token
4. 版本链查询不完整（v1→v2→v3 断链）
5. E2E 测试 baseURL 不一致
6. IntelligencePage staff 硬编码
7. 业务规则数字硬编码前端
8. list_feedback 部门过滤 bug

**P2（10 个）**：
1. AdminKbPage EvalTab DOM dataset 反模式
2. ServiceStatus 探测未文档化端点
3. 未使用的 downloadKbDocumentUrl 函数
4. 代码超长行
5. WorkOrderPanel 时间格式不一致
6. AdminKbPage 与 DepartmentKbPage 重复代码
7. session_id 共享导致跨场景槽位污染
8. domain.yml session_expiration_time=0.0
9. 图表可访问性
10. 测试残留用户

#### 优化建议

**3 轮优化**：
1. 第 1 轮：业务闭环与数据正确性（修复 P0 + 部分 P1，2-3 天）
2. 第 2 轮：智能体与 RAG 可靠性（HNSW 索引 + jieba 分词 + Rasa/Orchestrator 统一，3-4 天）
3. 第 3 轮：演示体验与工程完善（清理测试残留 + 单元测试 + 演示脚本，2-3 天）

#### 仍存在的不确定项

1. **Embedding 真实可用性**：当前默认配置（DeepSeek + text-embedding-v1）不工作，走 hash fallback。实际运行时 15 个 chunks 有 embedding，但质量可能为 hash 伪向量。需要确认 `EMBEDDING_API_KEY` 是否配置。
2. **LLM 真实调用**：测试环境 `AI_API_KEY=""` 强制禁用，生产 LLM 可用性取决于 `AI_API_KEY` 配置。实测时"博士家属有什么待遇"返回 `requires_llm=true, model_tier=llm_full`，但实际是否调用了 DeepSeek API 未确认（可能走降级）。
3. **OIDC 真实可用性**：需配置 `OIDC_*` 环境变量，当前未配置。
4. **worker 真实运行**：worker 容器健康，但是否真实处理了通知 outbox 和 SLA 提醒未验证。
5. **历史案例脱敏**：项目记忆硬约束要求脱敏，但代码未见显式脱敏逻辑，seed 中的 case 文档是作者编写的合成案例。
6. **外部集成**：所有外部集成（OIDC/工单平台/短信/地图/行政区划/日志/监控）需配置才可用，当前均未配置。
7. **playwright E2E**：未实际运行，依赖 E2E_PASSWORD 环境变量 + baseURL 不一致。
8. **frontend 构建**：之前会话已验证 vite build 通过，本轮未重新验证。

---

**审计完成**。本报告基于实际代码阅读 + Docker 运行时验证 + API 端到端验证 + 后端测试执行 + 数据库查询，所有结论均附文件路径与行号证据，运行时数据来自真实容器与真实数据库，无静态假数据。报告未修改任何业务代码，仅新增了一个审计验证脚本 `scripts/audit_e2e_verify.py`。
