# 工单流转

> **【部分过期】** 正式状态机以 **[PRODUCT.md](../../PRODUCT.md)**、`ticket_service.py`、`work_order_service.py` 为准：部门 submit/summary → `awaiting_review`（主单仍 `processing`）；坐席 `review-resolve` → `resolved`；市民满意/管理员代办结 → `closed`；不满意保持 `resolved`；申诉批准后才回 `processing`。

## 状态机

```text
pending ──accept──> accepted ──assign──> assigned ──process──> processing
   └──reject──> rejected                                  └──resolve──> resolved
                                                                    ├──citizen feedback(satisfied)──> closed
                                                                    ├──citizen feedback(dissatisfied)──> processing
                                                                    ├──admin close with reason──> closed
                                                                    └──admin/department process──> processing
```

中文展示依次为待受理、已受理、已派发、处理中、待市民确认、已办结、不予受理。数据库和 API 使用代码，Action 使用 `status_label` 和状态专属说明。

每次操作必须带非空 remark 和当前 version。Service 先检查版本、角色、部门和状态边，再执行原子 `version + 1`；旧版本返回 `VERSION_CONFLICT`，非法边返回 `INVALID_STATUS_TRANSITION`。

派发只能选择启用部门，且由 agent/admin 人工执行。系统没有自动派单。accepted_at、resolved_at、closed_at 在对应转换时写入；resolved 退回 processing 会清空 resolved_at。

部门提交解决结果时必须填写结果摘要、处理措施、解决情况和对市民公开答复，内部备注可选且只向工作人员返回。市民在 resolved 状态可提交满意、基本满意或不满意评价：前两者直接办结，不满意必须说明原因并原子退回 processing。每一轮评价以解决版本号唯一记录在 `ticket_feedbacks`，不会覆盖之前的反馈。管理员可以代办结，但必须填写对市民公开的代办结依据。

不予受理必须选择标准原因码，并填写对市民的详细说明；可补充建议办理渠道和是否需要补充材料。内部历史内容由 `visibility` 控制，市民只能收到安全的状态说明和公开答复。

业务处理记录保存在 `ticket_status_history`，市民评价保存在 `ticket_feedbacks`；登录、敏感查看、创建、受理、派发、状态变化、评价、联系方式修改和权限拒绝保存在独立 `audit_logs`。
