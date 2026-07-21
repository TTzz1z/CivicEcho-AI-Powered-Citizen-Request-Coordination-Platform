# 第六阶段 P2：智能分派与真实平台接入

## 1. 业务规则与状态流转

### AI 边界

- AI 只生成建议，不执行受理、不予受理、派发、退回、申诉审核、处理完成或办结。
- AI 建议保存在 `ai_suggestions`，与 `tickets.status`、`tickets.version` 完全解耦。生成和评价建议不得改变工单状态或版本。
- 每条建议均返回 `advisory_only=true`、置信度、生成引擎、输入指纹和解释。相同工单内容、相同建议类型重复请求时返回同一记录。
- 工单内容变化后输入指纹变化，生成新建议；旧建议保留，作为当时的审计证据。
- 敏感、紧急事件仅提示人工核实。工作人员仍须按本单位应急预案判断和升级。
- 处理结果文书是可编辑草稿，必须核对事实、依据、处理措施和公开范围后，由工作人员在原有工单操作中提交。

### 建议类型

| 类型 | 依据 | 输出 | 可见角色 |
|---|---|---|---|
| 责任部门 | 末级分类默认部门、同分类历史办结数据、地点 | 候选部门、分数、历史样本量 | 坐席、部门、管理员 |
| 相似/重复 | 描述、地点和事件的二元字符相似度 | 相似工单、相似度、重复可能性 | 四角色，仍受工单数据范围约束 |
| 摘要 | 当前诉求正文 | 可编辑摘要 | 四角色 |
| 完整性 | 描述、地点、时间、联系方式、涉及对象 | 缺失项和补充建议 | 四角色 |
| 文书草稿 | 诉求及已有处理结果 | 带强制复核声明的答复草稿 | 坐席、部门、管理员 |
| 风险提示 | 可配置前置规则库（本批为代码内规则） | 信号、风险级别、人工处置建议 | 四角色 |

### 状态流转

AI 建议自己的生命周期只有：

`生成完成 -> 人工评价（有帮助 / 无帮助）`

评价可被更新，但不能“采纳并自动执行”。外部同步状态为 `未同步 -> synced/failed`，也不改变工单业务状态；外部平台回写在正式启用前应先采用只读比对。

## 2. 数据库迁移与旧数据兼容

Alembic `0009`：

- 新建 `ai_suggestions`：不可变输出、模型版本、输入指纹、风险、人工评价。
- 新建 `integration_events`：只保存调用元数据、请求载荷哈希、外部编号和结果，不保存访问令牌、原始人员目录或短信正文。
- `users` 增加可空的 `oidc_subject`、`directory_external_id`。
- `tickets` 增加可空的外部平台编号和同步状态。
- 所有新列均可空；迁移不为旧工单伪造 AI 建议或外部平台编号，旧状态、编号、历史、附件、回访和申诉保持不变。

升级前先备份，执行：

```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
```

应显示 `0009 (head)`。生产环境不使用 downgrade 代替恢复。

## 3. 权限、接口和审计

| API | citizen | agent | department_staff | admin |
|---|---:|---:|---:|---:|
| `POST /api/v1/ai/tickets/{id}/analyze` | 本人；不含分派/文书 | 可见工单 | 本部门工单 | 全部 |
| `GET /api/v1/ai/tickets/{id}/suggestions` | 本人、过滤内部类型 | 可见工单 | 本部门工单 | 全部 |
| `POST /api/v1/ai/suggestions/{id}/review` | 本人可见建议 | 可见工单 | 本部门工单 | 全部 |
| `GET /api/v1/ai/hotspots` | 否 | 可见范围 | 本部门范围 | 全部 |
| `GET /api/v1/integrations/status`、目录同步、指标 | 否 | 否 | 否 | 是 |
| 外部工单同步 | 否 | 可见工单 | 否 | 全部 |
| 地图、行政区划查询 | 登录用户 | 登录用户 | 登录用户 | 登录用户 |

