# 倾听助手 V1.0 项目总览

## 项目背景与业务价值

倾听助手（Tingting Assistant）面向市民诉求受理场景，把“自然语言登记—人工受理—部门办理—结果确认—审计追踪”放进一条可演示、可测试的业务链路。它解决三个典型问题：市民不知道该找哪个部门，坐席与部门之间缺少统一工单状态，管理人员缺少可追责的数据视图。

V1.0 的重点不是堆叠页面，而是证明一个小型业务系统可以同时具备对话入口、严格状态机、四角色权限、持久化、可观测性、备份恢复和自动化质量门禁。原英文 Helpdesk、ServiceNow 适配和人工 handoff 资产继续保留，与中文政务诉求链路并存。

## 系统架构

```mermaid
flowchart LR
    U["市民 / 坐席 / 部门 / 管理员"] --> F["Frontend\nReact + Nginx"]
    F -->|"JWT / REST API"| B["Backend\nFastAPI"]
    F -->|"REST webhook"| R["Rasa Server"]
    R -->|"时间与邮箱实体"| D["Duckling"]
    R -->|"Custom Action"| A["Action Server"]
    A -->|"服务令牌 / 工单 API"| B
    B -->|"SQLAlchemy / Alembic"| P[("PostgreSQL")]
    A -.->|"可选；默认本地模式"| SN["ServiceNow"]
```

六个 Docker 服务的职责如下：

| 服务 | 责任 | 健康检查 |
|---|---|---|
| frontend | 静态页面、SPA 路由、Backend/Rasa 反向代理、安全响应头 | `/healthz` |
| backend | 登录、权限、工单状态机、管理、统计、审计 | `/health/live`、`/health/ready` |
| postgres | 用户、部门、工单、处理记录与审计持久化 | `pg_isready` |
| rasa | NLU、对话策略、表单和 tracker | `/status` |
| action_server | 中文诉求、旧 Helpdesk、ServiceNow、handoff 自定义 Action | `/health` |
| duckling | 中文时间与邮箱等结构化实体提取 | TCP 8000 |

## 六服务调用链路

```mermaid
sequenceDiagram
    actor Citizen as 市民
    participant UI as Frontend/Nginx
    participant Rasa as Rasa
    participant Duckling as Duckling
    participant Action as Action Server
    participant API as FastAPI Backend
    participant DB as PostgreSQL

    Citizen->>UI: 输入诉求
    UI->>Rasa: POST /webhooks/rest/webhook
    Rasa->>Duckling: 提取时间/邮箱
    Duckling-->>Rasa: 标准化实体
    Rasa->>Action: 表单校验/创建工单
    Action->>API: Bearer SERVICE_API_TOKEN
    API->>DB: 事务写入工单、历史、审计
    DB-->>API: 工单编号与版本
    API-->>Action: 统一响应 envelope
    Action-->>Rasa: 文本 + custom payload
    Rasa-->>UI: 对话回复与详情入口
    UI-->>Citizen: 展示工单编号
```

## 工单状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 创建
    pending --> accepted: 坐席受理
    pending --> rejected: 坐席/管理员拒绝
    accepted --> assigned: 坐席/管理员派发
    assigned --> processing: 部门/管理员开始处理
    processing --> processing: 添加处理记录
    processing --> resolved: 部门/管理员标记解决
    resolved --> processing: 市民不满意/工作人员退回重办
    resolved --> closed: 市民满意确认或管理员说明依据代办结
    rejected --> [*]
    closed --> [*]
```

每次写操作都携带当前 `version` 和非空备注。Backend 在同一事务内校验角色、数据范围、合法状态边并执行 `version + 1`；旧版本返回 409，避免并发覆盖。

## 四角色权限

| 能力 | 市民 citizen | 坐席 agent | 部门 department_staff | 管理员 admin |
|---|---|---|---|---|
| 数据范围 | 本人创建 | 待受理、未派发 | 本部门 | 全部 |
| 创建诉求 | 是 | 是 | 否 | 是 |
| 受理、拒绝、派发 | 否 | 是 | 否 | 是 |
| 处理、记录、解决 | 否 | 否 | 本部门 | 是 |
| 最终办结 | 否 | 否 | 否 | 是 |
| 用户、部门、审计、看板 | 否 | 否 | 否 | 是 |

后端 `AuthorizationPolicy` 是权限规则唯一入口；前端路由守卫负责体验，不能替代后端授权。

## 核心技术难点与解决方案

1. 对话与事务系统的一致性：Action Server 不再保存进程内主数据，而是用独立服务令牌调用 Backend；创建使用幂等键，Backend 统一写工单、历史和审计。
2. 多角色数据隔离：把角色、数据范围和动作权限集中到策略层，API、测试和 UI 共用相同业务语义，并覆盖越权失败用例。
3. 并发办理：工单版本号实现乐观锁；UI 收到 409 后提示并刷新，不静默覆盖他人操作。
4. Rasa 旧资产兼容：Rasa Core 3.6.20、SDK 3.6.2 与重新训练的 v1.1.0 模型固定部署；英文 Helpdesk、ServiceNow 和 handoff 由独立对话回归保护。
5. 可复现交付：六服务 Compose、Alembic 自动迁移、幂等 Seed、镜像 digest、Python/Node 锁文件和三浏览器独立 E2E 共同保证复现。
6. 安全与排障：短期 JWT、Argon2、服务身份、限流、请求体/超时、安全头、结构化日志、`request_id`、审计和 live/ready 分离。

## 测试与质量数据

当前门禁包含 Python 编译与 Ruff、Backend 18 条测试、Action 21 条测试、Rasa 数据校验、Core 24 条故事、NLU 测试、TypeScript、Vitest 12 条、生产构建、Docker 集成和 Playwright 三浏览器各 21 条，共 63 条 E2E。V1.0 基线结果见 [第七轮发布报告](round-7-release-report.md)。

## 项目边界

V1.0 是可展示的工程化单体系统：不接真实政务平台，不引入大模型/RAG，不包含 Kubernetes、ELK、Prometheus，也不以当前单机 Compose 形态宣称生产高可用。演进建议见 [生产化路线图](production-roadmap.md)。
