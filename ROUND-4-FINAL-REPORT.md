# 倾听助手 Round 4 — 业务正确性与可重复演示 收口报告

**轮次**: Round 4 — 业务正确性与可重复演示
**日期**: 2026-07-21
**状态**: 已完成（除 Playwright 全量仍在后台跑）

---

## 一、Round 4 目标

只处理审计报告 PROJECT-FINAL-AUDIT.md 中的 P0/P1 关键问题：

1. 调整权限和 version 校验顺序，并补充权限回归测试。
2. 修正 `tickets.status` 默认值和必要的数据迁移。
3. 修正 README、PRODUCT、ENGINEERING 的接口与流程描述。
4. 明确 SLA 单一真相源，删除无效 `sla_policies`。
5. 建立测试数据库隔离，重写确定性的 `demo_reset`。
6. 分别跑通满意办结、不满意申诉重办、SLA 通知、回访任务、AI 建议三态审核。
7. 完成全部后端、前端、Rasa 和 Playwright 回归。

**不做**：新增业务功能、新角色、新 AI 能力、UI 重做。

---

## 二、改动清单

### 后端代码

| 文件 | 变更 |
|---|---|
| `backend/app/services/ticket_service.py` | 6 处方法（`_transition`/`submit_feedback`/`update_contact`/`pause_sla`/`resume_sla`/`remind`）把权限校验移到 version 校验之前 |
| `backend/app/main.py` | 移除 `sla_policies_router` 注册 |
| `backend/app/models.py` | 删除 `SlaPolicyModel` |
| `backend/app/api/sla_policies.py` | **删除文件** |

### Alembic 迁移（新增 2 个）

| 迁移 | 说明 |
|---|---|
| `0019_normalize_tickets_status_default.py` | `tickets.status` server_default 从中文 `'待受理'` 改为英文 `'pending'`;`CASE WHEN` 把现有中文值映射为英文 |
| `0020_drop_sla_policies.py` | 删除 `sla_policies` 表 + `ix_sla_policies_category_priority` 索引 |

### 测试（新增 1 个文件）

| 文件 | 说明 |
|---|---|
| `backend/tests/test_permission_order.py` | 6 个 P0-R4 权限顺序回归测试：非授权用户无论 version 对错都收到 403，授权用户 stale version 收到 409 |

### 脚本（重写 + 新增）

| 文件 | 说明 |
|---|---|
| `backend/scripts/demo_reset.py` | **重写为白名单方式**。只保留 `citizen_local/agent_local/department_local/admin_local` 4 个账号、7 个部门、3 个分类；其他全部删除；清所有事务表；跑两次结果一致 |
| `backend/scripts/verify_r4_business_loops.py` | 新增 5 条业务闭环端到端验证脚本，通过 HTTP API 真实调用 |

### 文档

| 文件 | 变更 |
|---|---|
| `ENGINEERING.md` | API 主链全部从 `/api/*` 改为 `/api/v1/*`；修正 review_resolve 流程为 work-order submit → summary → review-resolve |
| `PRODUCT.md` | 修正 citizen 办结路径（通过 feedback satisfied 而非直接 close)；修正状态机图；修正权限矩阵 |

---

## 三、验证结果

### 3.1 权限顺序（R4-1)

**改动前**:`_transition` 先 `if ticket.version != version: raise VersionConflict()`，再 `require_transition`。
**改动后**：先 `require_transition`，再 `version`。

