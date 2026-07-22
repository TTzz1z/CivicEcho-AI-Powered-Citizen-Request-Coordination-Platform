# 倾听助手产品基线

## 产品定位

倾听助手是面向市民诉求受理与跨部门协同办理的政务服务演示平台。系统将对话式诉求登记、政策咨询（RAG）、可信工单流转、跨角色办理、附件与审计证据、通知与回访、申诉重办、AI 办件辅助建议整合为可重复部署和验证的单机工程交付。

本项目当前是可运行、可演示的工程化 MVP，所有数据均为演示种子数据；不宣称达到真实政务生产系统的高可用、等保或跨机房灾备标准。外部短信/OIDC/地图/政务平台均为可配置适配器，默认 disabled。

产品必须保持的价值是：业务状态和权限由后端可信控制；所有关键动作可审计；AI 只提供可复核建议（advisory only，三态人工确认）；系统可用固定演示数据稳定复现主闭环。

## 用户角色与权限矩阵

| 能力 | citizen | agent | department_staff | admin |
|---|:---:|:---:|:---:|:---:|
| 创建诉求（表单/对话） | 是 | 是 | 否 | 是 |
| 政策咨询（policy_rag） | 是 | 是 | 是 | 是 |
| 办事指南（service_guide） | 是 | 是 | 是 | 是 |
| 工单进度查询 | 是（本人工单） | 是（协调范围） | 是（本部门） | 是（全部） |
| 受理 / 拒绝 / 派发 | 否 | 是 | 否 | 是 |
| 部门处理 / 退回 / 转派 | 否 | 协调 | 是（本部门） | 是 |
| 提交处理结果（部门 work order submit） | 否 | 否 | 是（本部门任务） | 是 |
| 复核办结（review-resolve → resolved） | 否 | 是 | 否 | 是（正式办结仅 `review-resolve`；旧 `/resolve` 已删除） |
| 市民确认关闭（feedback satisfied → closed） | 是（本人工单） | 否 | 否 | 是（代办结 close） |
| 市民确认 / 评价 / 申诉 | 是（本人工单） | 否 | 否 | 管理审核 |
| 知识库上传 / 审核 / 发布 | 否 | 否 | 是（本部门文档） | 是 |
| 用户 / 部门 / 分类 / SLA 管理 | 否 | 否 | 否 | 是 |
| 审计日志查看 | 否 | 否 | 否 | 是 |
| AI 用量与安全查看 | 否 | 否 | 否 | 是 |
| 外部平台配置 | 否 | 否 | 否 | 是 |
| AI 建议（triage / handling / pre_review） | 否 | 是（分诊：pending/accepted） | 是（办件：本部门 assigned/processing） | 是 |

权限实现集中在后端 `backend/app/authorization.py` 的 `AuthorizationPolicy`：
- `can_view` 控制数据可见性（citizen 看本人、department_staff 看本部门、agent 看协调范围、admin 看全部）。
- `require_transition` 控制动作权限（按角色 × action × 部门归属三元组校验）。
- `apply_query_scope` 把同一数据范围下推到 SQL 查询，保证列表与详情一致。
- 前端路由守卫只负责用户体验，不能替代后端权限校验。

## 核心业务流程

### 1. 市民政策咨询（policy_rag）

```
市民输入问题
  → Orchestrator 规则识别（POLICY_WORDS 命中）
  → 路由 policy_rag
  → KnowledgeBaseService.rag_answer
  → pgvector 语义检索 top-K chunks（embedding_fallback 时回退关键词检索）
  → LLM 生成答案（要求引用 chunks）
  → 返回 answer + citations[]（含 title/doc_number/issuing_authority/excerpt）
  → 若 no_evidence：提示"未检索到相关政策，是否创建咨询工单？"
  → 市民明确确认后才能进入 ticket_intake
```

### 2. 工单全生命周期

```
提交（pending）
  → 坐席受理（accepted） / 拒绝（rejected）
  → 派发责任部门（assigned）
  → 部门开始处理（processing）
  → 部门提交 work_order 结果 → 部门汇总（collaboration_status=awaiting_review）
  → 坐席复核（resolved）
  → 市民评价满意（closed） / 管理员代办结（closed）
  → 市民评价不满意（保持 resolved，不自动重开）
  → 市民提交申诉（appeal submitted）
  → 管理员审核通过（processing，重办）/ 驳回（保持 resolved）
```

每步：版本号乐观锁、`ticket_status_history` 留痕、`audit_logs` 审计、`notifications` 通知（worker 异步投递）。

**citizen 办结路径**：市民不直接调用 `close`，而是通过 `POST /api/v1/tickets/{id}/feedback` 提交评价；`rating=satisfied/mostly_satisfied` 时服务层把状态从 `resolved` 改为 `closed`，`closure_type=citizen_confirmed`。`rating=dissatisfied` 时状态保持 `resolved`，市民需另行提交申诉。

### 3. 角色化 AI 辅助（advisory only）

坐席与部门共用底层 LLM/规则引擎，但 **capability、Prompt、Schema、权限与工单状态** 拆分，避免职责重叠。

| 角色页面 | capability | 允许状态 | 产出重点 | 禁止 |
|---|---|---|---|---|
| 智能分诊与派发 | `triage_assistant` | `pending` / `accepted` | 摘要、分类、紧急度、完整性、部门候选、SLA 建议、受理告知语 | 办结文书、未核实处理结果、自动派发 |
| AI 办件与文书辅助 | `handling_assistant` | `assigned` / `processing` 且本部门 | 核查清单、办理方案、风险、政策要点、回复模板/草稿 | 改分类/改派主办、无事实时写“已处理完成”、自动办结 |

