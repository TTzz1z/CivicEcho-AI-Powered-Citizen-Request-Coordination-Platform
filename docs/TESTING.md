# 测试说明（现行）

> **文档基线（本轮最终冻结验收，2026-07-22 本地实测）**
> - 工作区基线：相对 `438047c776787da6c5b412c403c7799ba52364c8` 的未提交收口改动（以最终 commit SHA 为准）
> - Alembic head：`0025`（`alembic heads` / `current` 均为 `0025 (head)`；`alembic check` → `No new upgrade operations detected`）
> - 远程 GitHub Actions：以 push 后该 SHA 的默认 jobs 为准（见下文「远程 CI」；未全绿前不得宣称发布完成 / 不得打 tag）

旧稿（已归档）：[archive/final-test-report.md](./archive/final-test-report.md)、[archive/test-isolation.md](./archive/test-isolation.md)、[archive/ci-design.md](./archive/ci-design.md)；索引见 [archive/](./archive/)。

## 默认门禁（不是全量 E2E）

`.github/workflows/ci.yml` 日常 / 发布相关默认信号：

| Job | 内容 |
|---|---|
| `static-checks` | compileall、ruff（严重规则）、`docker compose config -q` |
| `frontend-tests` | `npm ci` → `lint:types` → `vitest` → `build` |
| `backend-tests` | Alembic upgrade/check + `pytest -q` |
| `action-tests` | Action Server 两组 unittest |
| `rasa-regression` | data validate + Core/NLU 回归 |
| `e2e-smoke` | `scripts/run-e2e.sh smoke` → **仅** `e2e/smoke.spec.ts` + Chromium |
| `dependency-security` | pip-audit + npm audit |
| `docker-integration` | main push：开发 compose + seed + `verify_r4_business_loops` |
| `production-compose` | main/tag/手动：prod override 核心路径 + ClamAV EICAR |

可选：`e2e-full`（`workflow_dispatch` 勾选 `run_e2e_full`）跑三浏览器全量 Playwright，**不作为**默认发布门禁。未执行 Full **不得**判定发布失败。

> 注意：Windows 下 `scripts/run-e2e.ps1` 当前会跑 **全量** `playwright test`（非 smoke）。本轮 smoke：`npx playwright test e2e/smoke.spec.ts --project=chromium`（开发 Compose，`E2E_BASE_URL=http://127.0.0.1:8081`，`E2E_API_URL=http://127.0.0.1:8001`）。

## Smoke 范围（6 条，仅 Chromium）

`frontend/e2e/smoke.spec.ts`：

| # | 覆盖 |
|---|---|
| S1 | 市民登录 → 对话页渲染 |
| S2 | 建单 → accept → assign → process → WO submit → summary → **review-resolve** → feedback satisfied → **closed** |
| S3 | dissatisfied 保持 resolved → 申诉 → **admin 批准** → **processing** |
| S4 | policy_rag citations |
| S5 | 路由守卫 → `/forbidden` |
| S6 | AI 建议三态审核（采纳不改工单状态） |

```powershell
$env:E2E_PASSWORD = "your-e2e-password-12+"
$env:E2E_BASE_URL = "http://127.0.0.1:8081"
$env:E2E_API_URL = "http://127.0.0.1:8001"
cd frontend
npx playwright test e2e/smoke.spec.ts --project=chromium
```

## 本轮自动门禁结果（2026-07-22 重新实测）

| # | 命令 / 套件 | 结果 | 通过/失败/跳过 |
|---|---|---|---|
| 1 | `docker compose exec -T backend pytest -q` | **通过** | **162 passed / 0 failed / 0 skipped**（1 warning） |
| 2 | `frontend` `npm test`（Vitest） | 通过 | **49 / 0 / 0**（18 files） |
| 3 | `npm run lint:types` | 通过 | — |
| 4 | `npm run build` | 通过 | — |
| 5 | Alembic `heads` / `current` / `check` | 通过 | head=`0025`；`No new upgrade operations detected` |
| 6 | `docker compose run --rm --no-deps rasa data validate` | 通过 | exit 0（未使用 intent/utterance 警告，非失败） |
| 7 | Action Server unittest（`test_public_request_actions.py` + `test_ticket_gateway.py`） | 通过 | **18 + 3 = 21 / 0 / 0** |
| 8 | Playwright Chromium Smoke（`smoke.spec.ts`） | 通过 | **6 / 0 / 0**（约 25.8s） |
| 9 | 开发 Compose 健康 | 通过 | 8 服务 healthy；`/health/live` → 200；`/health/ready` → 200 |
| 10 | `/metrics` 匿名 | 通过* | backend `http://127.0.0.1:8001/metrics` → **401**；前端网关当前镜像对 `/metrics` 仍回 SPA HTML **200**（仓库根 `Caddyfile` 有 `respond 404`，运行中 frontend 镜像未体现该规则） |
| 11 | 生产 Compose | **部分** | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q` **通过**；本机**未**起 prod 栈 → 健康检查 **未验证** |
| 12 | MinIO put/open/delete | 通过 | `get_object_storage()` 上传/下载/删除 ok |
| 13 | ClamAV / EICAR | **未验证** | 开发栈无 `clamav`；`malware_scan_mode=disabled`；不伪造 |
| 14 | `pip-audit -r requirements.lock.txt`（backend 容器） | 通过 | No known vulnerabilities found |
| 15 | `npm audit --omit=dev --registry https://registry.npmjs.org` | 通过 | **0 vulnerabilities** |
| 16 | `demo_reset` 连续两次（`CONFIRM_DEMO_RESET=YES` + `SEED_PASSWORD`） | 通过 | 两次终态一致：`departments=7` / `categories=15` / `users=4` / `tickets=1` |

