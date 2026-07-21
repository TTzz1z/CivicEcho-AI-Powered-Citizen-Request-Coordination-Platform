# 倾听助手面试追问清单

> 18 个面试常见追问及参考答案，覆盖架构、AI 可信度、降级、权限、状态机、审计链路等核心话题。所有答案基于项目实际代码与已验证行为，不夸大。

## Q1：为什么选择 pgvector 而不是专用向量数据库（Qdrant / Milvus / Weaviate）？

**答**：
1. 当前规模（演示 KB 文档数十篇，chunks 数千条）不需要专用向量库的水平扩展能力，pgvector 在 PostgreSQL 单实例上完全够用。
2. 向量检索与业务查询（tickets、kb_documents、audit_logs）共用同一事务、同一连接池，避免分布式事务与跨库 join 复杂度。
3. 知识库可见性过滤（PUBLIC/DEPARTMENT/INTERNAL）需要在 embedding 检索前先按 Principal 过滤文档集，pgvector 可以在同一 SQL 中完成"WHERE visibility IN (...) ORDER BY embedding <=> query LIMIT K"，专用向量库通常需要二次过滤。
4. 备份恢复统一：PostgreSQL + MinIO 联合备份即可覆盖向量数据，不需要额外的向量库备份方案。
5. 不引入 Qdrant/Elasticsearch/Kafka 是 `ENGINEERING.md` 的明确约束，避免技术栈膨胀。

代价：超大规模（百万级 chunks）时 pgvector HNSW 索引构建慢，需要切换到 IVFFlat 或迁移专用库。当前未达到该量级。

## Q2：RAG 如何保证答案有依据（不编造）？

**答**：
1. **检索先行**：`KnowledgeBaseService.rag_answer` 先做 pgvector 语义检索 top-K chunks，没有命中就返回 `no_evidence=true`，不调用 LLM 生成。
2. **prompt 约束**：LLM prompt 显式要求"只能基于提供的 chunks 回答，不能编造"，并在答案中标注引用。
3. **引用字段强制**：每条 citation 必须包含 `title`、`doc_number`、`issuing_authority`、`excerpt` 四个字段，前端校验后渲染。缺字段则该 citation 不展示。
4. **过期策略阻断**：`kb_documents.expires_at` 过期后文档不参与检索，避免引用已失效政策。
5. **可见性过滤**：检索前按 Principal 过滤文档集，低权限用户不会拿到高权限文档的引用。
6. **无证据回退**：若 `no_evidence`，系统提示"未检索到相关政策，是否创建咨询工单？"——市民明确确认后才进入 `ticket_intake`，不静默建单。

## Q3：AI 审计链路如何设计？为什么是 10 种 capability？

**答**：
审计链路的核心是 `ai_usage_logs` 表 + `AiUsageRecorder` 单一写入路径。设计原则：

1. **每次模型调用都写一行**（含 LLM、embedding、降级、失败、缓存命中），不静默丢弃。
2. **Tokens 必须来自模型 `usage` 块**，绝不硬编码 0；模型不返回 usage 时记 `usage_unavailable=true`，不当作 0 tokens 处理。
3. **RAG 检索与 LLM 生成分开记**：一次市民请求可能产生 1 条 `embedding_query` + 1 条 `policy_rag`，不合并为单条模糊记录。
4. **降级路径同样留痕**：`degraded=true` + `degrade_reason` 标注原因。

10 种 capability 覆盖系统中所有真实模型调用入口：
- `orchestrator_classify`（意图分类）
- `ticket_draft`（草稿字段提取）
- `policy_rag` / `service_guide`（RAG 答案生成）
- `ticket_advice` / `ai_analyze` / `pre_review`（工单办理建议）
- `embedding_index` / `embedding_query` / `semantic_cache`（embedding 调用）

这样设计的好处：管理员 AI 用量页可以按 capability 维度看到"哪类调用最贵、哪类最容易降级、哪类命中率最高"，而不只是看到"调了 N 次模型"。

## Q4：session_id 隔离解决了什么问题？

**答**：
Round 2 之前 Orchestrator 用 `user:default` 作为 guard 缓存的 key，导致两个问题：

1. **会话串扰**：市民在社保咨询会话里得到的 policy 上下文，会被下一次路灯报修会话继承，AI 草稿可能错误携带政策字段。
2. **Guard 计数错乱**：限流、去重、并发、每日预算都按 `user:default` 统计，无法区分不同会话的轮次。