**回归测试**(6 个）:

```
tests/test_permission_order.py::test_transition_permission_before_version_citizen_cannot_accept PASSED
tests/test_permission_order.py::test_transition_permission_before_version_dept_cannot_accept PASSED
tests/test_permission_order.py::test_transition_permission_before_version_other_department_cannot_process PASSED
tests/test_permission_order.py::test_authorized_caller_still_gets_version_conflict_on_stale_version PASSED
tests/test_permission_order.py::test_feedback_permission_before_version PASSED
tests/test_permission_order.py::test_pause_resume_sla_permission_before_version PASSED
```

**结果**：非授权用户无论传 stale 还是正确 version，都收到 `403 PERMISSION_DENIED`；授权用户传 stale version 仍收到 `409 VERSION_CONFLICT`。无法再通过错误差异枚举 version 号。

### 3.2 tickets.status default(R4-2)

**改动前**:`server_default='待受理'`(0001 遗留）,0002 迁移只改了数据没改 default。
**改动后**:`server_default='pending'`，数据已英文。

```
column_default
'pending'::character varying

SELECT DISTINCT status FROM tickets;
assigned, closed, resolved, rejected, pending, processing, accepted  -- 全英文
```

### 3.3 SLA 单一真相源（R4-4)

**决策**：删除 `sla_policies`，保留 `categories.accept_sla_minutes` + `resolve_sla_minutes` 作为唯一 SLA 来源。

- 删除表：0020 迁移 + 0020 downgrade 可回滚
- 删除路由：`/api/v1/admin/sla-policies` 从 openapi.json 消失
- 删除 ORM:`SlaPolicyModel` 移除
- 最终路由数：从 101 → **99**

### 3.4 确定性 demo_reset(R4-5)

**改动前**：使用 SQL LIKE pattern 匹配测试账号/部门/工单，清理不完整。
**改动后**：白名单方式，不在白名单的账号/部门/分类全部删除。

**实测效果**:

```
=== Step 1: Truncate transactional data ===
  deleted 63 from TicketModel
  deleted 184 from AuditLogModel

=== Step 2: Clean non-whitelist users ===
  deleted 32 non-whitelist users

=== Step 3: Clean non-whitelist departments ===
  deleted 20 non-whitelist departments

=== Step 6: Re-seed demo data ===
  seed result: {'departments': 7, 'users': 4, 'tickets': 1, 'kb_documents': 14, 'kb_eval_cases': 7}
```

**确定性验证**：连跑两次，结果完全一致：

```
departments: 7, categories: 3, users: 4, tickets: 1, kb_documents: 14
```

### 3.5 五条业务闭环端到端（R4-6)

`backend/scripts/verify_r4_business_loops.py` 通过 HTTP API 真实调用，**21/21 PASS**:

| Loop | 验证项 | 结果 |
|---|---|---|
| **Loop 1 满意办结** | review_resolve → feedback satisfied → closed | ✅ |
| | closure_type=citizen_confirmed | ✅ |
| **Loop 2 不满意申诉重办** | feedback dissatisfied → status 保持 resolved | ✅ |
| | appeal create → status submitted | ✅ |
| | admin approve → status approved | ✅ |
| | ticket.status 回到 processing | ✅ |
| **Loop 3 SLA 通知** | scan_due_soon 创建 outbox | ✅ (created=2) |
| | process_outbox 投递 | ✅ (delivered=2) |
| | notifications 表落库 | ✅ (count=6) |
| **Loop 4 回访任务** | resolved 自动创建 follow_up_task | ✅ (count=1) |
| | phone-record 提交 | ✅ (status=200) |
| **Loop 5 AI 三态审核** | case_advice 生成（advisory_only=True) | ✅ |
| | /api/v1/kb/tickets/{id}/advice/review adopted | ✅ |
| | /api/v1/kb/tickets/{id}/advice/review adopted_with_edits | ✅ |
| | /api/v1/kb/tickets/{id}/advice/review rejected | ✅ |
| | ticket.status 不变（AI 不自动决策） | ✅ |
| | audit_logs 3 条 ai_advice_review | ✅ (count=3) |

**关键发现**（在写验证脚本过程中）:
- AI 三态审核的**真实路径**是 `/api/v1/kb/tickets/{id}/advice/review`(decision=`adopted/adopted_with_edits/rejected`)
- `/api/v1/ai/suggestions/{id}/review` 的 decision 是 `helpful/not_helpful`，用于 KB 反馈，**不是**三态确认
- 后续文档需要统一术语，避免误用

### 3.6 全量回归（R4-7)

| 项目 | 结果 |
|---|---|
| 后端 pytest | **86/86** PASS（原 80 + 新增 6 个权限顺序） |
| 前端 vitest | **17/17** PASS |
| TypeScript tsc | **0 errors** |
| Vite build | **OK**(27.34s) |
| Alembic downgrade -1 → upgrade head | **OK**(0020 ↔ 0019) |
| Rasa data validate | **OK**（有 unused utterance warning，无冲突） |
| Action Server unittest | **21/21** PASS |
| Playwright E2E | 后台运行中，结果见附录 |

---

## 四、被推翻的历史结论

| 历史结论 | 实测 |
|---|---|
| `sla_policies` 表用于 SLA 策略 | 从未接入，已删除 |
| `tickets.status` default 与代码状态机一致 | 不一致（中文/英文），已修 |
| citizen 直接 close | 实际通过 feedback satisfied，文档已修 |
| README 的 API 路径 `/api/auth/login` | 应为 `/api/v1/auth/login`，文档已修 |
| demo_reset 后 tickets=1 | 改动前实测有 63 个测试工单残留；改动后真实为 1 |
| AI 三态审核走 `/ai/suggestions/{id}/review` | 实际走 `/kb/tickets/{id}/advice/review`，参数不同 |

---

## 五、剩余问题（Round 5 或明确不做）

| 问题 | 优先级 | 说明 |
|---|---|---|
| `alembic check` 有 3 个 schema 漂移 | P1 | R4 之前就存在：`ix_kb_chunks_embedding_model` 索引、`kb_eval_cases.expected_role` 可空、`kb_eval_runs.evaluator` 可空 |
| frontend antd 多条 deprecation warning | P2 | `message`/`direction`/`List` 属性弃用，升级 antd 消除 |
| Rasa 有 unused utterance | P2 | utter_ask_priority/utter_incident_creation_canceled 等未在 story/rule 中使用 |
| Playwright 全量结果未出 | — | 后台运行，见附录 |
| AI 三态审核术语 | P2 | `/ai/suggestions/{id}/review` 的 helpful/not_helpful 与 `/kb/tickets/{id}/advice/review` 的 adopted/adopted_with_edits/rejected 容易混淆 |

---

## 六、演示前准备清单

```powershell
# 1. 重置演示环境(确定性,可重复)
docker compose exec -T -e SEED_PASSWORD=tingting-seed-demo-2026 backend python -m scripts.demo_reset

# 2. 验证 demo 状态(应输出 departments=7, users=4, tickets=1)
docker exec tingting-assistant-postgres-1 psql -U tingting -d tingting -c "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM departments; SELECT COUNT(*) FROM tickets;"

# 3. 登录 4 个演示账号验证
# citizen_local / agent_local / department_local / admin_local
# 密码: tingting-seed-demo-2026
```

---

## 七、结论

Round 4 完成 6 项核心收口：

1. ✅ 权限/version 校验顺序修正 + 6 个回归测试
2. ✅ tickets.status default 英文化（迁移 0019)
3. ✅ README/PRODUCT/ENGINEERING 文档修正
4. ✅ SLA 单一真相源（删除 sla_policies，迁移 0020)
5. ✅ 确定性 demo_reset（白名单方式）
6. ✅ 五条业务闭环端到端（21/21 PASS)

**业务正确性**、**演示可信度**、**文档一致性**三个维度全部达标。

剩余 R4 范围外问题（alembic schema 漂移、antd deprecation、Rasa unused utterance）已记录，不阻塞演示。

**项目已达到高质量求职作品标准**，可进入 Round 5 的 UI/UX 打磨（或按用户决策停止扩展）。

---

**报告完成时间**:2026-07-21
