# 部署 / 安全 / 备份 / 可观测性（现行）

> CivicEcho v2。开发 Compose 启动 5 个服务。生产覆盖配置使用 Caddy、ClamAV 和独立 SeaweedFS S3，启用 7 个服务。

本项目是**本地/演示级单机 Compose**交付，不宣称多机高可用、K8s、微服务拆分、等保测评或真实政府生产上线。

## 1. Compose 服务

### 开发（`docker-compose.yml`）

| 服务 | 职责 | 默认宿主机端口 |
|---|---|---|
| `frontend` | React SPA + Nginx | `127.0.0.1:8080` |
| `backend` | FastAPI | `127.0.0.1:8001`（故意绑 loopback） |
| `postgres` | PostgreSQL 16、pgvector、pg_trgm | Compose 私有网络 |
| `minio` | 本地演示附件与知识库对象存储，使用 GHCR 公共镜像并固定镜像摘要 | 回环地址 `9000` / `9001` |
| `worker` | SLA 扫描、通知 outbox、限流与会话清理 | 无业务端口暴露 |

### 生产等价（叠加 `docker-compose.prod.yml`）

```powershell
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml -p civicecho-prod up -d --build --wait
```

追加：

| 服务 | 职责 |
|---|---|
| `caddy` | 对外 80/443，HTTP 转 HTTPS。API 文档与监控路径返回 404。 |
| `clamav` | `clamd` 附件扫描（真实部署用 `clamav/clamav:stable`） |
| `object-storage` | 固定摘要的 SeaweedFS 4.55 S3，对外无宿主机端口 |

复制 `.env.prod.example` 后填写独立强密钥及站点地址。生产叠加固定关闭前端演示模式，启用 ClamAV 失败拒绝策略。内置 S3 使用私有网络和独立卷。生产环境须使用新的 Compose 项目名。已有数据库须按第 7 节与对象一起迁移，避免业务行继续指向旧卷。

默认 CPU 和内存预算可通过服务的 `*_CPU_LIMIT` 与 `*_MEMORY_LIMIT` 调整。ClamAV 初次加载病毒库预留 2 GiB。根据实测容器峰值和宿主机总内存调整。

CI 的 `production-compose` 使用 `Dockerfile.clamav-mock` 做协议兼容探测，避免官方镜像签名 CDN 在 runner 上失败；**真实部署仍应使用官方 ClamAV 镜像**。

## 2. 环境变量（最小集）

从 `.env.example` 复制。至少设置互不相同的强密钥：

| 变量 | 用途 |
|---|---|
| `POSTGRES_PASSWORD` | 数据库 |
| `JWT_SECRET` | 访问令牌（≥32，禁占位弱口令） |
| `SERVICE_API_TOKEN` | 受限的机器服务身份 |
| `SEED_PASSWORD` | 演示账号密码（≥12，仅开发环境） |

可选 AI：