Round 2 改为强制要求 caller 传 `session_id`（缺失时生成一次性 id `user:s-<uuid>`），保证：
- 每个会话有独立的 turn 计数。
- 缓存的语义检索不跨会话复用。
- 同一用户的多会话互不影响。
- `ai_usage_logs.session_id` 字段可用于按会话聚合分析。

## Q5：三态人工确认为什么不能自动派发？

**答**：
AI 在工单分类、责任部门建议、文书草稿等场景的准确率不到 100%，自动派发会带来三个风险：

1. **误派导致 SLA 失效**：路灯报修误派到教育服务，SLA 计时按错误部门的时限计算，市民体验受损。
2. **责任不清**：自动派发后部门不知情，承办人员看到的是"系统派单"而非"坐席确认"，权责混乱。
3. **监管缺位**：政务场景要求每个状态变更可追责到具体人，AI 不能作为责任主体。

三态确认（accept / modify / reject）让人工保留最终决定权：
- accept：AI 建议正确，坐席快速通过，省去重复录入。
- modify：AI 建议方向对但细节错（如分类正确但部门错），坐席修改后提交。
- reject：AI 建议完全错误，坐席手动选择。

AI 永远不调用 `accept`/`assign`/`resolve`/`close` 等命名业务动作接口，只写 `ai_suggestions` 表（`advisory_only=true`）。

## Q6：降级机制如何统一标记？

**答**：
所有降级路径走 `AiUsageRecorder` 单一写入路径，统一标记在 `ai_usage_logs` 表：

| 字段 | 取值 | 用途 |
|---|---|---|
| `degraded` | true/false | 是否走了降级路径 |
| `degrade_reason` | `llm_unavailable` / `embedding_fallback` / `budget_exceeded` / NULL | 降级原因代码 |
| `budget_exceeded` | true/false | 是否因预算超额（与 degraded 分开，便于报表区分） |
| `rate_limited` | true/false | 是否命中限流 |
| `usage_unavailable` | true/false | 模型是否未返回 usage 块（不当作 0 处理） |
| `embedding_fallback`（kb_chunks 表） | none / fallback_used / primary_failed | chunk 维度的 embedding 回退标记 |

管理员 AI 用量页可按 `degrade_reason` 筛选，清晰区分真实调用与降级调用，不会把降级路径的 0 tokens 算作"模型便宜"。

## Q7：工单状态机如何防止非法状态转换？

**答**：
状态机集中在 `backend/app/services/ticket_service.py:TRANSITIONS` 字典：

```python
TRANSITIONS = {
    "pending": {"accept": "accepted", "reject": "rejected"},
    "accepted": {"assign": "assigned"},
    "assigned": {"process": "processing"},
    "processing": {"note": "processing", "resolve": "resolved"},
    "resolved": {"close": "closed", "process": "processing"},
}
```

防护有三层：

1. **状态边校验**：服务层查 `TRANSITIONS[current_status].get(action)`，找不到目标动作就抛 `BusinessError`，拒绝转换。
2. **角色校验**：`AuthorizationPolicy.require_transition` 检查 principal.role × action × department_id 三元组，越权抛 `PermissionDenied`。
3. **版本号乐观锁**：每次状态变更要求客户端提交读取时的 `version`，服务端在同一事务内 `WHERE version = ?`，不一致返回 `409 VERSION_CONFLICT`，避免多人并发覆盖。

非法转换示例：`closed → accepted` 直接抛错；`pending → assigned`（跳过 accept）抛错；`agent` 角色 `resolve` 抛 403。

## Q8：通知幂等键为什么需要 6 个字段？

**答**：
`notifications.event_key` 是唯一约束的幂等键，由 6 个字段拼接而成，确保同一业务事件不会重复生成通知：

1. `event_type`（如 `ticket_accepted`）
2. `ticket_id`（关联工单）
3. `recipient_user_id`（接收人）
4. `actor_user_id`（触发者）
5. `operation_type` 或 `sequence`（同一事件不同轮次，如重办 round）
6. `channel`（in_app / email / sms，预留多通道）

