# 数据库设计（v1.0.0）

技术基线：PostgreSQL 16 + pgvector、SQLAlchemy 2.0、Alembic。当前 head = **0023**（`ai_suggestions` 增加 `ticket_advice` 类型与 `adopted|adopted_with_edits|rejected` 审核决策）。

## 核心表

| 表 | 用途 | 关键字段 / 约束 |
|---|---|---|
| `departments` | 部门主数据 | code、name、is_active |
| `users` | 账号 | role ∈ citizen/agent/department_staff/admin；Argon2 password_hash |
| `tickets` | 诉求主表 | `ticket_id` 唯一、`version` 乐观锁、`idempotency_key`、SLA 截止 |
| `ticket_status_history` | 业务处理留痕 | operation_type、previous/current_status、visibility |
| `work_orders` / `work_order_history` | 部门任务 | task_type、status、version；与父票同事务创建/启动 |
| `kb_documents` | 知识库文档 | status、visibility、`active_index_batch`、`replaces_doc_id`、`issuing_authority` |
| `kb_chunks` | 分块 + 向量 | `embedding`、`embedding_model`、`embedding_dimension`、`embedding_fallback`、`index_batch_id` |
| `ai_suggestions` | AI 建议证据链 | `suggestion_type` 含 `ticket_advice`；`review_decision` 三态 |
| `ai_usage_logs` | AI 用量审计 | capability、provider、model、tokens、degrade_reason |
| `audit_logs` | 业务审计 | actor、action、resource、details（含 advice_id/snapshot_hash） |
| `ticket_attachments` | 附件元数据 | MinIO object key；上传前 ClamAV/魔数校验 |

## 发布与索引

1. 新版本先写入 staging `index_batch_id`；
2. `index_status=ready` 后切换 `active_index_batch` 并 `PUBLISHED`；
3. 之后才把旧 `replaces_doc_id` 标为 `WITHDRAWN`；
4. 失败时旧版保持 `PUBLISHED` + 旧 batch 可检索；
5. `FOR UPDATE` 防止并发 building 产生多个 active batch。

## 并发与索引

- 工单更新：`WHERE version=:expected` 原子递增，冲突 409。
- Embedding 检索仅 `embedding_fallback='none'` 且 model/dimension 匹配。

## 迁移验证

本地/CI：`alembic upgrade head` + `alembic check`（无漂移）。历史 volume 从早期 revision 可连续升级到 0023。