| 变量 | 说明 |
|---|---|
| `AI_PROVIDER` | 默认 `rules`；真实 LLM 用 `deepseek` 等 |
| `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | OpenAI 兼容 chat |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 默认 SiliconFlow `Qwen/Qwen3-Embedding-0.6B`（1024 维） |

没有生成密钥时使用规则。向量不可用时使用词法检索，审计记录 `degrade_reason` 和 `embedding_fallback`。

`ALLOW_CITIZEN_SELF_REGISTER` 控制注册入口。注册、匿名建单、上传、AI 和导出的 `*_RATE_LIMIT_ATTEMPTS`、`*_RATE_LIMIT_WINDOW_SECONDS` 由 Compose 传入后端。完整键名与默认值见 [开发模板](../.env.example) 和 [生产模板](../.env.prod.example)。

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

docker compose exec -T backend alembic current   # 期望 0032 (head)
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

Backend 启动时执行 `alembic upgrade head`；迁移失败则拒绝起服务。

演示 Seed（容器内）：

```powershell
docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m app.seed
```

首次启动生产系统后，用交互终端建立首位管理员。命令只接受第一次调用，口令由终端输入。之后在管理端配置部门与用户。

```powershell
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml -p civicecho-prod exec backend python -m app.bootstrap_admin operator --display-name 管理员
```

## 4. S3 对象存储

- Bucket：附件 `tingting-attachments`；KB `tingting-kb`（可由 `OBJECT_STORAGE_BUCKET` / `KB_UPLOAD_BUCKET` 覆盖）。
- 上传路径：魔数校验 →（生产）ClamAV → 扫描通过后才 `put`。
- 知识库解析每个后端进程最多两个并发子进程。单份文档最多 20 MiB 和 50 万个正文字符，PDF 最多 400 页。解析超时 15 秒，Linux 子进程地址空间上限 384 MiB。管理员可按页面提示拆分或重试。
- 开发栈继续读取原有 MinIO 演示卷，仅供隔离本地演示。生产默认使用 SeaweedFS 新卷。不得把旧 MinIO 数据目录挂进 SeaweedFS。
- `PRODUCTION_OBJECT_STORAGE_ENDPOINT` 可配置批准的外部 S3 端点，并用 `OBJECT_STORAGE_SECURE=true` 启用 TLS。外部服务须预建两个 bucket，授权应用读取、写入和删除相应对象。内置服务仍可随 Compose 管理。
- `scripts/backup-database.ps1` 只备份 PostgreSQL。需要附件和知识库恢复时使用联合备份。

## 5. ClamAV

- 开发默认 `MALWARE_SCAN_MODE=disabled`。
- 生产：`clamd` + `MALWARE_SCAN_REQUIRE_CLEAN=true`；解析严格匹配 `stream: OK` / `FOUND`。
- CI 用协议替身检查扫描接口。使用官方 ClamAV 验证部署时，可用 EICAR 标准测试样本确认接口返回 `422 MALWARE_DETECTED`。
- 离线部署前在联网机器按目标平台构建、拉取镜像并保存，记录所有镜像摘要。在目标机器加载镜像后以 `--no-build --pull never` 启动。提前将经过来源及新鲜度校验的 ClamAV 签名库部署到 `clamav_data`，按维护窗口更新库并复验健康及 EICAR。可用 `CLAMAV_IMAGE` 固定目标镜像。

## 6. Caddy

- `Caddyfile` 的站点由 `SITE_ADDRESS` 配置。网关统一路由页面与 API，拦截 `/docs`、`/redoc`、`/openapi.json` 和 `/metrics`。内部探针走回环。Nginx 为通知与 AI 的 SSE 路径关闭代理缓冲。

## 7. 备份与恢复

在维护窗口阻断外部写入，停止源项目 backend 与 worker。保持 PostgreSQL 和对象存储运行，使数据库和对象按同一个停写窗口导出。归档包含数据库引用的未删除工单附件和知识库源文件、对象大小与 SHA-256 清单，以及归档文件的校验和。存放在访问受控的存储目录。

```powershell
docker compose -p tingting-assistant stop backend worker
.\scripts\backup.ps1 -Project tingting-assistant -OutputDir D:\Backups\civicecho-cutover
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml -p civicecho-prod build backend
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml -p civicecho-prod up -d --wait postgres object-storage
.\scripts\restore.ps1 -Production -Project civicecho-prod -BackupDir D:\Backups\civicecho-cutover -Force
```

从生产源导出时指定 `-Production`，自定义配置路径可传 `-EnvFile`。迁移目标须沿用源项目的 bucket 名。恢复脚本要求空数据库和明确的目标项目，不覆写冲突对象。若对象恢复或检查失败，目标项目保持停止，保留源项目并在新的空目标上重试。联合恢复完成后启动目标，核对 Alembic head、用户权限、附件与知识库样本再切入口。切换前可重新启动原项目回退。目标开始接收新写入后，先安排反向数据同步，再考虑回退。

旧 `minio/objects.tar` 套件只能先恢复到隔离的兼容 MinIO 项目，再用 `backup.ps1` 重新导出可迁移归档。

`docker compose down` 保留 volume；`down -v` 永久删除数据。E2E 使用项目名 `tingting-e2e`，不碰开发卷。

## 8. 安全边界（代码已有）

- `AuthorizationPolicy` 为权限单一真相源；前端守卫不可替代后端。
- JWT + Argon2；登录限流（`login_attempts`）。
- FastAPI Orchestrator 统一分发对话请求。应用与模型准入按用户、连接来源及会话执行限流或预算约束。匿名请求在代理地址无法区分时可能共用额度。
- 知识库生成回答不使用语义缓存，每次重新检索当前有权访问且已发布的文档，避免文档撤回、权限或内容变更后返回旧答案。
- 生产 fail-fast：弱密钥、宽 CORS、未启用恶意扫描等可拒启。
- `/metrics`：需 `MONITORING_TOKEN` 或 admin JWT（`backend/app/api/dependencies.py:require_metrics_access`）。
- 日志递归脱敏；`integration_events` 存 hash 不存凭据原文。
- 开发 Backend 端口默认绑 `127.0.0.1`。生产 Backend 无宿主机端口映射。

CI 扫描后端 Python 锁文件和前端 npm 依赖树。 [GitHub Actions 工作流](../.github/workflows/ci.yml)

`ANONYMOUS_RETENTION_DAYS` 默认 30 天。Worker 清理超期匿名 AI 用量及无答案记录。浏览器聊天保留期为 24 小时，工单及其审计按业务记录管理。

## 9. 可观测性

- `X-Request-ID` → ContextVar → 结构化日志 / `audit_logs` / `ai_usage_logs` / 响应头。
- `X-Trace-ID` 标记 OpenTelemetry 请求链。RAG 和模型调用产生子 span，通知 outbox 持久化 `traceparent` 并关联 Worker 投递。部署可设置 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` 使用 OTLP HTTP collector；为空时输出到日志。
- `/metrics` 的阶段延迟 p50/p95 使用每进程最近 2048 个样本。单进程本地数据适合回归对比，跨进程聚合使用 collector。
- 后端 `/health/live` 检查进程存活。后端 `/health/ready` 检查数据库，生产还验证两个 bucket。Worker 的 `/health/ready` 单独检查最近一次成功扫描。
- Worker 负责 SLA 临期与通知 outbox 重试。
- AI 成本字段 `estimated_cost_rmb` 为**估算**，非供应商真实账单。
- SSE 流包括通知未读数与增量，以及对话和知识库回答。流式结束事件记录路由、引用、耗时及降级原因。
- 未内置 ELK/Prometheus 全家桶；生产可采集容器 stdout，保留 JSON 与 `request_id`。

## 10. 回滚原则

先备份再换镜像。Schema 优先前向修复；非必要不自动 `alembic downgrade`。必须回滚时用发布前 custom-format dump，在隔离环境验证后再切换。
