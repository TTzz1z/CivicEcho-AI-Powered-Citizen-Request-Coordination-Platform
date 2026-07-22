# 日志与可观测性

> **【已收敛】** 现行可观测性说明已并入 **[DEPLOYMENT.md](../DEPLOYMENT.md)**。补充：`GET /metrics` 需 `MONITORING_TOKEN` 或 admin JWT；无业务 SSE。

## request_id 链路

浏览器 Axios 为 Backend 与 Rasa 请求生成随机 request_id。Nginx 透传 `X-Request-ID`；Backend 校验格式、写入 ContextVar、JSON 系统日志、错误日志和独立审计表，并在响应头返回。Rasa 3.x 内置 REST channel 不提取 metadata，因此本项目的 `RequestIdRest` channel 从请求头/JSON 提取同一 ID；Action Server 将其透传至 Backend，并记录调用路径、结果、HTTP 状态和耗时。

审计日志记录“谁对什么资源做了什么”，系统日志记录请求、异常、耗时和服务状态，两者职责分离。数据库业务操作通过审计表的 `request_id` 与系统请求日志关联。

## 健康检查

- `/health/live`：仅证明 Backend 进程存活，不访问数据库。
- `/health/ready` 与 `/api/v1/system/health`：执行 `SELECT 1`，PostgreSQL 不可用时返回 503 `DATABASE_UNAVAILABLE`。
- Frontend、Action Server、Rasa、Duckling 和 PostgreSQL 各有 Compose healthcheck。
- 前端每 30 秒探测 Backend 和 Rasa；任一离线时明确显示服务名称、自动重试和“未确认前不要重复提交”。

## 运维命令

```powershell
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 action_server
Invoke-WebRequest http://localhost:8001/health/live
Invoke-WebRequest http://localhost:8001/health/ready
```

本版本只使用容器标准输出和 PostgreSQL 审计表，没有引入重量级日志平台。生产可由宿主机现有日志收集器采集 stdout，但必须保留 JSON 原文和 request_id。
