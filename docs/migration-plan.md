# 从 Helpdesk Assistant 迁移到倾听助手

原则：先维持已验证基线，再做可测试的小步迁移；不在一次提交中同时升级 Rasa、改目录、换语言和重写 Actions。

## 阶段 0：基线接管（本轮）

- [x] 升级并固定 Rasa 3.6.20 / SDK 3.6.2 / Python 3.10 兼容基线，重新训练 v1.1.0 模型。
- [x] 验证数据、训练和原有测试。
- [x] 增加 Compose、Action 镜像、REST credentials 和环境变量入口。
- [x] 保留 legacy Helpdesk 数据/Actions，记录风险。
- [x] 预留 `backend/` 和 `frontend/`。

## 阶段 1：最小中文政务垂直切片（第二轮已完成）

目标只做一条可测试闭环，不接复杂模型：

1. [x] 定义 `submit_complaint`、`submit_suggestion`、`policy_consultation`、`request_help` 四类意图边界。
2. [x] 定义 `event`、`location`、`time`、`target`、联系方式、描述和工单号。
3. [x] 新增统一 `public_request_form`，完成追问、摘要确认、取消和修改。
4. [x] 用确定性进程内 Mock 创建/查询工单并返回编号。
5. [x] 增加独立 NLU、Core/Story、Action 单测和 REST 烟测。

legacy IT intents 未删除，继续作为回归基线；中文数据和 Actions 已分别隔离在独立文件中。

## 阶段 2：业务边界与持久化

1. 在 `backend/` 初始化 FastAPI，仅提供版本化工单接口和健康检查。
2. 定义 `TicketRepository` / `TicketGateway` 接口，让 Rasa Action 不直接依赖数据库表。
3. PostgreSQL 保存工单、流转和审计；Redis 用于缓存/幂等/短期会话，不替代审计存储。
4. 使用 Alembic 管理迁移；所有写操作带 request/idempotency key。
5. Action Server 通过服务账号调用 FastAPI，增加超时、重试边界、错误码映射和链路 ID。

## 阶段 3：目录迁移

在测试全绿后单独执行机械迁移：

```text
rasa_bot/
├── actions/
├── data/
├── config.yml
├── domain.yml
├── endpoints.yml
└── credentials.yml
```

迁移时同步调整：Action Python import、Docker build context、Compose volume/workdir、Makefile、测试命令和 CI 路径。先复制并双路径验证，再删除根目录旧文件，避免一次移动导致基线丢失。

## 阶段 4：React 与管理后台

- `frontend/` 建立用户对话端和工单管理端，先共用设计 token，不复制业务状态机。
- 浏览器只访问 FastAPI/BFF；Rasa 与业务 API 的服务地址不暴露到客户端。
- 实现鉴权、权限、审计、脱敏、可访问性和异常恢复后再进入试点。

## 阶段 5：Rasa 版本决策

单独建立升级验证分支/任务，比较：

- Python/依赖安全支持周期；
- 训练数据和 Domain 迁移成本；
- Forms、Rules、Custom Actions 兼容性；
- 中文基准数据上的准确率、延迟和资源占用。

只有验证报告和回滚方案齐备后才升级，不能与阶段 1 的中文业务改造混在一起。

## 退出条件

每阶段必须具备：可复现启动命令、数据校验通过、自动化测试结果、配置模板、故障回滚说明，以及不含真实账号/个人信息的检查记录。
