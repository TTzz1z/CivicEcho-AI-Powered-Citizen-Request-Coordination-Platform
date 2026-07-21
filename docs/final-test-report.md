# 最终测试报告

测试日期：2026-07-21（Asia/Shanghai）
版本：Round 3 验收收口版
执行环境：本地 Docker Compose

## 测试环境

| 项 | 配置 |
|---|---|
| 操作系统 | Windows + Docker Desktop |
| Docker Compose 服务 | 8 个容器（frontend / backend / postgres / minio / rasa / action_server / duckling / worker） |
| 数据库 | PostgreSQL 16 + pgvector 扩展（`pgvector/pgvector:pg16`） |
| LLM Provider | DeepSeek（OpenAI 兼容 `chat/completions`，`deepseek-chat`） |
| Embedding Provider | SiliconFlow `text-embedding-v1`，1024 维 |
| Rasa | 3.6.20 + Rasa SDK 3.6.2，模型 `tingting-v1.3.0.tar.gz` |
| 演示数据 | Seed 4 账号 + 演示 KB 文档 + reset 脚本 |

`.env` 关键配置：

```
AI_PROVIDER=deepseek
AI_API_KEY=<已填>
AI_MODEL=deepseek-chat
EMBEDDING_API_KEY=<已填>
EMBEDDING_MODEL=text-embedding-v1
EMBEDDING_DIMENSIONS=1024
```

## 测试结果汇总表

| 门禁 | 命令 | 结果 |
|---|---|---|
| 后端 pytest | `docker compose exec -T backend pytest -q` | **80/80 passed** |
| 前端 vitest | `cd frontend; npm test` | **17/17 passed** |
| TypeScript tsc | `cd frontend; npm run lint:types` | **0 errors** |
| Vite build | `cd frontend; npm run build` | **OK** |
| Playwright E2E | `cd frontend; npx playwright test` | **96/96 passed** |
| Alembic 升级 | `docker compose exec -T backend alembic upgrade head` | **OK**（head = 0018） |
| Alembic 降级 | `docker compose exec -T backend alembic downgrade -1` | **OK**（0018 → 0017） |
| Alembic check | `docker compose exec -T backend alembic check` | **clean** |
| Docker healthy | `docker compose ps` | **8/8 healthy** |

## 真实 AI Token 证据

通过 `backend/scripts/verify_r3_real_llm.py` 触发 4 条真实 DeepSeek 调用，全部写入 `ai_usage_logs` 表：

| # | capability | route | query | provider | model | total_tokens | latency_ms | cost (RMB) | usage_unavailable |
|---|---|---|---|---|---|---|---|---|---|
| 1 | policy_rag | citizen_query | 城市道路路灯坏了由哪个部门负责维修 | deepseek | deepseek-chat | 1582 | 约 3500 | 0.013 | false |
| 2 | service_guide | citizen_query | 路灯故障报修需要什么材料如何办理 | deepseek | deepseek-chat | 1873 | 约 4200 | 0.015 | false |
| 3 | policy_rag | citizen_query | 社保补贴政策适用于哪些人群 | deepseek | deepseek-chat | 2104 | 约 4800 | 0.017 | false |
| 4 | service_guide | citizen_query | 怎么办身份证 | deepseek | deepseek-chat | 2419 | 约 5100 | 0.019 | false |

总计 4 条真实 LLM 调用：

- `total_tokens` 范围：1582 - 2419
- `estimated_cost_rmb` 范围：0.013 - 0.019 RMB
- `provider=deepseek`、`model_name=deepseek-chat`
- `usage_unavailable=false`（来自模型真实 `usage` 块，非 0 填充）
- `degraded=false`、`degrade_reason=NULL`（无降级）
- `session_id` 每次调用都唯一（`r3-<8hex>`），证明 session_id 隔离生效

引用字段完整性验证（每条 policy_rag/service_guide 调用都返回 citations）：

- `title` ✓
- `doc_number` ✓
- `issuing_authority` ✓
- `excerpt` ✓

## 降级测试结果

通过 `backend/scripts/verify_r3_degradation.py` 触发三种 `degrade_reason`：

| 测试场景 | 触发条件 | degrade_reason | degraded | budget_exceeded | 行为 |
|---|---|---|---|---|---|
| LLM 不可用 | 清空 `AI_API_KEY` | `llm_unavailable` | true | false | Orchestrator 跳过 LLM，policy_rag 退化为仅检索原文 + 引用；ticket_draft 退化为规则模板 |
| Embedding 失败 | 清空 `EMBEDDING_API_KEY` | `embedding_fallback` | true（部分路径）| false | RAG 回退到 PostgreSQL 关键词 + pg_trgm 模糊匹配，`kb_chunks.embedding_fallback=fallback_used` |
| 预算超额 | 模拟单用户每日 LLM 调用超 60 次 | `budget_exceeded` | true | true | Guard 拒绝 LLM 调用，返回降级提示，不消耗 token |

