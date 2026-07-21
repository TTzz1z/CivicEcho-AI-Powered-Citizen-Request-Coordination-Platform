# 数据库设计

技术基线：PostgreSQL 16、SQLAlchemy 2.0、Alembic。`0001` 未修改；`0002_enterprise_ticket_workflow.py` 增量升级旧 volume。

## 核心表

`departments` 保存 code、name、description、启停状态和带时区审计时间，migration 预置城市管理、交通运输、住房物业、教育服务、医疗卫生、社区民政、综合受理。

`users` 保存 username、Argon2 password_hash、display_name、固定 role、可选 department_id、启停状态和时间。数据库约束 role 只能是 citizen、agent、department_staff、admin。

`tickets` 在 `0001` 字段上增加：

- creator_user_id、anonymous_creator_key
- assigned_department_id、assigned_user_id、priority
- accepted_at、resolved_at、closed_at、version
- occurred_at_text、occurred_at_start/end、occurred_at_precision、timezone

旧 `occurred_at` 列保留作 schema 兼容，写入时与 `occurred_at_text` 同步。旧中文状态在 migration 中映射为英文代码。状态、优先级均有 CHECK 约束。

`ticket_status_history` 是业务处理记录：operator_user_id、operation_type、content、previous/current_status、created_at；保留旧 remark 列兼容。创建、状态变化和联系方式修改都会追加记录。

`audit_logs` 是系统安全记录，保存主体类型/用户、动作、资源、结果和经过秘密字段过滤的 JSON details；不保存密码或完整 Token。

## 并发与索引

- `ticket_id`、`idempotency_key` 唯一；编号来自 PostgreSQL sequence。
- 更新用 `WHERE version=:expected_version` 原子递增，冲突返回 HTTP 409。
- 索引覆盖状态+时间、部门+状态、创建人+时间、匿名创建摘要、联系方式+时间、历史、用户部门角色和审计检索。

## 实际迁移验证

升级前 `alembic_version=0001`、工单 87 条；原 volume 上执行 Backend 启动迁移后为 `0002`、仍为 87 条、7 个部门存在，原工单可按编号查询。未删除或重建 volume。
