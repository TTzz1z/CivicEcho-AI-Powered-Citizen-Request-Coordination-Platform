# 倾听助手项目约定

<!-- codex-project-bootstrap: complete -->

## 权威基线

- 产品范围和阶段顺序：`PRODUCT.md`、`ENGINEERING.md`、`UPGRADE-PLAN.md`。
- 已验证现状和已知缺口：`PROJECT-AUDIT.md`。审计结论不能被旧发布报告覆盖。
- 项目说明、架构和操作文档：`README.md` 与 `docs/`；若其描述与当前代码或审计证据冲突，应更新文档，不夸大能力。

## 代码与架构边界

- `backend/app` 是业务真相源；仅后端可以执行状态流转、权限判断、审计与业务持久化。
- Rasa 和 `actions` 必须通过服务身份调用后端，前端只调用公开 API；不得旁路写数据库或由客户端任意写状态。
- 所有状态变更使用命名动作接口，维护幂等键和版本冲突语义；AI 始终是 `advisory_only`。
- `backend/migrations` 是唯一 schema 演进路径。数据库迁移、备份恢复、认证授权、附件安全、限流和 worker/outbox 属于高风险改动。
- 不引入 Kubernetes、重型检索/消息组件、自动行政决策或未配置的外部集成。

## 安全与生成内容

- `.env`、数据库、MinIO 对象、备份、测试结果和截图不应作为源码或证据中的秘密来源。使用 `.env.example` 仅记录非秘密配置键。
- 不硬编码凭据、令牌、Cookie、个人数据或外部服务地址；未配置集成必须显式标为不可用。
- 不执行提交、推送、重置、清理、删除数据卷或破坏性数据库操作，除非用户明确要求。

## 常用验证

- Compose：`docker compose config -q`、`docker compose up -d --build --wait --remove-orphans`、`docker compose ps`。
- 后端/迁移：在 `backend` 容器执行 `alembic check` 与 `pytest -q`；迁移改动另验空库、升级和 seed 幂等。
- 前端：在 `frontend` 执行 `npm run lint:types`、`npm test`、`npm run build`。
- Rasa：使用现有容器和模型执行 `rasa data validate`、Core/NLU 回归；不得用放大 timeout 掩盖卡死。
- 阶段完成时记录真实命令、退出码、通过结果、未验证项和剩余风险。

## 阶段执行与审查

- 严格按 `ENGINEERING.md` 的阶段一至阶段四顺序；一个阶段验收通过前不进入下一阶段。
- 常规阶段完成后执行一次 stage review。认证授权、迁移、幂等/重试、备份恢复、附件扫描、限流、AI 权限或生产部署的改动需按高风险阶段审查。
- 项目级审查重点：权限和状态机不可绕过、迁移与 ORM 一致性、任务幂等性、备份恢复完整性，以及文档与真实证据一致性。