```
工作人员打开对应 AI 页面并输入工单号
  → POST /api/v1/ai/tickets/{id}/analyze（capability=triage_assistant|handling_assistant）
  → 校验角色 + 工单状态 +（部门）归属
  → 生成建议写入 ai_suggestions（不动 ticket.status）
  → 业务采纳：adopted / adopted_with_edits / rejected
  → 模型质量反馈：helpful / not_helpful（不写业务字段）
  → 真实受理/派发/提交办理结果仍在工单详情由人工完成
```

未填写真实办理事实时，`handling_assistant` 只返回带【占位符】的回复模板。
`ticket_advice`（工单详情侧栏）仍可作为部门办件辅助入口，但智能工作台主路径已按上表拆分。

AI 永远不直接调用 `accept`/`assign`/`resolve`/`close` 等状态变更接口。

**两类审核不要混淆：**

| 类型 | 入口 | 作用 | 是否改工单状态 |
|---|---|---|---|
| 通用 AI Suggestion 审核 | 分诊/办件工作台 suggestion 能力 | 质量反馈 helpful/not_helpful；业务采纳 adopted* | 否 |
| 工作人员 KB 办件审核 | `/api/v1/kb/tickets/{id}/advice/review` | 强制 `advice_id`；三态确认；审计写入 snapshot/hash/operator | 否（办结仍走工单动作） |

## 工单状态机图

```mermaid
stateDiagram-v2
    [*] --> pending: 市民/对话创建
    pending --> accepted: agent accept
    pending --> rejected: agent reject
    accepted --> assigned: agent assign
    assigned --> processing: department process
    processing --> processing: department note
    processing --> resolved: agent review_resolve
    resolved --> closed: citizen feedback satisfied / admin close
    resolved --> processing: appeal approved (重办)
    processing --> assigned: department return
    assigned --> processing: transfer / support / review
    rejected --> [*]
    closed --> [*]
```

状态机由 `backend/app/services/ticket_service.py:TRANSITIONS` 字典集中定义，非法转换返回 `BusinessError`，旧版本号返回 `409 VERSION_CONFLICT`。

## AI 能力边界（advisory only，不自动决策）

- 所有 AI 输出必须标记 `advisory_only=true`，不得直接修改工单状态、权限或责任部门。
- AI 建议保存到 `ai_suggestions` 表，与工单状态和版本解耦；每条记录 `provider/model/prompt_version/latency/risk_level/confidence`。
- AI 不调用 `accept`/`reject`/`assign`/`resolve`/`close` 等命名业务动作接口；这些接口必须由人工触发。
- 文书草稿必须由工作人员复核后，才能作为正式处理内容使用。
- 政策咨询（policy_rag）找不到证据时返回 `no_evidence`，不编造答案；市民明确确认后才创建咨询工单，避免误建单。
- 真实模型只允许通过环境变量配置的 OpenAI 兼容接口接入（DeepSeek + SiliconFlow Embedding）。
- 连接器默认关闭；未配置真实 URL 和令牌时，系统明确返回"未配置"，不伪造成功。

## 降级策略

| 场景 | degrade_reason | 行为 |
|---|---|---|
| `AI_API_KEY` 为空 / LLM 超时 / 返回非法 JSON | `llm_unavailable` | Orchestrator 跳过 LLM，policy_rag/service_guide 退化为"仅检索原文 + 引用"，ticket_draft 退化为规则模板 |
| `EMBEDDING_API_KEY` 为空 / embedding 调用失败 | `embedding_fallback` | RAG 检索回退到 PostgreSQL 关键词 + pg_trgm 模糊匹配，仍返回引用但召回率下降 |
| 单用户/平台每日 LLM 调用超出预算 | `budget_exceeded` | Guard 拒绝 LLM 调用，返回降级提示，记录 `budget_exceeded=true` |
| Orchestrator 不可用回退 Rasa / ServiceNow localmode | `orchestrator_unavailable`（前端明示） | **不得**声称已创建真实工单；无 QT 编号时前端 `sanitizeRasaFallbackText` 改写成功措辞；正式办结仅 `review-resolve` |

所有降级路径统一写入 `ai_usage_logs`，`degraded=true` + `degrade_reason` 标注原因，管理员可在 AI 用量页清晰区分真实调用与降级调用。

## 已完成能力边界与非目标

现行能力基线（详见代码与 CI）：

- 业务闭环：状态机、权限、SLA、通知、申诉、回访。
- AI 可信度：`ai_usage_logs` 审计链路、policy_rag 不建单、service_guide 接 RAG、多意图、session 隔离、三态确认、降级标记。
- 知识库索引：重建失败时保留旧索引；成功后原子切换，避免已发布政策短暂不可检索。
- 可复现验收：真实 Token 证据、引用字段完整、演示环境、全量测试与文档。

不做 Kubernetes、多机高可用、跨机房灾备、复杂 BPMN、多租户 SaaS、原生 App/小程序、自动电话外呼，以及自动行政决策、自动拒绝、自动派发或自动办结。不训练或微调模型。

## 交付与验收目标

- 一条命令启动完整演示环境，四角色用固定演示账号完成主闭环。
- 默认测试、迁移检查和 E2E 有真实通过证据（详见 [docs/final-test-report.md](docs/final-test-report.md)）。
- 真实 LLM 调用产生 `ai_usage_logs` 记录，`total_tokens > 0`，`provider=deepseek`。
- 降级路径有明确 `degrade_reason`，演示不中断。

本文件与 `ENGINEERING.md`、`README.md`、`docs/final-test-report.md` 共同构成产品与工程基线；若描述与当前代码冲突，以可运行代码与已验证测试结果为准。
