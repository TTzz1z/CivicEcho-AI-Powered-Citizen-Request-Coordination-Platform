# 第四阶段：转派、退回和多部门协同

## 交付结论

`tickets` 继续作为市民诉求主单，部门办理改为独立的 `work_orders`。一个主单可以同时包含一个有效主办任务、多个协办任务和复核任务。历史单部门接口保持兼容：旧的派发操作会同步生成主办任务，旧数据由 `0007` 迁移自动回填。

## 数据结构

### Ticket 主单

主单保存市民原始诉求、统一状态、SLA、最终公开答复和协同状态。新增协同状态：

| 状态 | 含义 |
|---|---|
| `none` | 尚未进入部门协同 |
| `awaiting_citizen` | 坐席已退回，等待市民补充材料 |
| `awaiting_dispatch` | 部门已退回，等待坐席重新派发 |
| `in_progress` | 一个或多个部门正在办理 |
| `awaiting_summary` | 所有有效任务已提交，等待主办汇总 |
| `disputed` | 责任归属存在争议，等待管理员协调 |
| `completed` | 主办已形成统一最终答复 |

### WorkOrder 部门任务

任务角色为 `primary`、`support`、`review`，状态为 `pending`、`processing`、`returned`、`transferred`、`submitted`、`cancelled`。每个任务独立保存：

- 处置部门和指定责任人；
- 任务要求；
- 本部门结果摘要、措施、结果类型、公开内容和内部备注；
- 转派来源、退回原因和乐观锁版本；
- 独立的 `work_order_history` 操作历史。

转派不会覆盖原任务。原任务进入 `transferred`，新部门获得一条带 `source_work_order_id` 的新任务，因此责任链可完整追溯。

## 业务闭环

1. 坐席可在待受理或已受理阶段要求市民补充材料。
2. 市民上传附件并提交补充说明，主单回到坐席继续处理。
3. 坐席或管理员创建主办、协办和复核任务，可指定责任人。
4. 部门可开始办理、退回坐席或转派其他部门。
5. 每个有效任务分别提交部门处理结果。
6. 所有有效任务提交后，主单进入 `awaiting_summary`。
7. 只有主办部门责任人或管理员可汇总最终答复，主单进入 `resolved`。
8. 参与部门或坐席可发起归属争议，只有管理员可给出协调结论并重新指定主办任务。

多部门主单不能通过旧 `/resolve` 接口绕过协同规则；后端会返回 `COLLABORATION_SUMMARY_REQUIRED`。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/tickets/{id}/supplement-request` | 坐席退回市民补充材料 |
| POST | `/api/v1/tickets/{id}/supplement` | 市民提交补充说明 |
| GET/POST | `/api/v1/tickets/{id}/work-orders` | 查询/创建部门任务 |
| POST | `/api/v1/tickets/{id}/work-orders/{work_order_id}/assign` | 指定责任人 |
| POST | `/api/v1/tickets/{id}/work-orders/{work_order_id}/start` | 开始办理 |
| POST | `/api/v1/tickets/{id}/work-orders/{work_order_id}/return` | 退回坐席重新派发 |
| POST | `/api/v1/tickets/{id}/work-orders/{work_order_id}/transfer` | 部门间转派 |
| POST | `/api/v1/tickets/{id}/work-orders/{work_order_id}/submit` | 提交本部门结果 |
| POST | `/api/v1/tickets/{id}/summary` | 主办汇总最终答复 |
| POST | `/api/v1/tickets/{id}/dispute` | 发起责任归属争议 |
| POST | `/api/v1/tickets/{id}/dispute/resolve` | 管理员协调争议 |
| GET | `/api/v1/departments/{id}/staff` | 获取可指定责任人 |

主单操作使用 Ticket `version`，任务操作使用 WorkOrder `version`。版本不匹配统一返回 HTTP 409。

## 验证

```powershell
docker compose up -d --build
docker compose exec -T backend alembic current
docker compose exec -T backend pytest tests -q
$env:LOCAL_SEED_PASSWORD='<本地演示密码>'
python scripts/docker_phase4_integration.py
cd frontend
npm test -- --run
npm run build
```

真实 Docker 集成脚本覆盖：市民补充、主办退回、重新派发、协办转派、复核任务、三个部门分别提交、争议协调和主办汇总。
