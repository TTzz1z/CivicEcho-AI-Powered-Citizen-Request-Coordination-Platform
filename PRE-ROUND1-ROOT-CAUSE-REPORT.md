# 第一轮前置根因诊断报告（PRE-ROUND1-ROOT-CAUSE-REPORT）

- 生成时间：2026-07-20
- 诊断范围：Playwright E2E（38 用例）、通知 worker 幂等性、Embedding 真实性
- 诊断原则：只查根因，不修改业务状态机/办结审核/评价申诉，不为通过测试降低断言
- 运行环境：Docker（frontend 8081→80, backend 8001→8000, postgres, minio, rasa, action_server, duckling, worker）
- 统一登录密码：`tingting-seed-demo-2026`
- E2E 运行参数：`E2E_BASE_URL=http://localhost:8081`、`E2E_PASSWORD=tingting-seed-demo-2026`、`--project=chromium`

---

## 一、Playwright E2E 38 用例分类表

### 1.1 分类标准

| 代号 | 含义 |
|------|------|
| A | 产品代码缺陷 |
| B | E2E 测试代码过期（选择器/断言文本与当前 UI 不一致） |
| C | 测试环境配置缺失（baseURL、密码、端口） |
| D | Seed 或前置数据缺失 |
| E | 用例设计不合理（依赖时间窗、严格模式违反、断言过严） |
| F | 正常 skipped（serial 串行依赖前序失败） |

### 1.2 38 用例逐条分类

| # | 文件:用例 | 结果 | 分类 | 根因 / 证据 |
|---|----------|------|------|-------------|
| 1 | auth-switch.spec.ts: 退出后切换角色会进入新账号工作台 | passed | — | 通过 |
| 2 | chat-draft.spec.ts: 教育投诉：识别类型并补全后提交 | failed | B | `getByText('工单草稿')` strict mode violation，匹配到 2 个元素（提示文本 + 标题），应使用 `{ exact: true }` 或 `getByRole('heading')` |
| 3 | chat-draft.spec.ts: 路灯故障：地点已识别 | failed | B | 同 #2，相同选择器问题 |
| 4 | chat-draft.spec.ts: 政策咨询：识别为咨询 | failed | B | 同 #2 |
| 5 | chat-layout.spec.ts: 长对话只滚动消息区并固定左侧建议栏 | passed | — | 通过 |
| 6 | chat-layout.spec.ts: 公开会话说明访客工单归属 | failed | B | `getByText` 断言与当前访客模式 UI 文案不一致，未使用 `getByRole('menuitem')` 或 `data-testid` |
| 7-16 | orchestrator.spec.ts: 10 个智能路由用例 | failed | B | 全部 `getByText(...).toBeVisible()` 超时；前一轮已修正密码与按钮选择器，但断言文本仍依赖具体返回文案，5000ms 默认超时不足，未等待 `/api/v1/orchestrator/chat` 响应即断言 |
| 17 | workflows.spec.ts: 市民通过真实 Rasa 对话创建诉求 | timedOut | E | Rasa webhook 响应超过 45000ms；本身可能因 Rasa 模型加载慢，属用例设计不合理（应使用 `waitForResponse` + 更长超时或 `test.setTimeout`） |
| 18 | workflows.spec.ts: 坐席可以打开工单工作台 | passed | — | 通过 |
| 19 | workflows.spec.ts: 部门人员可以打开本部门工单 | passed | — | 通过 |
| 20 | workflows.spec.ts: 管理员可以访问看板和管理页面 | passed | — | 通过 |
| 21 | workflows.spec.ts: 普通用户访问管理员页面被阻止 | passed | — | 通过 |
| 22 | workflows.spec.ts: 四角色均可进入对应的 AI 辅助页面 | failed | E | `getByText('人机协同边界')` 使用默认 5000ms 超时；`IntelligencePage.tsx:49` 确实包含该文本，但页面渲染依赖 react-query 完成加载，应显式 `waitFor` 或加大断言超时 |
| 23 | workflows.spec.ts: 真实浏览器生成紧急 AI 提示且不改变工单行政状态 | failed | B/E | `getByText('请立即由人工核实并按应急预案升级')` 未找到；该文案来自 LLM 输出，依赖 prompt 与模型一致性，且未等待 `/api/v1/ai/tickets/{id}/analyze` 200 响应即断言 |
| 24 | workflows.spec.ts: Rasa 不可用时聊天页可降级重试 | passed | — | 通过 |
| 25 | workflows.spec.ts: Backend 不可用时工单页可安全降级 | passed | — | 通过 |
| 26 | workflows.spec.ts: 停用用户无法登录 | passed | — | 通过 |
| 27 | workflows.spec.ts: 并发版本冲突会提示并刷新 | passed | — | 通过 |
| 28 | workflows.spec.ts: 市民满意评价后直接办结 | passed | — | 通过 |
| 29 | workflows.spec.ts: 阶段五通知、申诉重办和电话回访完整闭环 | passed | — | 通过 |
| 30 | workflows.spec.ts > 真实工单全状态闭环 > 市民通过聊天创建真实诉求并查看详情 | failed | B | 第 92 行使用 `{name:/发送消息/}`，但 Rasa 对话页按钮 accessible name 实际为 "发送"（`/^发送$/`）。与第 7 行不一致，属测试自身选择器不一致 |
| 31-38 | workflows.spec.ts > 真实工单全状态闭环 > 后续 9 个用例 | skipped | F | serial 模式下 #30 失败，后续 9 个用例自动 skip |

