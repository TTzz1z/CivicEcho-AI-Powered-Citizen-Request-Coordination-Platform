# CI 设计

> 现行测试门禁说明亦见 **[TESTING.md](../TESTING.md)**。核对点 Commit `438047c` · Alembic head `0025`。

唯一有效工作流是 `.github/workflows/ci.yml`。

| Job | 触发 | 内容 |
|---|---|---|
| static-checks | PR / push | Python 3.11 compileall、固定 ruff 0.8.6 严重错误检查、compose config |
| frontend-tests | PR / push | npm ci、tsc、vitest、build |
| backend-tests | PR / push | PostgreSQL 16 service、Alembic upgrade/check、pytest |
| action-tests | PR / push | 构建固定 Rasa SDK 3.6.2 镜像，两组 unittest |
| rasa-regression | PR / push | data validate + Core/NLU 回归 |
| e2e-smoke | PR / push | Chromium smoke（`scripts/run-e2e.sh smoke`） |
| dependency-security | PR / push | pip-audit + npm audit |
| docker-integration | main push | 开发 compose up、seed、R4 业务闭环 |
| **production-compose** | main push / tag / workflow_dispatch | `docker-compose.yml` + `docker-compose.prod.yml`，校验 Caddy/Backend/PG/MinIO/ClamAV，EICAR infected |
| e2e-full（可选） | workflow_dispatch 且显式勾选 | 三浏览器全量 Playwright（`scripts/run-e2e.sh full`）；**不作为发布门禁** |

Compose 所需密码/Token 只使用 CI 临时示例值，不打印 Token。Backend/Action 依赖版本固定；Rasa Core/SDK 固定为 3.6 系列并使用已训练的 `tingting-v1.3.0` 模型。

打 `v1.0.0` 前必须：`main` push Actions 全绿（含 `e2e-smoke`、`production-compose` 等默认 jobs）。`e2e-full` 仅手动可选，失败不阻塞发布。