为什么 6 个：少一个会导致重办场景重复投递（如 `ticket_id + event_type` 在第二次 resolve 时被认为重复）；多一个会过度区分，导致同事件被分发给同一用户多次。

幂等键在 Repository 层 `INSERT ... ON CONFLICT (event_key) DO NOTHING`，重复写入返回旧行，保证 worker 重试不会产生重复通知。

## Q9：知识库可见性如何按角色过滤？

**答**：
`kb_documents.visibility` 三态：

- `PUBLIC`：所有角色可见（含未登录访客，但有速率限制）。
- `DEPARTMENT`：仅 `department_id` 匹配的部门人员 + admin 可见。
- `INTERNAL`：仅 admin + 上传者本人可见。

实现位置在 `KnowledgeBaseService`：

1. **检索前过滤**：先按 Principal 构造可见文档集 SQL（`WHERE visibility = 'PUBLIC' OR (visibility = 'DEPARTMENT' AND department_id = ?) OR ...`），再做 embedding 检索。
2. **详情校验**：单文档 API 也走 `AuthorizationPolicy`，越权访问返回 404（不返回 403 避免泄露存在性）。
3. **审核流程隔离**：DRAFT / REVIEWING / REJECTED 状态文档仅上传者 + 审核员 + admin 可见，普通部门人员看不到未发布文档。
4. **RAG 引用安全**：若低权限用户查询的语义命中了高权限文档的 chunk，该 chunk 不会进入 LLM prompt，避免泄露。

## Q10：service_guide 和 policy_rag 的路由边界？

**答**：
两者都是 RAG + LLM 生成答案，但语义边界不同：

| 路由 | 触发关键词 | 数据源 | 答案形态 |
|---|---|---|---|
| `policy_rag` | "政策/补贴/福利/待遇/社保/公积金/入学/落户/人才/医保/养老/残疾/优抚/退伍" | `kb_type=policy` 文档 | 解释政策适用范围、标准、条件 |
| `service_guide` | "怎么办/如何办理/需要什么材料/去哪里办/办理流程/办理条件/需要什么证件/怎么申请/在哪办/手续" | `kb_type=guide` 文档 | 给出办理步骤、材料清单、办理地点 |

边界设计：
1. policy_rag 不建单（市民咨询政策后不直接转工单，除非明确说"我要创建咨询工单"）。
2. service_guide 接 RAG：找到指南就返回，找不到返回 `no_evidence` 提示建单。
3. 两者命中相同文档时按关键词优先级裁决（service_guide 关键词更具体，优先匹配）。
4. 多意图场景（"路灯坏了怎么办"）按 `REFLECT_WORDS` 判断：若仅问"怎么办"走 service_guide；若包含"反映/不给办/推诿"等反映性词则触发 ticket_intake。

## Q11：多意图检测如何避免误建单？

**答**：
Round 2 引入 `REFLECT_WORDS`（反映/不合理/不规范/不给办/推诿/踢皮球/投诉窗口 等）区分"咨询"与"反映诉求"：

1. **纯咨询**："路灯坏了怎么办" → service_guide，不建单。
2. **纯投诉**："幸福路路灯坏了三天没人修" → ticket_intake，建单。
3. **多意图**："路灯坏了怎么办，窗口不给办" → 同时识别 service_guide + ticket_intake，但优先建单（市民已表达不满），同时返回办理指南作为参考。

避免误建单的关键：
- `policy_rag` 路由永不建单，即使市民说"我要咨询政策"也不进入 `ticket_intake`。
- 只有市民明确说 `CREATE_CONSULTATION_TICKET_WORDS`（如"创建咨询工单"）才在 `no_evidence` 后建咨询工单。
- 低置信度内容走 `clarify` 路由，反问市民澄清意图，不直接建单。

## Q12：Orchestrator 的分层路由设计（规则→OOD→LLM）？

**答**：
`OrchestratorService.process` 三层流水线：

1. **Step 1 规则识别**（`_rule_detect`）：基于关键词正则匹配 10 个路由（greet/help/emergency/ticket_id/handoff/policy_rag/service_guide/ticket_intake/suggestion_intake/ticket_progress），confidence≥0.9 直接执行，零 LLM 成本。
2. **Step 2 Guard.check**：输入长度 / 限流 / 去重 / 并发 / 预算 / 语义缓存判定。命中语义缓存直接返回，不调模型。
3. **Step 3 必要时调 LLM**：规则不命中或低置信度时调用 `llm_lite` 模型做 OOD（out-of-domain）分类，决定是否进入业务路由或 `out_of_scope` 兜底。