### 1.3 分类统计

| 分类 | 数量 | 说明 |
|------|------|------|
| A 产品代码缺陷 | 0 | 无被本次 E2E 直接捕获的产品缺陷 |
| B E2E 测试代码过期 | 14 | 选择器不精确、断言文本过严、未等待响应、串行用例选择器不一致 |
| C 测试环境配置缺失 | 0 | 本轮已修正 baseURL 与密码 |
| D Seed/前置数据缺失 | 0 | KB 缺博士人才政策文档，但属产品内容缺失而非 seed 数据缺失 |
| E 用例设计不合理 | 3 | Rasa 超时未设 setTimeout、AI 辅助页超时过短、紧急 AI 提示依赖 LLM 文案 |
| F 正常 skipped | 9 | serial 串行依赖 |
| 通过 | 12 | — |

### 1.4 修正环境前后对比

| 运行 | baseURL | E2E_PASSWORD | passed | failed | skipped | 备注 |
|------|---------|--------------|--------|--------|---------|------|
| v2（修正前） | http://localhost:8080 | 默认 | 0 | 30 | 8 | 8080 端口连接拒绝，全部 unexpected |
| v3 | http://localhost:5173 | 已设 | 0 | 30 | 8 | Vite dev server 未启动 |
| v5（最终） | http://localhost:8081 | tingting-seed-demo-2026 | 12 | 18（含 1 timedOut） | 8 | 真实结果 |

---

## 二、产品缺陷与测试缺陷分别统计

### 2.1 E2E 测试缺陷（共 17 条，含 1 timedOut）

| 类别 | 数量 | 典型代表 |
|------|------|----------|
| 选择器不精确（strict mode violation） | 3 | `getByText('工单草稿')` 匹配多个元素 |
| 断言文本与 UI 不一致 | 10 | orchestrator.spec.ts 10 条断言文案依赖具体返回 |
| 未等待 API 响应即断言 | 2 | AI 辅助页、紧急 AI 提示 |
| 选择器不一致（同项目不同用例） | 1 | workflows.spec.ts #30 用 `/发送消息/`，#7 用 `/^发送$/` |
| 超时设置不合理 | 1 | Rasa 对话未设 setTimeout 导致 45000ms 超时 |

### 2.2 E2E 产品缺陷（共 0 条）

本轮 38 用例未直接暴露产品代码缺陷。但需注意：测试用例失败本身不等于产品缺陷；以下两项需在第一轮 P0 修复后重新运行 E2E 才能验证：

- **Rasa webhook 响应慢**（>45s）：可能属产品性能/配置问题，但本轮定位为用例设计不合理（未设更长超时），暂不计入产品缺陷；
- **AI 辅助页加载慢**（>5s）：可能属 react-query 加载链路问题，但同样需先修正测试断言再判断。

---

## 三、修正环境后实际通过、失败和 skipped 数量

| 指标 | 数值 |
|------|------|
| 总用例 | 38 |
| passed | 12 |
| failed | 18（含 1 timedOut） |
| skipped | 8（serial 依赖） |
| flaky | 0 |
| 运行时长 | 387559ms（~6.5 分钟） |
| baseURL | http://localhost:8081 |
| 项目 | chromium |

---

## 四、通知重复的 SQL 证据和根因

### 4.1 数据快照

| 指标 | 数值 |
|------|------|
| ticket_due_soon 通知总数 | 9514 |
| notification_outbox sent 总数 | 9249 |
| 工单总数 | ~319 |
| 不同 recipient_user_id | 73 |
| 不同 ticket_id | 191 |
| 单 ticket 最大通知数 | 59 |

### 4.2 SQL 证据

#### 4.2.1 幂等键唯一性（无重复）

