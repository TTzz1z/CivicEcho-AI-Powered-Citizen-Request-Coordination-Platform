# 中文政务诉求领域设计

本轮在原英文 Helpdesk 领域旁增量加入中文政务诉求，不删除原意图、表单、ServiceNow 适配器和 handoff 参考代码。当前中文能力是 Rasa 3.6.20 上重新训练的 DIET 领域基线，不是 BERT、RAG 或自研语义融合模型。

## 四类核心意图

| 意图 | 业务边界 | 示例 |
|---|---|---|
| `submit_complaint` | 已发生的问题、管理不到位或服务不满 | 小区垃圾三天没人清理 |
| `submit_suggestion` | 改善方案、建设意见或公共服务建议 | 希望这里增加公交站 |
| `policy_consultation` | 询问政策、条件、流程、材料或办理方式 | 居住证需要什么材料 |
| `request_help` | 因现实困难请求帮助或协调 | 老人行动不便，请帮忙上门办理 |

训练数据位于 `data/nlu_zh.yml`。四类分别有 40、40、38、38 条样本，包含口语、长短句和无显式类别关键词表达。独立测试数据位于 `tests/test_nlu.yml`，不与训练句完全重复。

辅助意图包括 `query_request_status`、`provide_information`、`cancel_request`、`affirm`、`deny`、`greet`、`goodbye` 和 `out_of_scope`。模糊诉求由统一表单继续询问类型；明确不相关输入进入 fallback/out-of-scope。

## 实体与槽位

| 名称 | 含义 | 是否建单必填 |
|---|---|---|
| `request_type` | 投诉、建议、咨询、求助 | 是 |
| `description` | 用户首句完整原文或修正后的完整描述 | 是 |
| `location` | 发生地点；无地点的咨询可填“不适用” | 是 |
| `event` | 核心事件 | 否 |
| `time` | 发生或持续时间 | 否 |
| `target` | 单位、人员、设施或对象 | 否 |
| `contact` | 联系方式 | 否 |
| `ticket_id` | 查询用工单编号 | 查询时使用 |

`last_ticket_id` 保存本会话最近创建的编号；三个布尔槽位只控制确认、修正和查询编号等待状态。联系方式拒绝提供不会阻止创建。

## NLU 配置

- `JiebaTokenizer`：Rasa 3.6.20 使用该中文分词器；镜像已验证可完成训练和回归。
- `RegexFeaturizer`、词级和字符级 `CountVectorsFeaturizer`、`DIETClassifier`：负责中文意图和开放实体基线。
- `DucklingEntityExtractor`：固定 `locale: zh_CN`、`timezone: Asia/Shanghai`，仅处理 email/time；不承担地点、对象等全部实体。
- `EntitySynonymMapper`、`RulePolicy`、`TEDPolicy` 和 legacy `AugmentedMemoizationPolicy` 保留。

独立测试中四类意图共 23/24 正确；DIET 地点实体为 5/10，工单编号为 2/2。Duckling 复杂时间已通过实际 `/model/parse` 验证，但 Rasa 3.0 的离线 DIET 实体报告不会合并统计 Duckling 结果。