设计目标：
- 简单问候、感谢、帮助说明走模板，不调模型。
- 写代码、写论文、娱乐闲聊等无关问题用固定中文兜底回复，不进入 LLM 生成。
- 真正业务咨询才走 embedding + LLM，控制成本。

## Q13：语义缓存如何避免重复 RAG 调用？

**答**：
`OrchestratorGuard._cache_lookup_semantic` 实现语义缓存：

1. **缓存键**：用户输入的 embedding 向量 + route（policy_rag / service_guide）。
2. **存储**：`ai_usage_logs` 表中 `capability=semantic_cache` 记录命中标记，缓存内容存进程内 + 持久化辅助。
3. **相似度阈值**：`DEFAULT_CACHE_MIN_SIMILARITY = 0.92`，余弦相似度低于阈值不命中。
4. **TTL**：`DEFAULT_CACHE_TTL_SECONDS = 6 * 3600`（6 小时），过期失效。
5. **容量上限**：`DEFAULT_CACHE_MAX_ENTRIES = 500`，LRU 淘汰。

不缓存的场景：
- `ticket_intake` / `suggestion_intake`：每个投诉/建议内容唯一，不缓存。
- `general_chat` / `clarify`：低价值对话，不缓存。
- 写入操作（建单、状态变更）：永不缓存。

效果：市民重复问"社保补贴政策"在 6 小时窗口内命中缓存，不重复调 embedding + LLM，`ai_usage_logs` 记录 `cache_hit=true, total_tokens=0`。

## Q14：为什么 AI 建议是 advisory_only？

**答**：
三个核心理由：

1. **责任归属**：政务场景要求每个状态变更可追责到具体人，AI 不能作为责任主体。AI 建议写入 `ai_suggestions` 表，记录 `provider/model/prompt_version`，但工单状态变更（`ticket_status_history`）记录的是 `operator_user_id`（人）。
2. **准确率边界**：AI 在分类、责任部门建议、文书草稿上的准确率不到 100%，自动决策会放大错误。advisory only 让人工保留最终决定权，AI 仅做"草稿 + 风险提示"。
3. **审计可回放**：每条 AI 建议有 `input_fingerprint`（输入哈希）和 `result_json`（输出原文），审计时可重现为什么 AI 给出该建议；若自动决策，AI 的"黑盒"无法解释为什么办结了某工单。

工程实现：AI 不调用 `/api/tickets/{id}/accept` 等状态变更接口；`ai_suggestions.review_decision` 字段记录人工的 `accept/reject/modify` 决定，但即使 `accept`，工单状态变更仍需人工点确认按钮。

## Q15：request_id 如何贯穿全链路？

**答**：
`request_id_context`（contextvar）在 FastAPI 中间件层注入：

1. **入口**：每个 HTTP 请求从 `X-Request-ID` 头读取 request_id；无头时生成 `uuid4().hex`。
2. **结构化日志**：每条日志带 `request_id` 字段，stdout 中可按 `request_id` 串联。
3. **audit_logs.request_id**：业务动作（accept/assign/resolve/close 等）写入审计时携带。
4. **ai_usage_logs.request_id**：每次模型调用（含降级、失败、缓存命中）记录同一 request_id。
5. **integration_events.request_id**：外部集成事件（OIDC/SMS/工单平台）携带。
6. **响应头**：FastAPI 中间件把 request_id 写回 `X-Request-ID` 响应头，前端可关联。

效果：管理员在审计页拿到一个 `request_id`，可以在 AI 用量页查到该请求触发的所有模型调用，在 integration_events 查到外部事件，在结构化日志查到中间过程，形成"市民请求 → 状态变更 → AI 调用 → 通知投递 → 外部事件"完整链路。

## Q16：为什么 Rasa 不直接写数据库？

