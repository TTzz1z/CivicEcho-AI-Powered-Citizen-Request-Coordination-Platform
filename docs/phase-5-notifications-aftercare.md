# 第五阶段 P1：通知、回访和申诉

## 业务规则

### 通知

- P1 启用 `in_app` 站内通知；数据模型同时保留 `sms`、`wechat`、`email`、`government_message` 渠道值和投递状态，外部渠道当前返回“已预留”。
- 事件覆盖：工单创建成功、已受理、需要补充材料、已派发、即将超时、处理完成、等待市民确认、已办结，以及申诉提交、审核和结果。
- 通知按 `事件 + 工单 + 办理轮次/业务事件 + 收件人` 幂等，同一事件重复扫描不会重复入库。
- 即将超时定义为：工单未暂停、未进入终态，受理或办理截止时间位于未来 4 小时内。读取通知中心时会执行幂等扫描；生产部署可复用同一服务方法接计划任务。
- 用户只能读取和标记自己的通知；读取单条、全部已读均写审计。

### 自动回访和电话记录

- 每次工单进入 `resolved`（待市民确认）时，按办理轮次自动生成一个回访任务，最迟回访时间为 48 小时后。
- 回访任务状态：`pending -> in_progress -> completed`；工单由其他方式办结或申诉获准重办时，未结束任务转为 `cancelled`。
- 坐席和管理员可以记录电话回访。未接通/号码有误只能选择“继续回访”；电话确认办结必须已接通且满意度为“满意”或“基本满意”。
- 电话确认后，工单从 `resolved` 原子流转为 `closed`，`closure_type=phone_confirmed`；市民表示拟申诉时只发送提示，正式申诉仍须由市民本人提交。

### 市民申诉

- 仅工单创建人可以申诉，工单必须处于 `resolved` 或 `closed`。
- 申诉期限为处理完成或办结后 15 天；每张工单最多 2 次；同一时间只能有一个 `submitted/approved/reprocessing` 申诉。
- 状态流：`submitted -> rejected`，或 `submitted -> reprocessing -> completed`。审核通过与进入重新办理为同一事务，不保留无业务停留时间的中间态。
- 只有管理员可以审核。通过时工单进入 `processing`、办理轮次加一、清空原办结时间；驳回不改变工单状态。
- 重新办理再次进入 `resolved` 时，系统自动把公开答复写为申诉结果，申诉变为 `completed`，并按新轮次创建回访任务。

## 数据迁移与旧数据兼容

- Alembic 版本：`0008`。
- 新表：`notifications`、`follow_up_tasks`、`phone_follow_up_records`、`appeals`。
- `tickets` 新增 `handling_round`（默认 1）和 `appeal_count`（默认 0）；旧工单不补造历史通知或回访任务，避免伪造历史事实。
- 原工单状态、工单号、反馈、附件、协同任务和状态历史不变；`closure_type` 仅扩展 `phone_confirmed`。
- 回滚会删除第五阶段新数据和字段；执行前必须备份，不应在生产环境把 downgrade 当作数据恢复手段。

## API 与权限

| API | citizen | agent | department_staff | admin |
|---|---:|---:|---:|---:|
| `GET /api/v1/notifications`、已读接口 | 本人 | 本人 | 本人 | 本人 |
| `GET /api/v1/appeals` | 本人 | 全部 | 关联部门 | 全部 |
| `POST /api/v1/tickets/{id}/appeals` | 本人工单 | 否 | 否 | 否 |
| `POST /api/v1/appeals/{id}/review` | 否 | 否 | 否 | 是 |
| `GET /api/v1/follow-ups`、电话记录 | 否 | 是 | 否 | 是 |

所有创建申诉、审核、完成申诉、电话回访、读取通知操作均写入 `audit_logs`，沿用请求 ID 和敏感字段脱敏机制。

## 手工测试说明

1. 执行 `alembic upgrade head`，确认版本为 `0008`；抽查升级前旧工单的编号、状态、历史不变，`handling_round=1`、`appeal_count=0`。
2. 四角色分别登录，确认都有“通知中心”和“回访与申诉”菜单；市民/部门人员访问 `/follow-ups` 应为 403，坐席审核申诉应为 403。
3. 新建工单并依次受理、要求补料、派发、处理完成；市民通知中心逐项核对标题、工单链接、未读数、单条已读和全部已读。
4. 将截止时间调整到未来 4 小时内，刷新通知中心两次；确认产生一次“即将超时”，不重复入库。
5. 处理完成后，用坐席打开回访页；确认存在第 1 轮、48 小时截止任务。先记录无人接听，任务进入继续回访；再记录已接通且满意，确认工单办结、任务完成、通知到达。
6. 新建另一张处理完成工单。市民提交不足 10 字的申诉理由应被拒绝；提交合规申诉后，同一工单再次提交应返回 `ACTIVE_APPEAL_EXISTS`。
7. 管理员审核通过，确认工单进入处理中、办理轮次加一、旧回访任务取消；部门人员完成重新办理后，确认申诉结果和第 2 轮回访任务自动生成。
8. 第 2 次申诉由管理员驳回；第 3 次提交应返回 `APPEAL_LIMIT_REACHED`，且工单状态不变。
9. 在审计页核对 `submit_appeal`、`review_appeal`、`complete_appeal`、`record_phone_follow_up`、`read_notification`。
10. Chromium、Firefox、WebKit 各跑一次阶段五 E2E；在 1280px 与 390px 宽度检查菜单、通知操作、回访卡片、申诉弹窗、焦点顺序和无横向溢出。

## 自动化命令

```bash
docker compose exec -T backend pytest -q
cd frontend && npm run lint:types && npm test && npm run build
cd frontend && E2E_PASSWORD=... npm run test:e2e
```
