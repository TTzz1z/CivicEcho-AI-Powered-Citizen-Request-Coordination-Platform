# 第二轮测试报告

测试日期：2026-07-13。运行环境：Docker Compose、Rasa 3.0.13、Rasa SDK 3.0.7、Python 3.8、Duckling 0.2.0.2。最终模型：`models/tingting-round2-final.tar.gz`。

## 最终结果

| 检查 | 命令/方式 | 结果 |
|---|---|---|
| 数据校验 | `docker compose run --rm rasa data validate` | 退出码 0，无 Story 冲突；保留 legacy handoff/未显式引用模板警告 |
| 模型训练 | `docker compose run --rm rasa train --fixed-model-name tingting-round2-final` | 成功；全量训练约 426 秒，locale 修正后缓存重打包约 23 秒 |
| 独立 NLU | `rasa test nlu --nlu tests/test_nlu.yml ...` | 意图 30/31，accuracy 0.9677 |
| Core/Story | `rasa test core --stories tests/test_conversations.yml ... --fail-on-prediction-errors` | 24/24 对话、113/113 动作，accuracy 1.0 |
| Action 单测 | `python -m unittest discover -s tests -p test_public_request_actions.py -v`（Rasa 容器） | 14/14 通过 |
| REST 闭环 | `/webhooks/rest/webhook` | 投诉和咨询创建/查询通过；缺地点、修改、取消、无编号、不存在编号通过 |
| Duckling | 直接 `/parse` 与 Rasa `/model/parse` | `zh_CN` 下复杂中文时间解析成功，时区为 `+08:00` |

NLU 明细：投诉 5/6、建议 6/6、咨询 6/6、求助 6/6；唯一错例把“昨晚施工到凌晨，孩子没法睡觉”从投诉判成求助。DIET 实体：地点 5/10、工单号 2/2、DIET 时间 0/2；实际 Duckling 可解析“下周一下午三点”等时间，但不计入该 DIET 报告。

生成报告位于：

- `results/round2-final-nlu/intent_report.json`
- `results/round2-final-nlu/DIETClassifier_report.json`
- `results/round2-final-core/story_report.json`

## 覆盖范围

- 四类诉求创建路径。
- 缺少地点追问和已有地点不重复追问。
- 咨询地点“不适用”、时间非必填。
- 摘要确认、否认后修正、显式取消。
- 创建后按最近编号查询、显式编号查询、无编号追问、不存在编号。
- 工单编号生成、创建、过滤查询、状态更新、默认状态确定性。
- 必填缺失、可选空值、槽位清理和最近工单保留。
- 创建/查询异常的中文降级提示。
- 原 12 条英文 Helpdesk 对话回归继续包含在 24 条 Core 测试中。

## 实际发现并修复的问题

1. `WhitespaceTokenizer` 不支持 Rasa 3.0.13 的 `zh`，改用镜像已验证的 `JiebaTokenizer`。
2. Duckling 的 `zh` locale 返回空，固定为 `zh_CN` 和 `Asia/Shanghai`。
3. 条件槽位在终止 Action 中切换会触发 Core fallback 并回滚槽位，终止 Action 现显式调度 `action_listen`。
4. Duckling 区间值直接展示会输出字典，现保留匹配到的原始中文时间用于摘要。

## 迭代中的非最终结果

- 第一次训练因 `WhitespaceTokenizer` 不支持 `language: zh` 失败，未生成可用模型；改为已安装的 `JiebaTokenizer` 后成功。
- 第一版独立 NLU 为 27/31（87.1%），地点实体 1/10；修正实体边界、补充边界样本并调整 DIET 后得到最终结果。
- Core 第一次严格测试在 6/23 停止，因为测试把 Form 内部发送的 `utter_ask_location` 错写成独立策略动作；修正测试表达后通过。随后补入“创建后同会话查询”，最终为 24/24。
- 第一轮 REST 烟测发现终止 Action 后 fallback 回滚槽位；修正显式 `action_listen` 后重新执行，创建、修改、取消和查询均通过。
- 一次并行运行测试和重建依赖容器导致 Compose 容器名竞争；该编排命令失败后已按顺序重跑，NLU/Core 最终命令均退出 0。

## 已知限制与下一步

- 地点实体泛化仍有限，遇到未识别地点会退回表单追问；少量数字/地点可能被 DIET 误标。
- 独立 NLU 测试仅 31 条，不能代表生产准确率；应扩大盲测集，重点补投诉/求助边界和实体一致性。
- Mock 工单只存在单个 Action Server 进程内，重启即丢失，不支持多副本一致性或审计。
- 下一轮最合理的方向是先扩充脱敏中文盲测与错误分析，并定义 `TicketRepository` 契约/幂等语义；在此基础上再单独评估正式持久化，不应同时升级 Rasa 或开发前端。