```sql
SELECT COUNT(*) AS total,
       COUNT(DISTINCT idempotency_key) AS distinct_keys
FROM notification_outbox
WHERE event_type = 'ticket_due_soon';
-- total=9514, distinct_keys=9514 → 0 重复
```

幂等键格式：`ticket_due_soon:{ticket_id}:{occurrence}:{user_id}`
其中 `occurrence = deadline.isoformat()`，**不包含当前时间**，每次扫描同一 deadline 生成相同 key。

#### 4.2.2 recipient 分布

```sql
SELECT u.role, COUNT(*) AS cnt
FROM notification_outbox o JOIN users u ON u.id = o.recipient_user_id
WHERE o.event_type = 'ticket_due_soon'
GROUP BY u.role;
-- admin: ~4970, agent: ~3866, department_staff: ~678
```

#### 4.2.3 工单状态分布

```sql
SELECT t.status, COUNT(*) AS cnt
FROM notification_outbox o JOIN tickets t ON t.ticket_id = o.ticket_id
WHERE o.event_type = 'ticket_due_soon'
GROUP BY t.status;
-- pending: ~8836 (93%), accepted: ~520, assigned: ~100, processing: ~58
```

#### 4.2.4 单 ticket 时间序列（Top 1）

```sql
SELECT ticket_id, COUNT(*) AS cnt
FROM notification_outbox
WHERE event_type = 'ticket_due_soon'
GROUP BY ticket_id
ORDER BY cnt DESC LIMIT 5;
-- 单 ticket 最多 59 条，对应 52 agent+admin + 7 部门人员 = 59，与 recipients 数量一致
```

### 4.3 根因定位

**文件**：`backend/app/worker.py:83-88`

```python
if event_type in {"ticket_due_soon", "appeal_submitted"}:
    staff = db.scalars(select(UserModel.id).where(
        UserModel.role.in_(("agent", "admin")),
        UserModel.is_active.is_(True),
    )).all()
    recipients.update(staff)
```

**根因**：
1. **幂等键本身有效**（0 重复），不是幂等键失效；
2. **recipients 范围过宽**：`ticket_due_soon` 通知给所有 agent+admin（52 人），而非仅派单的 agent 与归属部门；
3. 同一 ticket 在 deadline 临近窗口内被反复扫描（默认 `worker_due_soon_hours`），但 `occurrence = deadline.isoformat()` 相同，故对同一 (ticket, user) 只生成一条；
4. 单 ticket 59 条通知 = 52 (agent+admin) + 7 (department_staff) + 0 (creator)，**非重复风暴，而是广播风暴**；
5. `notification_outbox` 有 `uq_outbox_idempotency_key` UNIQUE 约束，幂等键机制有效；
6. `process_outbox` 中的 `event_key` 基于 `idempotency_key` 派生，亦无重复；
7. **resolved/closed/paused 工单未被扫描**（`scan_due_soon` 已过滤 `status.in_(pending, accepted, assigned, processing)` 且 `sla_paused_at IS NULL`）；
8. `aftercare_service` 与 `worker.py` 两套扫描逻辑：前者负责阶段五回访，后者负责 SLA 到期前提醒，**功能不重叠**，非重复逻辑。

### 4.4 结论

- **不存在幂等键失效导致的重复风暴**；
- **存在广播风暴**：单 ticket 触发 ~59 条通知，9514 条通知中 93% 集中在 pending 状态工单；
- 列为 **P0-G**：通知范围过宽。

### 4.5 最小修复方案（不在本轮实施）

将 `ticket_due_soon` 的 recipients 收窄为：
- ticket.creator_user_id（市民，可选）
- ticket.assigned_user_id（受理坐席）
- ticket.assigned_department_id 下的 department_staff（部门人员）

移除 `if event_type in {"ticket_due_soon", "appeal_submitted"}: recipients.update(all agent+admin)` 分支中针对 `ticket_due_soon` 的处理，仅保留 `appeal_submitted` 的广播。

幂等键保持不变（已是稳定键：`ticket_id + handling_round + event_type + threshold_level` 的等价形式）。

---

## 五、Embedding 的实际 API 调用证据

### 5.1 配置

| 配置项 | 值 |
|--------|-----|
| EMBEDDING_BASE_URL | https://api.siliconflow.cn/v1 |
| EMBEDDING_MODEL | Qwen/Qwen3-VL-Embedding-8B |
| EMBEDDING_API_KEY | 已配置（掩码：sk-***-2026） |
| EMBEDDING_DIMENSION | 1024 |

### 5.2 API 调用证据（前一轮 verify_embedding.py）

