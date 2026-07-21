# 倾听助手 Tingting Assistant

倾听助手是一个面向市民诉求受理与跨部门协同办理的政务服务演示平台。系统把"市民政策咨询（RAG）→ 工单全生命周期管理 → AI 办件辅助建议 → 知识库治理 → 审计追踪"做成一条可运行、可测试、可复现的闭环链路，由 FastAPI + PostgreSQL+pgvector + React+TypeScript+antd + Rasa + Docker 共同构成。

项目重点不是页面堆叠，而是把对话式入口、可信业务状态机、四角色权限、AI 可信度审计、降级机制、知识库可见性、人工复核三态确认整合到同一个工程化系统中。所有数据均为演示种子数据，不涉及真实政务数据；外部短信/OIDC/地图/政务平台均为可配置适配器，默认 disabled。

## 核心功能

| 模块 | 已实现能力 |
|---|---|
| 市民政策咨询 | RAG 检索（pgvector 语义检索 + 关键词回退），引用必须包含 `title/doc_number/issuing_authority/excerpt`，无证据时返回 `no_evidence` 并提示建单 |
| 工单全生命周期 | `pending → accepted → assigned → processing → resolved → closed` 状态机，含 `rejected`、版本号乐观锁、`idempotency_key` 幂等创建、**权限校验先于 version 校验**(R4) |
| 多部门协同 | `work_orders` 主办/协办/复核任务，部门退回、转派、提交结果，主办汇总；`awaiting_review` 由坐席复核办结 |
| AI 办件助手 | advisory only（三态人工确认：adopted/adopted_with_edits/rejected，走 `/api/v1/kb/tickets/{id}/advice/review`)，覆盖 `ticket_advice`、`pre_review`、`ai_analyze` 三类能力 |
| 知识库管理 | 文档上传 → 解析 → 审核 → 发布 → 版本（replaces_doc_id）→ 可见性（PUBLIC/DEPARTMENT/INTERNAL）→ 过期下架 |
| Rasa NLU + Orchestrator | 分层路由（规则→OOD→LLM），11 条路由（`policy_rag` / `service_guide` / `ticket_intake` / `suggestion_intake` / `ticket_progress` / `department_navigation` / `emergency_route` / `general_chat` / `human_handoff` / `clarify` / `out_of_scope`），多意图检测，session_id 隔离 |
| AI 审计链路 | `ai_usage_logs` 记录 10 种 capability，每条含 `provider/model/total_tokens/latency/cost/degrade_reason/session_id` |
| 通知回访申诉 | `notifications`（幂等键 6 字段）+ `follow_up_tasks`（电话回访）+ `appeals`（申诉重办闭环） |
| 4 角色 | citizen、agent、department_staff、admin，后端 `AuthorizationPolicy` 集中校验 |
| 降级机制 | `llm_unavailable` / `embedding_fallback` / `budget_exceeded` / `orchestrator_unavailable` 等 `degrade_reason` 统一标记并在前端明示 |
| 可复现交付 | Docker Compose 一键启动开发 8 服务（生产 override 追加 Caddy + ClamAV），Alembic 升降级，演示数据一键 reset（含生产护栏） |

## 技术栈

**Frontend**：React 19、TypeScript、Vite、Ant Design、TanStack Query、Vitest、Playwright

**Backend**：FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL 16 + pgvector、JWT、Argon2

**Conversation AI**：Rasa 3.6.20 + Rasa SDK 3.6.2、PostgreSQL Tracker Store、Duckling、Action Server

**AI 辅助**：DeepSeek（OpenAI 兼容 `chat/completions`）+ SiliconFlow Embedding（默认 `Qwen/Qwen3-Embedding-0.6B`，1024 维），`advisory_only=true`，无密钥自动降级规则引擎

**Infrastructure**：Docker Compose（开发 8 服务；生产 override 追加 Caddy、ClamAV）、MinIO 对象存储、worker 后台（SLA 扫描 + 通知 outbox + 登录限流清理）、Alembic 启动迁移、幂等 Seed

## 快速开始（Docker Compose 一键启动）

环境要求：Docker Desktop / Docker Compose、PowerShell。

```powershell
Copy-Item .env.example .env

# 编辑 .env，至少填写四个互不相同的强密钥：
#   POSTGRES_PASSWORD / JWT_SECRET / SERVICE_API_TOKEN / SEED_PASSWORD
# 如需演示真实 LLM / Embedding 调用，再填：
#   AI_PROVIDER=deepseek / AI_API_KEY=sk-...
#   EMBEDDING_API_KEY=sk-...（默认 SiliconFlow：EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1）
# 未配置 Embedding Key 时系统会用伪向量回退，AI 审计会记录 embedding_fallback，不应称为真实向量检索。

docker compose pull --ignore-buildable
docker compose build
docker compose up -d --wait --remove-orphans
```

默认访问地址：

- Web：`http://localhost:8080`
- Backend OpenAPI：`http://localhost:8001/docs`
- Backend Ready：`http://localhost:8001/health/ready`
- Rasa Status：`http://localhost:5005/status`
- MinIO Console：`http://localhost:9001`

## 演示账号

Seed 会创建四类本地演示账号，密码由 `SEED_PASSWORD` 环境变量提供。本仓库默认演示密码为 `tingting-seed-demo-2026`，仅用于本地演示，禁止用于生产。

| 角色 | 用户名 | 部门 |
|---|---|---|
| 市民 | `citizen_local` | — |
| 坐席 | `agent_local` | — |
| 部门人员 | `department_local` | 综合受理 |
| 管理员 | `admin_local` | — |

