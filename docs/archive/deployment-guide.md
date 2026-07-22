# 部署指南

> **【已收敛】** 现行部署 / 安全 / 备份 / 可观测性请以 **[DEPLOYMENT.md](../DEPLOYMENT.md)** 为准。本文保留作历史稿；文中 Alembic 等表述可能过期（当前 head=`0025`）。

## 标准流程

1. 安装 Docker Desktop/Compose v2，确认 `models/tingting-v1.3.0.tar.gz` 存在。
2. 复制 `.env.example` 为 `.env`，使用安全随机生成器设置 PostgreSQL 密码、JWT 密钥和服务令牌。
3. 如需真实向量检索，配置 `EMBEDDING_API_KEY` 与 SiliconFlow `EMBEDDING_BASE_URL`；留空则走 hash fallback，并在审计中标记 `embedding_fallback`。
4. 生产环境设置 `APP_ENV=production`、精确 `CORS_ORIGINS` 和 `RASA_CORS_ORIGIN`。不要配置 `*`。生产附件扫描使用 `MALWARE_SCAN_MODE=clamd` + `MALWARE_SCAN_URL=clamav:3310`（见 `docker-compose.prod.yml`）。容器内 MinIO 保持 HTTP（`OBJECT_STORAGE_SECURE=false`），对外 HTTPS 由 Caddy 终止。
5. 通过 `SEED_PASSWORD` 临时环境变量执行 `scripts/start-demo.ps1`；该命令会启动并执行演示检查。正式环境可只运行 `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait`，再由受控初始化流程建账号。
6. 检查 `docker compose ps`：**开发 8 服务**均 healthy；生产 override 另含 `caddy` 与 `clamav`。`alembic current` 应为现行 head（写作时为 `0025`；以仓库 `migrations/versions` 与 `docs/TESTING.md` 为准）。

Backend 容器启动时先执行 `alembic upgrade head` 和 `alembic current`，迁移失败会阻止 Uvicorn 启动。Nginx 对 API/对话上游设置连接与读取超时、1 MiB 请求体限制和安全响应头。

## 发布检查

```powershell
docker compose config -q
docker compose up -d --build --wait
docker compose exec -T backend alembic current
Invoke-RestMethod http://localhost:8001/health/live
Invoke-RestMethod http://localhost:8001/health/ready
docker compose ps
.\scripts\check-demo.ps1
```

## 回滚

应用镜像回滚前先备份数据库。数据库结构优先前向修复，不建议自动执行 Alembic downgrade。若必须恢复，使用发布前的自定义格式 dump，并按备份恢复文档在隔离环境验证后切换。

## Docker Volume

默认命名卷为 `<project>_postgres_data`。`docker compose down` 保留数据，`docker compose down -v` 永久删除数据。E2E 使用 `tingting-e2e` 项目名，因此不会接触开发卷。