三种 `degrade_reason` 全部写入 `ai_usage_logs`，`degraded=true` + `degrade_reason` 字段标注原因，管理员可在 AI 用量页按 `degrade_reason` 筛选。

## Playwright 详细结果

执行命令：`cd frontend; npx playwright test`

| 指标 | 值 |
|---|---|
| 总用例数 | 96 |
| 通过 | 96 |
| 失败 | 0 |
| 跳过 | 0 |
| 总耗时 | 约 20.7 分钟 |
| 浏览器 | chromium |

测试文件覆盖：

| 文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `auth-switch.spec.ts` | ~12 | 登录、角色切换、退出后路由守卫 |
| `chat-draft.spec.ts` | ~14 | 智能对话建单草稿模式（路灯/教育/政策咨询） |
| `chat-layout.spec.ts` | ~8 | 长对话滚动、公开会话归属说明 |
| `orchestrator.spec.ts` | ~20 | 10 条路由 E2E（政策咨询/办事指南/草稿/进度查询等） |
| `round2-ai-credibility.spec.ts` | ~14 | session_id 隔离、引用字段、降级标记、三态确认 |
| `workflows.spec.ts` | ~28 | 四角色闭环、申诉重办、AI 办件助手、审计链路 |

每个失败用例都会在 `frontend/test-results-v3/` 留下 `error-context.md` + `trace.zip` + 失败截图，便于排障。

## 已知限制

1. **依赖外部 LLM 服务的 E2E 可能因服务波动失败**：`orchestrator.spec.ts` 与 `round2-ai-credibility.spec.ts` 中部分用例需要真实 DeepSeek/SiliconFlow 调用，若演示时 LLM API 限流、超时或区域不可达，相关用例可能失败。失败时系统应自动降级（`degraded=true`），但断言"provider=deepseek"的用例不会因降级而通过。
2. **单机 Compose 部署**：当前不是多机高可用、K8s 或微服务化部署；不宣称自动扩缩容或零停机发布。
3. **Rasa 3.6.20 依赖树**：保留上游 `DeprecationWarning`（TensorFlow、Pillow 等），本轮按约束不升级 Rasa 主版本。
4. **登录限流为 Backend 进程内 + 数据库共享**：多实例前需迁移到 Redis 或网关共享限流。
5. **外部适配器默认 disabled**：OIDC、组织目录、短信、地图、政务工单平台等适配器未注入真实配置时返回"未配置"，不伪造成功。
6. **演示数据**：所有数据均为 Seed 演示数据，不是真实政务数据；生产环境禁止使用 `tingting-seed-demo-2026` 弱密码。
7. **未训练或微调模型**：所有 AI 能力基于 DeepSeek + SiliconFlow 现成模型 + 规则降级，不涉及模型训练。

## 复现步骤

```powershell
# 1. 启动 8 服务
Copy-Item .env.example .env  # 首次运行
# 编辑 .env：POSTGRES_PASSWORD / JWT_SECRET / SERVICE_API_TOKEN / SEED_PASSWORD / AI_API_KEY / EMBEDDING_API_KEY
docker compose up -d --wait --remove-orphans

# 2. 重置演示数据
SEED_PASSWORD=tingting-seed-demo-2026 docker exec -w /app tingting-assistant-backend-1 python -m scripts.demo_reset

# 3. 跑后端测试
docker compose exec -T backend pytest -q

# 4. 跑前端测试与构建
cd frontend
npm ci
npm run lint:types
npm test
npm run build

# 5. 跑 E2E
npx playwright test

# 6. 触发真实 LLM 调用并验证 ai_usage_logs
docker exec -T backend python -m scripts.verify_r3_real_llm
docker exec -T backend python -m scripts.verify_r3_degradation
docker exec -T backend python -m scripts.verify_r3_rasa_orchestrator
docker exec -T backend python -m scripts.verify_r3_service_guide

# 7. 验证迁移升降级
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic downgrade -1
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic check
```

## 结论

Round 3 验收范围内全部门禁通过：

- 后端 80/80、前端 17/17、tsc 0 errors、Vite build OK、Playwright 96/96、Alembic 升降级 OK、Docker 8/8 healthy。
- 真实 DeepSeek LLM 调用产生 4 条 `ai_usage_logs`，`total_tokens` 1582-2419，`cost` 0.013-0.019 RMB，`usage_unavailable=false`。
- 三种 `degrade_reason`（llm_unavailable / embedding_fallback / budget_exceeded）全部验证通过。
- 引用字段（title / doc_number / issuing_authority / excerpt）完整。
- session_id 隔离与 request_id 全链路追踪生效。

未验证项：真实短信、OIDC、地图、政务工单平台接入（适配器默认 disabled，不声称已接入）。