> 后端全量 pytest 本轮结论：**162 passed / 0 failed**。不保留任何历史「150 / 12 failed」类表述作为现行结论。

## 本轮人工主流程（API / 脚本交叉印证）

| 项 | 结果 | 证据 |
|---|---|---|
| 市民政策咨询 + citations | **通过** | API：`社保补贴政策适用于哪些人群` → `route=policy_rag`，`payload.citations=5`；Smoke S4 |
| 无证据降级 | **通过（测试/Smoke + 部分探针）** | 虚构法条 query → `out_of_scope`、citations=0；含「政策」关键词的冷门措辞仍可能命中 KB（探针偏弱，不推翻既有用例） |
| 市民建单 | **通过** | `acceptance_main_flow.py`；Smoke S2 |
| 坐席 AI 分诊 / 受理 / 派发 | **通过** | live `/ai/tickets/{id}/analyze` → `suggestion_type=triage_assistant`；accept/assign 在 acceptance + Smoke |
| 部门办件 / WorkOrder / 汇总（提交不直接办结） | **通过** | acceptance Step 4：WO submit + summary → `awaiting_review`，主单仍 `processing`；`/resolve` → 404 |
| 坐席 review-resolve | **通过** | acceptance Step 5；Smoke S2 |
| 市民满意关闭 | **通过** | Smoke S2 |
| 不满意 / 申诉 / 管理员批准重办 | **通过** | acceptance Steps 6–9；Smoke S3 |
| AI 建议审核不改工单状态 | **通过** | API：`advice/review` adopted 后 status 仍 `processing`；Smoke S6 |
| 越权 403 | **通过** | 市民 `GET /admin/audit-logs` → **403**；Smoke S5 `/forbidden` |
| 409 冲突 | **通过** | 同 version 二次 accept → **409 `VERSION_CONFLICT`** |

`scripts/acceptance_main_flow.py`：**19 PASS / 0 FAIL**。

## 未执行 / 已知限制

| 项 | 说明 |
|---|---|
| E2E Full | **故意非门禁**；本轮未跑；勿因未跑 Full 判失败 |
| 生产 Compose 健康 / ClamAV EICAR | 仅 `config -q`；未起 prod；ClamAV **未验证** |
| 远程 GitHub Actions | push 后以 Actions 默认 jobs 为准；未全绿前不打 tag |
| Rasa Core/NLU 回归 | 本地仅 `data validate`；Core/NLU 回归依赖远程 `rasa-regression` |
| 匿名绑定 | 非跨设备找回 |
| AI 建议 | advisory only；不自动派发/填结果/办结 |
| 成本估算 | `estimated_cost_level` 等为估算字段 |
| `ticket_advice` | 兼容/审核路径保留；以现行 API 为准 |
| 交付定位 | 演示/工程化 MVP，**非**真实政务生产上线 |
| `demo_reset` 后 KB | 终态仍可见历史测试 KB 文档（非 whitelist 清理范围）；白名单用户/部门/分类计数稳定 |

## `.env` 关键变量（仅存在性，不回显密钥）

| 变量 | 状态 |
|---|---|
| `JWT_SECRET` / `SERVICE_API_TOKEN` / `SEED_PASSWORD` / `POSTGRES_PASSWORD` / `CORS_ORIGINS` | 已配置 |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | 已配置 |
| MinIO / compose 注入项 / `MALWARE_SCAN_*` | 由 compose 默认或开发态 |

`.env` 已被 `.gitignore` 忽略，未纳入版本控制。
