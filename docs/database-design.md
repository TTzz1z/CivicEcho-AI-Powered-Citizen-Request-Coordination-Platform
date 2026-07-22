# 数据库设计（现行）

技术基线：PostgreSQL 16 + pgvector、SQLAlchemy 2.0、Alembic。

**当前 Alembic head = `0025`**（`0025_expand_municipal_categories`，`down_revision=0024`）。

近期相关迁移：

| Revision | 内容 |
|---|---|
| `0023` | `ticket_advice` 与 `adopted|adopted_with_edits|rejected` 审核决策 |
| `0024` | `ai_suggestions.suggestion_type` 增加 `triage_assistant` / `handling_assistant` |
| `0025` | 城市管理等市政叶子分类幂等 upsert（演示归口覆盖） |

核对命令：`alembic current` / `alembic heads` → 期望 `0025 (head)`。

## 核心表

| 表 | 用途 | 关键字段 / 约束 |
|---|---|---|
| `departments` | 部门主数据 | `code`（含 `general-intake` 综合受理）、`name`、`is_active` |
| `users` | 账号 | `role` ∈ citizen/agent/department_staff/admin；Argon2 `password_hash` |
| `tickets` | 诉求主表 | `ticket_id`、`status`、`version` 乐观锁、`idempotency_key`、`assigned_department_id`、`collaboration_status`、SLA 截止 |
| `ticket_status_history` | 业务处理留痕 | `operation_type`、`previous_status`/`current_status`、`visibility` |
| `work_orders` / `work_order_history` | 部门任务 | `task_type`（primary/support/review）、`status`、`version`；与父票同事务创建/启动 |
| `ticket_feedbacks` | 市民评价 | `rating`、`result`（含 `dissatisfied_recorded`）；满意才闭环 `closed` |
| `appeals` | 申诉 | `status` submitted → 管理员审核；**批准后**主单才回 `processing` |
| `kb_documents` | 知识库文档 | `status`、`visibility`、`active_index_batch`、`replaces_doc_id`、`issuing_authority` |
| `kb_chunks` | 分块 + 向量 | `embedding`、`embedding_model`、`embedding_dimension`、`embedding_fallback`、`index_batch_id` |
| `ai_suggestions` | AI 建议证据链 | `suggestion_type` 含 `triage_assistant`/`handling_assistant`/`ticket_advice`；`review_decision` |
| `ai_usage_logs` | AI 用量审计 | `capability`、`provider`、`total_tokens`、`estimated_cost_rmb`（估算）、`degrade_reason` |
| `audit_logs` | 业务审计 | actor、action、resource、`request_id`、details |
| `notifications` / `notification_outbox` | 通知与可靠投递 | 幂等键；worker 重试 |
| `follow_up_tasks` | 电话回访 | `handling_round`、`due_at`、`status` |
| `ticket_attachments` | 附件元数据 | MinIO object key；扫描状态 |
| `login_attempts` | 登录限流 | 共享 DB 限流 |

> `sla_policies` 表已在 `0020` 删除；SLA 写在 `tickets.accept_due_at` / `resolve_due_at`（按分类×优先级计算）。

## Ticket 与 WorkOrder 关系

```text
tickets (主单 status)
  └── work_orders[] (部门任务)
        primary / support / review
        pending → processing → submitted
                              └── 全部 submitted → collaboration_status=awaiting_summary
        主办 summary → collaboration_status=awaiting_review
                       （主单仍为 processing）
        坐席 review-resolve → 主单 resolved，collaboration_status=completed
```

要点（与 `work_order_service.py` 一致）：

- 部门 **submit / summary 不会**把主单直接设为 `resolved`。
- 坐席 **`review-resolve`** 才将主单设为 `resolved`。
- 市民 feedback 满意或管理员 `close` → `closed`。
- 申诉：`create_appeal` 不改主单状态；`review_appeal` 批准后主单 → `processing`。

## 发布与索引（KB）

1. 新版本写入 staging `index_batch_id`；
2. `index_status=ready` 后切换 `active_index_batch` 并 `PUBLISHED`；
3. 再将旧 `replaces_doc_id` 标 `WITHDRAWN`；
4. 失败时旧版保持可检索；
5. `FOR UPDATE` 防止并发 building。

## 并发

- 工单更新：`WHERE version=:expected`，冲突 `409 VERSION_CONFLICT`。
- Embedding 检索仅 `embedding_fallback='none'` 且 model/dimension 匹配。

## 迁移验证

```powershell
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic check
```

历史 volume 可从早期 revision 连续升级到 `0025`。本轮文档整理**未**在新库上重跑升降级实测 → 标 **未验证**（以 CI `backend-tests` / 本地输出为准）。