**答**：
1. **对话 Action 不是业务真相源**：Rasa tracker 可能因重试、超时、并发产生重复或部分写入，直接落库会放大一致性问题。
2. **统一权限与审计**：Backend 集中处理状态机、授权、幂等、事务和审计，Action Server 通过服务令牌调用受限接口，不继承用户权限，所有写操作走同一审计链路。
3. **多入口一致**：Web 页面、对话入口、外部集成共享同一套业务规则，避免对话路径绕过权限校验。
4. **Rasa 重启不丢业务**：Rasa tracker 持久化到 PostgreSQL（仅会话状态），即使 Rasa 重启，已落库的工单状态不丢失；新会话从最新状态恢复。

## Q17：如何防止重复创建工单？

**答**：
1. **idempotency_key 唯一约束**：`tickets.idempotency_key` 字段唯一，Repository `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`，重试返回原工单。
2. **对话层不假装成功**：Action Server 调用 Backend 失败时不向 Rasa 返回"已创建"，而是抛错让对话进入重试或人工接管。
3. **去重窗口**：OrchestratorGuard 的 `DEFAULT_DEDUP_WINDOW_SECONDS = 30`，同一用户 30 秒内相同文本不重复处理。
4. **唯一工单号**：`ticket_id` 格式 `QT<yyyymmdd><8位sequence>`，sequence 由数据库原子递增，保证全局唯一。

## Q18：为什么用版本号乐观锁而不是悲观锁？

**答**：
1. **政务场景读多写少**：工单详情页被市民、坐席、部门、管理员频繁查看，悲观锁会阻塞读操作，影响体验。
2. **多人协同常态**：坐席 A 在派发时，部门 B 可能在看工单详情，悲观锁会阻塞 B 的查看。
3. **冲突成本低**：真正的状态变更冲突（两人同时点派发）概率低，发生时返回 409 让前端刷新即可，不需要数据库层阻塞。
4. **跨服务一致**：Action Server 通过 HTTP 调 Backend，无法持有数据库连接的悲观锁；版本号在 HTTP body 中传递，跨服务一致。

实现：`tickets.version` 字段，每次状态变更 `UPDATE ... SET version = version + 1 WHERE ticket_id = ? AND version = ?`，affected_rows=0 即冲突，返回 409。

## Q19：worker 的通知 outbox 如何保证可靠投递？

**答**：
`notification_outbox` 表 + worker 后台扫描 + 指数退避重试：

1. **写入**：业务事件触发时同步写 `notifications`（用户可见）+ `notification_outbox`（投递队列）。
2. **扫描**：worker 每 60 秒扫描 `notification_outbox WHERE status='pending' AND next_retry_at <= now()`。
3. **投递**：调用通道适配器（in_app / email / sms），成功标记 `sent_at`，失败增加 `retry_count`，按指数退避更新 `next_retry_at`。
4. **重试上限**：`max_retries=3`，超限标记 `status='failed'`，记录 `error_message`。
5. **幂等键**：`notification_outbox.idempotency_key` 唯一，避免同一事件被多次入队。
6. **不依赖打开页面**：通知由 worker 主动投递，即使用户不打开通知页也会收到 in_app 通知。

## Q20：如果上线，第一批要补什么？

**答**：
1. **外部秘密管理**：把 `JWT_SECRET` / `AI_API_KEY` / `SERVICE_API_TOKEN` 等从 `.env` 迁到 Vault / AWS Secrets Manager / 阿里云 KMS。
2. **TLS/WAF/可信反代**：Caddy 已支持 HTTPS，生产补充 WAF、CDN、防爬虫。
3. **PostgreSQL 托管高可用**：迁移到 RDS / PolarDB / 阿里云 PG，主备自动切换。
4. **集中日志告警**：把容器 stdout 接到 ELK / Loki + Grafana，配置 SLO 告警。
5. **限流迁移**：登录限流从 Backend 进程内迁到 Redis 共享限流或网关层。
6. **OIDC / 组织账号**：接入真实 SSO，禁用 `*_local` 演示账号。
7. **对象存储**：MinIO 迁到 OSS / S3，开启版本控制与跨区域复制。
8. **备份演练**：PostgreSQL + MinIO 联合备份恢复，RTO/RPO 演练。
9. **容量测试**：模拟市民峰值并发（如政策发布期间），测 SLA 扫描与 worker 投递能力。
10. **灰度发布**：CI/CD + 蓝绿或金丝雀，避免大版本一次性上线。

不立即做：拆微服务（领域与团队规模不足）、K8s（单机 Compose 已够用）、训练/微调模型（DeepSeek + 规则降级已满足需求）。