审计动作包括 `generate_ai_suggestion`、`review_ai_suggestion`、`view_ai_hotspots`、`oidc_login`、`sync_identity_directory`、`sync_external_ticket`、`lookup_map` 和 `lookup_division`。外部调用另写 `integration_events`，凭据经过日志脱敏且不入库。

## 4. 真实平台适配约定

- OIDC：使用 Discovery、授权码换令牌和 UserInfo；只有已由人员目录预配的用户可以登录。前端回调默认为 `/auth/oidc/callback`。
- 组织人员目录：`GET DIRECTORY_API_URL`，返回 `items[]`，字段为 `external_id`、`username`、`display_name`、`role`、`department_code`、`is_active`。同步按外部编号幂等更新。
- 政务工单/ServiceNow：`POST WORK_ORDER_API_URL`，以本地工单号为业务幂等键，响应返回 `id` 或 `ticket_id`。正式切换前先在测试租户做双写核对。
- 地图和行政区划：后端代理查询，访问令牌不下发浏览器。
- 短信：`POST /api/v1/integrations/sms/send` 仅管理员可调用，只接受已审核模板编号和参数；调用元数据只保存载荷哈希，审计手机号脱敏。批量正式发送仍须接入通知任务队列、失败重试和退订机制。
- 集中日志：应用继续输出带 `request_id` 的脱敏 JSON stdout，由部署平台采集到 `CENTRAL_LOG_ENDPOINT` 对应平台；禁止应用静默吞掉采集失败。
- 监控：平台抓取健康接口与 `/api/v1/integrations/metrics`（管理员/受控采集身份），对 5xx、外部依赖失败、同步失败和 AI 风险提示积压设告警。管理员可用 `POST /api/v1/integrations/logging/probe` 和 `/monitoring/probe` 做上线前连通性验证。

所有连接器默认关闭。只有 URL、访问令牌和网络白名单均配置后才允许在测试环境开启。

## 5. 四角色前端

- 市民：“智能诉求检查”，可检查本人工单摘要、完整性、相似诉求和风险信号。
- 坐席：“智能分派”，额外显示责任部门建议、文书草稿、热点聚类和外部工单同步。
- 部门人员：“文书辅助”，在本部门数据范围内生成摘要、草稿并查看热点。
- 管理员：“智能与平台接入”，查看全部建议、热点及八类连接器配置状态，可触发人员目录同步。

所有页面固定展示人机协同边界，不提供“一键采纳并办结”按钮。

## 6. 手工测试说明

1. 备份后升级到 `0009`，抽查旧工单的编号、状态、版本、历史、附件、协同任务、回访和申诉未变化；新字段为空。
2. 四角色分别登录，确认都能看到自己的 AI 菜单；跨角色 URL 仍返回无权访问。
3. 市民输入本人工单，生成摘要、完整性、相似和风险建议；请求 `assignment` 应返回 403。
4. 坐席分析一张包含“燃气泄漏、有人受伤”的工单，确认显示紧急提示；刷新前后工单状态与版本不变。
5. 同一内容重复分析，确认建议 ID 不变；修改工单内容后再次分析，确认产生新的输入版本建议。
6. 将建议评价为有帮助/无帮助，在审计页核对生成和评价记录、请求 ID，确认没有工单状态历史。
7. 创建至少两张同分类、相近地点工单，坐席/部门/管理员查看热点；市民访问热点接口应为 403。
8. 未配置连接器时，管理员页面显示“待配置”；触发目录或工单同步应明确返回 409，不得伪造成功。
9. 在测试身份平台完成 OIDC 登录；未同步账号应被拒绝，停用账号也应被拒绝，成功登录应有审计记录。
10. 使用测试租户逐一验证目录同步、外部工单幂等同步、地图/区划代理；检查 `integration_events` 不含令牌和原始敏感载荷。
11. 在 Chromium、Firefox、WebKit 运行 E2E，并在 1280px、390px 检查建议卡片、热点、连接器状态、键盘焦点与无横向溢出。

## 7. 自动化验证

```bash
docker compose up -d --build backend frontend
docker compose exec -T backend pytest -q
cd frontend && npm run lint:types && npm test && npm run build
cd frontend && E2E_PASSWORD=... npm run test:e2e
```
