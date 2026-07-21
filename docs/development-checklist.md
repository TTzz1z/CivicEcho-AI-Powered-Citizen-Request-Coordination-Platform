# 后续开发检查清单

## 开始任务前

- [ ] 明确本次只改 NLU、对话、Action、后端或前端中的哪些边界。
- [ ] 从 `.env.example` 创建本地 `.env`，确认未放入真实生产凭据。
- [ ] `docker compose run --rm rasa data validate` 通过。
- [ ] 记录当前模型、数据和测试基线，避免同时升级 Rasa。

## NLU 与对话数据

- [ ] Intent 有定义、正例、近邻反例和 out-of-scope 边界。
- [ ] 训练/验证/测试样本不重复，不用训练集精度代替泛化效果。
- [ ] 实体标注一致；时间、地点、对象和事件有缺失/歧义样本。
- [ ] 新 Form 覆盖补全、改口、拒绝、取消、打断、恢复和确认。
- [ ] Rules 只承载确定性路径；TED Stories 覆盖需要泛化的路径。
- [ ] `rasa data validate` 无新增冲突警告。

## Actions 与外部系统

- [ ] Action 输入槽位做类型、长度和必填校验。
- [ ] 外部请求有连接/读取超时、可控重试、错误码映射和日志 trace ID。
- [ ] 创建类操作具备幂等键，不因 Rasa 重试重复建单。
- [ ] 日志不记录密码、证件号、手机号、完整地址等敏感信息。
- [ ] local/mock mode 返回确定结果，测试不依赖随机数。
- [ ] ServiceNow/未来工单平台分别有契约测试，生产凭据不进入测试环境。

## PostgreSQL / Redis / FastAPI

- [ ] Schema 变更使用迁移脚本并可回滚。
- [ ] PostgreSQL 是工单与审计事实源；Redis 只承载明确的临时用途。
- [ ] API 有版本、鉴权、RBAC、分页、统一错误结构和 OpenAPI 校验。
- [ ] Rasa Action 通过 gateway/repository 接口访问业务，不直接拼业务表 SQL。
- [ ] 健康检查区分 liveness/readiness，不泄漏内部配置。

## React 用户端与管理端

- [ ] 用户端与管理端按角色隔离路由和权限。
- [ ] 对话消息、表单和工单状态具备加载、空、错误、重试状态。
- [ ] 键盘导航、焦点、对比度和屏幕阅读器标签通过检查。
- [ ] 浏览器不持有 ServiceNow、数据库、Rasa Action Server 凭据。

## 测试与交付

- [ ] Action 单元测试通过。
- [ ] Rasa NLU 测试和端到端 stories 通过，失败样本已人工复核。
- [ ] Docker Compose 从空环境可构建、训练、启动并完成 REST smoke test。
- [ ] README、`.env.example`、架构图和迁移说明与实现同步。
- [ ] 生成物（`models/`、`results/`、`.env`、数据库）没有进入版本控制。
- [ ] 明确列出已验证、未验证、已知风险和回滚步骤。
