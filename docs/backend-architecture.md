# 工单后端架构

## 分层与信任边界

```text
Rasa Action / API 用户
        │ Bearer 服务凭据 / JWT
        ▼
FastAPI Router ── 当前主体解析
        ▼
TicketService / AuthService
  ├─ AuthorizationPolicy（唯一权限规则入口）
  ├─ 状态机、时间校验、版本校验
  └─ 业务记录与审计触发
        ▼
Repository
  ├─ PostgreSQLTicketRepository
  └─ InMemoryTicketRepository（只用于单测）
```

Router 只做输入/输出和依赖注入，不写 SQL；状态转换、角色限制和版本冲突均在 Service/集中策略层执行。Action Server 使用独立 `SERVICE_API_TOKEN`，不冒充管理员；普通用户使用短期 JWT。

## 主要模块

- `api/dependencies.py`：解析 JWT 或服务凭据。
- `authorization.py`：四角色数据范围和操作权限。
- `security.py`：Argon2 密码哈希、HS256 JWT、匿名会话摘要。
- `services/ticket_service.py`：创建、查询、分页、状态机、派发、联系方式修改。
- `repositories/postgres.py`：查询构建、分页计数、乐观锁更新。
- `time_normalization.py`：保守中文时间规则；优先接受 Action/Duckling 的带时区结果。

## API

- `POST /api/v1/auth/login`、`GET /api/v1/auth/me`
- `GET /api/v1/departments`
- `POST/PATCH /api/v1/departments`、`GET/POST/PATCH /api/v1/users`（admin）
- `POST /api/v1/tickets`、`GET /api/v1/tickets/{ticket_id}`、`GET /api/v1/tickets`
- `POST /tickets/{id}/accept|assign|process|resolve|close|reject`
- `PATCH /tickets/{id}/contact`
- 兼容入口 `PATCH /tickets/{id}/status` 仍委托严格状态机，不允许任意跳转。

统一成功 envelope 为 `{"success":true,"data":...}`，错误为 `{"success":false,"error":{"code","message","details"}}`。500 响应不暴露内部异常。