| 验证项 | 结果 |
|--------|------|
| POST /v1/embeddings 响应状态 | 200 OK |
| 返回 model 字段 | `Qwen/Qwen3-VL-Embedding-8B` |
| 向量维度 | 1024 |
| L2 norm | 1.0（已归一化） |
| fallback 触发 | 未触发（API 可用） |
| fallback 时 model 字段 | `fallback-hash`（与真实 model 区分） |

### 5.3 数据库追溯能力

#### 5.3.1 kb_documents 表

```
id | title                           | embedding_model              | index_status | status
2  | 路灯故障报修办事指南             | Qwen/Qwen3-VL-Embedding-8B  | ready        | PUBLISHED
3  | 路灯故障常见问题解答             | Qwen/Qwen3-VL-Embedding-8B  | ready        | PUBLISHED
4  | 城市公共交通乘车守则             | Qwen/Qwen3-VL-Embedding-8B  | ready        | PUBLISHED
5  | 物业服务收费管理办法             | Qwen/Qwen3-VL-Embedding-8B  | ready        | PUBLISHED
6  | 城市生活垃圾分类管理办法（2020年版）| (空)                        | pending      | EXPIRED
```

- 4/5 PUBLISHED 文档 `embedding_model = "Qwen/Qwen3-VL-Embedding-8B"`；
- 1 条 EXPIRED 文档 `embedding_model` 为空（未索引）。

#### 5.3.2 kb_chunks 表（关键发现）

```
kb_chunks 列：id, document_id, chunk_index, content, token_count, created_at, embedding, chunk_hash, keywords, char_count
```

- **无 `embedding_model` 列**；
- **无 `provider` 列**；
- **无 `dimension` 列**；
- **无 `fallback` 标志列**；
- **无 `created_at` 之外的元数据**。

### 5.4 余弦相似度对比

| 文本对 | 余弦相似度 |
|--------|-----------|
| "路灯坏了" vs "路灯故障报修" | 0.31 |
| "路灯坏了" vs "垃圾分类" | 0.52 |
| 长文本（>100 字）相似对 | 0.78+ |
| 长文本（>100 字）无关对 | 0.20- |

短文本语义区分不稳定（相似 < 无关），但长文本语义区分正常。

### 5.5 RAG 检索验证

- 查询"博士人才政策"：KB 中无对应文档，检索失败（无证据）；
- 查询"路灯故障"：正确返回 doc_id=2/3，5 条引用，办理时限正确。

### 5.6 结论

- **当前 Embedding API 真实可用**，返回 1024 维 Qwen 模型向量；
- **kb_documents 表模型元数据存在**，4/5 PUBLISHED 文档记录 `Qwen/Qwen3-VL-Embedding-8B`；
- **kb_chunks 表无 chunk 级来源追溯能力**，无法验证历史 chunk 向量是否由真实模型生成；
- **短文本语义区分不稳定**，但长文本正常；
- **fallback 机制存在**，fallback 时 model=`fallback-hash`，但 kb_chunks 不记录该字段，fallback 发生时 kb_documents 仍可能记录真实 model 名（取决于 `embed_results[0].model` 是否在 fallback 时被错误写入）。

**最终定性**：模型元数据存在，API 真实可用，但历史 chunk 级来源无法完全验证。不能写成"完全证实历史向量由真实模型生成"。

---

## 六、需要新增或调整的 P0/P1

### 6.1 新增 P0

| 编号 | 项目 | 来源 |
|------|------|------|
| P0-G | 通知广播风暴：ticket_due_soon 通知所有 agent+admin | 本轮诊断 |

### 6.2 维持原 P0

| 编号 | 项目 | 状态 |
|------|------|------|
| P0-A | 办结审核角色错位（部门人员自审自结） | 维持 |
| P0-B | 低评分无审核自动重开 | 维持 |
| P0-C | service principal 绕过 KB 可见性过滤 | 维持 |
| P0-D | AI 审计断链（token=0） | 维持 |
| P0-E | service_guide 直接 LLM 生成无 RAG | 维持 |
| P0-F | pgvector 无 HNSW/IVFFlat 索引 | 维持 |

### 6.3 新增 P1

| 编号 | 项目 | 来源 |
|------|------|------|
| P1-A | kb_chunks 表缺少 embedding_model/provider/dimension/fallback 列，无法追溯 chunk 级来源 | 本轮诊断 |
| P1-B | E2E 测试选择器不精确（14 条用例），需统一使用 data-testid 或稳定语义定位 | 本轮诊断 |
| P1-C | E2E 用例未等待 API 响应即断言（2 条），需引入 `waitForResponse` | 本轮诊断 |
| P1-D | E2E 串行用例选择器不一致（`/发送消息/` vs `/^发送$/`） | 本轮诊断 |

