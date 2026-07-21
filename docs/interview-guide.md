# 倾听助手面试指南

## 30 秒项目介绍

倾听助手是一个面向政务诉求协同的全栈作品。我保留了 Rasa 原英文 Helpdesk 和 handoff 能力，在其上完成中文诉求登记，并用 FastAPI、PostgreSQL 和 React 实现市民、坐席、部门人员、管理员四角色闭环。项目的亮点不是页面数量，而是权限、状态机、乐观锁、幂等、审计、正式答复、市民评价重办、PostgreSQL 会话持久化、Worker 可靠通知、接入 DeepSeek 但保留规则降级的人机协同边界、八服务 Docker（生产 override 追加 Caddy/ClamAV）、PostgreSQL + MinIO 联合备份恢复和三浏览器 75 条 E2E 都能实际运行。

## 两分钟展开顺序

1. 业务问题：自然语言入口与跨角色办理脱节。
2. 架构选择：Rasa 管对话，Backend 管可信业务状态，PostgreSQL 管持久化（含 Rasa Tracker），Action 只做适配，Worker 管异步扫描与通知。
3. 最难部分：对话到事务的一致性、状态机权限、并发冲突和旧 Rasa 兼容。
4. 工程质量：迁移、Seed、健康检查、日志审计、联合备份恢复、生产 config guard、CI、75 条 E2E。
5. AI 边界：接入 DeepSeek 生成摘要/风险/草稿/部门建议，`advisory_only=true` 不改状态，无密钥自动降级规则，全程可审计。
6. 边界意识：V1.x 是单机 Compose 展示版（生产 override 含 HTTPS/扫描），真正生产化还需集中日志、HA 和灾备演练。

## 常见问题与回答要点

### 为什么不用 Rasa 直接写数据库？

- 对话 Action 不是业务真相源，重试、并发和扩容会放大一致性问题。
- Backend 统一状态机、授权、幂等、事务和审计，Action 只使用受限服务身份。
- 这样 Web 页面和对话入口共享同一套规则。

### 为什么不是微服务？

- 当前领域与团队规模不足以抵消分布式事务、部署和可观测性成本。
- 八个容器是运行职责分离（含异步 worker），不代表把业务代码强行拆成多个服务。
- 先保持模块化单体；只有独立扩缩容、数据所有权或团队边界成立时才拆。

### 四角色权限如何保证？

- 前端守卫只改善体验，所有真实授权在 Backend 的 `AuthorizationPolicy`。
- 权限同时包含“能做什么”和“能看哪些数据”。
- 越权返回安全错误并写审计，服务身份不会继承管理员权限。

### 工单并发怎么处理？

- 客户端提交读取时的 `version`。
- 服务端在合法状态转换中原子递增版本；不一致返回 409 `VERSION_CONFLICT`。
- 前端提示“数据已被他人更新”并刷新，避免最后写入者静默覆盖。

### 如何防止重复创建工单？

- 创建请求带 `idempotency_key`。
- Repository 对键做唯一约束；重试返回原结果并标记 replay。
- 对话层失败不会假装已经创建成功。

### Rasa 的职责是什么？

- NLU、实体提取、对话策略、表单槽位和回复编排。
- Duckling 提供时间/邮箱结构化提取；Action 连接 Backend 或可选 ServiceNow。
- 工单状态、权限和审计不放在 Rasa tracker 中。

### 为什么不升级 Rasa？

- V1.0 封版要求保护既有模型、英文 Helpdesk、ServiceNow 与 handoff 资产。
- 本轮把 Backend 的 Starlette 安全升级与 Rasa 依赖树隔离，减少联动风险。
- Rasa 主版本迁移作为独立项目，需要重新训练、指标对比和全链路验收。

### Starlette 公告如何处理？

- 先用调用点盘点判断项目是否存在 `FileResponse`、`StaticFiles`、multipart、`request.form()`、`HTTPEndpoint` 或基于 URL path 的鉴权。
- 再独立升级 FastAPI/Starlette，执行 Backend、Action、Rasa、前端、E2E、Docker 回归。
- V1.0 保留通过回归的 FastAPI 0.139.0 + Starlette 1.3.1；不是只靠“当前不可利用”长期搁置。

### 健康检查为什么分 live 和 ready？

- live 只回答进程是否存活，避免依赖故障导致无限重启。
- ready 检查数据库，告诉编排与流量入口当前能否服务。
- 演示脚本还检查迁移、Seed、登录、Rasa 和跨服务查询，覆盖“healthy 但业务不可用”。

### 日志和审计有什么区别？

- 应用日志用于排障，写 stdout，带 `request_id` 且递归脱敏。
- 审计日志是业务证据，记录主体、动作、资源、结果和关联请求。
- 两者都不记录密码、Authorization、Cookie 或完整身份证号。

### 如何证明系统真的可复现？

- 基础镜像用标签加 digest；前端 `npm ci`；Backend 有完整生产锁文件。
- Backend 启动先执行 Alembic；Seed 幂等且密码只从环境变量传入。
- `check-demo.ps1` 从环境检查到跨服务查询给出 8 个明确关卡。

### 测试策略是什么？

- 单元/服务测试覆盖状态机、权限、时间、错误 envelope 和 Repository。
- Rasa 分别做数据校验、Core、NLU 与真实 Action 链路。
- Playwright 用独立数据库和 Compose 项目，Chromium/Firefox/WebKit 各执行 21 条。

### 如果上线，第一批要补什么？

- 外部秘密管理、TLS/WAF/可信反代、PostgreSQL 托管高可用、集中日志告警。
- OIDC/组织账号、Redis 限流与 tracker、对象存储、备份恢复 RTO/RPO 演练。
- 容量测试、SLO、灰度发布与依赖升级节奏；不是立即拆微服务。

## 可主动展示的证据

- `ENGINEERING.md` / `PRODUCT.md`：架构、调用链、权限和状态机。
- `docs/final-test-report.md`：实际回归数字与验收结论。
- `scripts/check-demo.ps1`：可运行的一键检查，不是静态 PPT。
- `frontend/e2e/workflows.spec.ts`：真实四角色闭环、降级和并发冲突。
- `backend/app/services/ticket_service.py` 与 `authorization.py`：核心业务规则。

## 避免夸大的表述

- 不把单机 Compose 说成“生产高可用微服务”。
- 不把规则/NLU 系统说成“大模型智能客服”。
- 不声称已接真实政务或 ServiceNow；默认是本地兼容模式。
- 不只报测试数量，要能解释关键失败路径和数据隔离方式。