## 一键 Reset 演示环境

清空所有事务数据（工单、通知、AI 日志、审计）并重新 Seed，用于演示前重置。脚本含生产环境保护：`APP_ENV=production` 会拒绝执行，且必须显式确认。

```powershell
docker exec -w /app `
  -e SEED_PASSWORD=tingting-seed-demo-2026 `
  -e CONFIRM_DEMO_RESET=YES `
  tingting-assistant-backend-1 `
  python -m scripts.demo_reset --confirm-reset
```

Bash / Git Bash 一行：

```bash
docker exec -w /app -e SEED_PASSWORD=tingting-seed-demo-2026 -e CONFIRM_DEMO_RESET=YES tingting-assistant-backend-1 python -m scripts.demo_reset --confirm-reset
```

执行后输出每张表清理行数与重新 Seed 的统计。

## 测试命令

```powershell
# 后端 pytest（以当前 CI / 本地输出为准）
docker compose exec -T backend pytest -q

# 前端 vitest（以当前本地输出为准）
cd frontend; npm test

# TypeScript tsc(0 errors)
cd frontend; npm run lint:types

# Vite build(OK)
cd frontend; npm run build

# Playwright Smoke(6 条核心路径, Chromium; GitHub Actions 日常 CI 同此)
cd frontend; npx playwright test e2e/smoke.spec.ts --project=chromium

# Playwright 全量 E2E（workflow_dispatch / tag 门禁，约 20 min）
sh scripts/run-e2e.sh full

# 生产等价 Compose（Caddy + ClamAV；容器内 MinIO HTTP）
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait

# Alembic 升降级 + 漂移检查
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic downgrade -1
docker compose exec -T backend alembic check  # 应输出 "No new upgrade operations detected"

# Docker 健康检查(开发 8 服务)
docker compose ps

# Rasa Action Server 单元测试
docker compose exec -T action_server python -m unittest discover -s tests -v

# R4 业务闭环验证
docker compose exec -T backend python -m scripts.verify_r4_business_loops
```

> 历史报告中的通过数量可能已过期；投递/面试时请以当前 commit 的 GitHub Actions 与本地命令输出为准。
## 文档索引

- 产品文档：[PRODUCT.md](PRODUCT.md)
- 工程文档：[ENGINEERING.md](ENGINEERING.md)
- 演示脚本：[docs/demo-script.md](docs/demo-script.md)
- 最终测试报告：[docs/final-test-report.md](docs/final-test-report.md)
- 面试追问清单：[docs/interview-qa.md](docs/interview-qa.md)
- 当前架构与调用链路：[docs/architecture-current.md](docs/architecture-current.md)
- 权限与认证：[docs/auth-and-permissions.md](docs/auth-and-permissions.md)
- 工单工作流：[docs/ticket-workflow.md](docs/ticket-workflow.md)
- 数据库设计：[docs/database-design.md](docs/database-design.md)
- 部署指南：[docs/deployment-guide.md](docs/deployment-guide.md)
- 备份与恢复：[docs/backup-and-restore.md](docs/backup-and-restore.md)
- 安全加固：[docs/security-hardening.md](docs/security-hardening.md)
- 可观测性：[docs/observability.md](docs/observability.md)
- 第三方声明：[NOTICE.md](NOTICE.md)

## 项目结构概览

```
helpdesk-assistant-main/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI 路由（auth/tickets/orchestrator/kb/ai_usage 等）
│   │   ├── services/         # 业务服务（ticket/orchestrator/kb/ai_usage_recorder 等）
│   │   ├── repositories/      # SQLAlchemy 仓储
│   │   ├── authorization.py  # AuthorizationPolicy + Principal
│   │   ├── models.py          # SQLAlchemy 模型（含 AiUsageLogModel 等）
│   │   ├── llm_client.py     # DeepSeek 客户端
│   │   ├── embedding_client.py # SiliconFlow Embedding 客户端
│   │   └── seed.py            # 幂等 Seed
│   ├── migrations/versions/  # Alembic 迁移 0001-0023
│   ├── scripts/              # demo_reset.py / verify_r*.py
│   └── tests/                # pytest 用例
├── frontend/
│   ├── src/
│   │   ├── api/              # axios + tanstack query 客户端
│   │   ├── pages/            # 4 角色页面（ChatPage/TicketDetailPage/AdminAiUsagePage 等）
│   │   ├── components/       # AiCaseAssistant/KbRagPanel/TicketDraftPanel 等
│   │   └── routes/           # AppRoutes + guards
│   └── e2e/                  # Playwright 96 用例
├── actions/                  # Rasa Action Server
├── data/                     # Rasa NLU / stories / rules
├── docs/                     # 项目文档
├── docker-compose.yml        # 8 服务编排
├── docker-compose.prod.yml   # 生产 override（Caddy + ClamAV）
├── Dockerfile.backend
├── Dockerfile.actions
├── PRODUCT.md
├── ENGINEERING.md
└── README.md
```

## 项目边界

- 当前形态是本地/演示级 Docker Compose 部署，不宣称多机高可用、K8s、微服务化或零停机发布。
- 外部 OIDC、组织目录、短信、地图、日志、监控和政务工单平台均为可配置适配器；未注入真实配置时默认 disabled，不伪造成功。
- AI 模块当前以 DeepSeek + 规则降级为基础生成建议，不训练或微调模型，不自动受理/派发/办结。
- 所有数据均为演示种子数据，不是真实政务数据。
