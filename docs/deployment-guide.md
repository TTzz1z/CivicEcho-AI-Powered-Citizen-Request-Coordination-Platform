# 部署指南

## 标准流程

1. 安装 Docker Desktop/Compose v2，确认 `models/tingting-v1.0.0.tar.gz` 存在。
2. 复制 `.env.example` 为 `.env`，使用安全随机生成器设置 PostgreSQL 密码、JWT 密钥和服务令牌。
3. 生产环境设置 `APP_ENV=production`、精确 `CORS_ORIGINS` 和 `RASA_CORS_ORIGIN`。不要配置 `*`。
4. 通过 `SEED_PASSWORD` 临时环境变量执行 `scripts/start-demo.ps1`；该命令会启动并执行 8 项演示检查。正式环境可只运行 `docker compose up -d --build --wait`，再由受控初始化流程建账号。
5. 检查 `docker compose ps` 六服务均 healthy、`alembic current` 为 head。

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