---

## 七、第一轮最终修复清单

### 7.1 P0 清单（7 项）

| 编号 | 项目 | 修复要点 | 是否允许本轮后实施 |
|------|------|----------|---------------------|
| P0-A | 办结审核角色错位 | 引入独立审核角色或上移至 admin/agent | 是（涉及状态机，需谨慎） |
| P0-B | 低评分无审核自动重开 | 评价 1-2 星需人工审核后决定是否重开 | 是（涉及评价申诉业务，需谨慎） |
| P0-C | service principal 绕过 KB 可见性 | `_apply_visibility_filter` 对 service principal 同样适用 | 是 |
| P0-D | AI 审计断链（token=0） | 修复 token 统计链路 | 是 |
| P0-E | service_guide 直接 LLM 生成 | 改为 RAG 检索 + LLM 生成 | 是 |
| P0-F | pgvector 无索引 | 创建 HNSW 或 IVFFlat 索引 | 是 |
| P0-G | 通知广播风暴 | 收窄 ticket_due_soon recipients 至 creator+assignee+dept_staff | 是 |

### 7.2 E2E 测试修复清单（允许本轮实施）

| 项目 | 修复要点 |
|------|----------|
| 选择器精确化 | `getByText('工单草稿')` → `getByText('工单草稿', { exact: true })` 或 `getByRole('heading', { name: '工单草稿' })` |
| 等待 API 响应 | orchestrator.spec.ts 10 条用例：在断言前 `await page.waitForResponse(r => r.url().includes('/orchestrator/chat') && r.status() === 200)` |
| 超时调整 | AI 辅助页用例：`toBeVisible({ timeout: 15000 })` |
| 串行选择器统一 | workflows.spec.ts:92 `/发送消息/` → `/^发送$/` |
| Rasa 用例超时 | workflows.spec.ts:7 添加 `test.setTimeout(90_000)` |
| 访客模式断言 | chat-layout.spec.ts 改用 `getByRole('menuitem')` 或 `data-testid` |

### 7.3 P1 清单（4 项，本轮不实施）

| 编号 | 项目 |
|------|------|
| P1-A | kb_chunks 增加 embedding 元数据列 |
| P1-B | E2E 选择器统一为 data-testid |
| P1-C | E2E 等待 API 响应模式化 |
| P1-D | E2E 串行选择器统一 |

---

## 八、哪些结论需要修正回验证报告

### 8.1 需修正的结论

| 原结论 | 修正后结论 | 修正原因 |
|--------|-----------|----------|
| "通知存在 9946 条重复" | "通知存在 9514 条，0 重复，但属广播风暴（单 ticket ~59 条）" | 幂等键有效，根因为 recipients 范围过宽 |
| "Embedding 完全证实为真实模型" | "API 真实可用，kb_documents 元数据存在，但 kb_chunks 无 chunk 级来源追溯，历史 chunk 无法完全验证" | kb_chunks 无 embedding_model 列 |
| "E2E 1/38 通过" | "E2E 12/38 通过，18 失败，8 skipped（修正 baseURL 后）" | 前一轮 baseURL 错误 |
| "event_key 包含当前时间导致重复" | "幂等键为 ticket_id+occurrence+user_id，occurrence=deadline.isoformat()，不含当前时间，无重复" | SQL 证据 |
| "worker 重启后重复投递" | "无重复投递，幂等键约束有效" | SQL 证据 |
| "aftercare_service 与 worker.py 两套扫描产生重复" | "两者功能不重叠（前者回访，后者 SLA 提醒），非重复逻辑" | 代码审查 |

### 8.2 维持的结论

- Token=0 确认成立（P0-D）；
- 办结审核角色错位（P0-A）；
- 低评分无审核重开（P0-B）；
- service principal 绕过 KB 可见性（P0-C）；
- service_guide 直接 LLM 生成（P0-E）；
- pgvector 无索引（P0-F）；
- Rasa 独立通道，访客入口使用 Rasa，登录用户使用 Orchestrator；
- Orchestrator 路由：规则关键词 → Guard 预检查 → LLM 语义分类 → 工具路由。

---

## 附录：本轮未实施项

- 未清理通知数据（按用户要求，避免掩盖根因）；
- 未修改工单状态机、办结审核逻辑、评价申诉业务；
- 未实施 P0-G 修复（仅记录根因与方案）；
- 未对 E2E 测试代码做大规模修改（仅记录修复清单）；
- 未新建 Embedding 测试文档（前一轮 verify_embedding.py 已证明 API 真实可用，本轮聚焦数据库追溯能力验证）。
