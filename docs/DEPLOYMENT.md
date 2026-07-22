# 部署 / 安全 / 备份 / 可观测性（现行）

> **文档基线**
> - Commit：`438047c776787da6c5b412c403c7799ba52364c8`
> - Alembic head：`0025`
> - 开发 Compose：`docker-compose.yml` **8** 服务
> - 生产 override：`docker-compose.prod.yml` 追加 **Caddy + ClamAV**，并收紧宿主机端口

本文收敛原部署/备份/安全/可观测性旧稿；历史全文见 [archive/deployment-guide.md](./archive/deployment-guide.md)、[archive/backup-and-restore.md](./archive/backup-and-restore.md)、[archive/security-hardening.md](./archive/security-hardening.md)、[archive/observability.md](./archive/observability.md)。

本项目是**本地/演示级单机 Compose**交付，不宣称多机高可用、K8s、微服务拆分、等保测评或真实政府生产上线。

## 1. Compose 服务

### 开发（`docker-compose.yml`）

| 服务 | 职责 | 默认宿主机端口 |
|---|---|---|
| `frontend` | React SPA + Nginx | `8080` |
| `backend` | FastAPI | `127.0.0.1:8001`（故意绑 loopback） |
| `postgres` | PG16 + pgvector + Rasa tracker | 无对外映射（仅网络内） |
| `minio` | 附件 / KB 对象存储 | `9000` / console `9001` |
| `rasa` | NLU / 对话 | `5005` |
| `action_server` | Custom Action | `127.0.0.1:5055` |
| `duckling` | 实体解析 | `8000` |
| `worker` | SLA 扫描、通知 outbox、登录限流清理 | 无业务端口暴露 |

### 生产等价（叠加 `docker-compose.prod.yml`）

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait
```

追加：

| 服务 | 职责 |
|---|---|
| `caddy` | HTTPS 终止，对外仅 80/443；`/metrics*` 可配置拒绝 |
| `clamav` | `clamd` 附件扫描（真实部署用 `clamav/clamav:stable`） |

生产环境变量要点：`APP_ENV=production`、精确 `CORS_ORIGINS`、`MALWARE_SCAN_MODE=clamd`、`MALWARE_SCAN_URL=clamav:3310`、`MALWARE_SCAN_REQUIRE_CLEAN=true`。容器内 MinIO 保持 HTTP（`OBJECT_STORAGE_SECURE=false`），对外 TLS 由 Caddy 终止。

CI 的 `production-compose` 使用 `Dockerfile.clamav-mock` 做协议兼容探测，避免官方镜像签名 CDN 在 runner 上失败；**真实部署仍应使用官方 ClamAV 镜像**。

## 2. 环境变量（最小集）

从 `.env.example` 复制。至少设置互不相同的强密钥：

| 变量 | 用途 |
|---|---|
| `POSTGRES_PASSWORD` | 数据库 |
| `JWT_SECRET` | 访问令牌（≥32，禁占位弱口令） |
| `SERVICE_API_TOKEN` | Action Server → Backend |
| `SEED_PASSWORD` | 演示账号密码（≥12；production 禁 demo 默认值） |

可选 AI：

| 变量 | 说明 |
|---|---|
| `AI_PROVIDER` | 默认 `rules`；真实 LLM 用 `deepseek` 等 |
| `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | OpenAI 兼容 chat |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 默认 SiliconFlow `Qwen/Qwen3-Embedding-0.6B`（1024 维） |

未配置 Key 时走规则 / hash embedding fallback，审计记 `degrade_reason` / `embedding_fallback`，**不得**对外称为真实向量检索。

监控：

| 变量 | 说明 |
|---|---|
| `MONITORING_TOKEN` | 访问 `GET /metrics`（Bearer 或 `X-Monitoring-Token`）；亦可 admin JWT |
| `MONITORING_ENDPOINT` | 可选外推送端点（未配置则不伪造上报成功） |

健康检查请用 `/health/live`、`/health/ready`，**不要**用匿名 `/metrics`。

## 3. 启动与迁移

```powershell
Copy-Item .env.example .env
# 编辑密钥后：
docker compose pull --ignore-buildable
docker compose build
docker compose up -d --wait --remove-orphans

docker compose exec -T backend alembic current   # 期望 0025 (head)
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

Backend 启动时执行 `alembic upgrade head`；迁移失败则拒绝起服务。

演示 Seed（容器内）：

```powershell
docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m app.seed
```

## 4. MinIO

- Bucket：附件 `tingting-attachments`；KB `tingting-kb`（可由 `OBJECT_STORAGE_BUCKET` / `KB_UPLOAD_BUCKET` 覆盖）。
- 上传路径：魔数校验 →（生产）ClamAV → 扫描通过后才 `put`。
- **`scripts/backup-database.ps1` 只备份 PostgreSQL，不含 MinIO 对象。**

## 5. ClamAV

- 开发默认 `MALWARE_SCAN_MODE=disabled`。
- 生产：`clamd` + `MALWARE_SCAN_REQUIRE_CLEAN=true`；解析严格匹配 `stream: OK` / `FOUND`。
- CI 用 mock 验证 EICAR → `infected`。

## 6. Caddy

- `Caddyfile` + `SITE_ADDRESS`；生产前端/后端端口从宿主机撤销，流量经 Caddy。
- 建议禁止公网匿名访问 `/metrics`。

## 7. 备份与恢复

```powershell
.\scripts\backup-database.ps1 -Output backups\tingting-$(Get-Date -Format yyyyMMdd).dump
```

恢复（隔离验证后再切）：

```powershell
$env:VERIFY_TICKET_ID = 'QT...'
.\scripts\restore-database.ps1 -InputFile backups\tingting.dump -Force
```

推荐顺序：停写 → 备份 PG → 备份 MinIO buckets → 恢复时先 PG（确认 `alembic current`）再 MinIO → 抽检附件与 KB。

历史文档中「第六轮实测 / Alembic 0003」等数字**已过期**，本轮 **未验证** 备份脚本；需要时请在隔离 compose 项目重跑。

`docker compose down` 保留 volume；`down -v` 永久删除数据。E2E 使用项目名 `tingting-e2e`，不碰开发卷。

## 8. 安全边界（代码已有）

- `AuthorizationPolicy` 为权限单一真相源；前端守卫不可替代后端。
- JWT + Argon2；登录限流（`login_attempts`）。
- 生产 fail-fast：弱密钥、宽 CORS、未启用恶意扫描等可拒启。
- `/metrics`：需 `MONITORING_TOKEN` 或 admin JWT（`backend/app/api/dependencies.py:require_metrics_access`）。
- 日志递归脱敏；`integration_events` 存 hash 不存凭据原文。
- Backend / Action Server 默认绑 `127.0.0.1`，降低 LAN 直连面。

安全扫描历史数字（旧 npm audit / Starlette 公告日期等）以 Actions `dependency-security` 当前结果为准；本轮文档整理 **未重跑**。

## 9. 可观测性

- `X-Request-ID` → ContextVar → 结构化日志 / `audit_logs` / `ai_usage_logs` / 响应头。
- `/health/live`：进程存活；`/health/ready`：含 DB `SELECT 1`。
- Worker 负责 SLA 临期与通知 outbox 重试。
- AI 成本字段 `estimated_cost_rmb` 为**估算**，非供应商真实账单。
- 无 SSE 业务流；`StreamingResponse` 仅用于附件/文件下载。
- 未内置 ELK/Prometheus 全家桶；生产可采集容器 stdout，保留 JSON 与 `request_id`。

## 10. 回滚原则

先备份再换镜像。Schema 优先前向修复；非必要不自动 `alembic downgrade`。必须回滚时用发布前 custom-format dump，在隔离环境验证后再切换。
