# 第三轮测试报告

测试时间：2026-07-13（Asia/Shanghai）  
环境：Windows + Docker Desktop；Rasa 3.0.13、Rasa SDK 3.0.7、PostgreSQL 16、Python 3.11 backend。

## 结论

第三轮验收链路通过：中文输入经 Rasa、Action Server、FastAPI 写入 PostgreSQL，Action 与 PostgreSQL 重启后仍可查询；幂等和并发测试通过；原中文/legacy Core 回归保持全绿。NLU 意图盲测从 94.17% 提升到 97.50%，Regex/Lookup 地点 F1 为 74.03%。所有数值来自本轮实际命令输出。

## 测试汇总

| 范围 | 结果 |
|---|---|
| Rasa 数据校验 | 退出码 0；仅保留原 legacy 未使用 intent/utterance 警告 |
| 盲测防泄漏 | blind 120、training 708、exact overlap 0 |
| NLU 优化前 | 113/120，Accuracy 94.17%，Macro F1 94.12% |
| NLU 优化后 | 117/120，Accuracy 97.50%，Macro F1 97.50% |
| 地点优化前 DIET | P 62.96%、R 27.87%、F1 38.64% |
| 地点优化后 Regex/Lookup | P 61.29%、R 93.44%、F1 74.03% |
| Core 回归 | 24/24 stories，113/113 actions，100% |
| Backend 内存/API | 5/5 passed |
| PostgreSQL Repository | 2/2 passed |
| Actions + HTTP gateway | 20/20 passed |
| Docker 健康状态 | rasa/action_server/duckling/backend/postgres 均 healthy |
| 完整中文集成链路 | 通过 |
| Action 重启持久化 | 通过 |
| PostgreSQL 重启/volume 持久化 | 通过 |

## Backend 与数据库

实际迁移版本为 `0001`。通过 `psql \d tickets` 确认 `ticket_id` 和 `idempotency_key` 均为唯一约束，`ticket_status_history.ticket_id` 外键指向 `tickets.ticket_id`。健康检查执行 `SELECT 1`，不仅检查 Web 进程。

覆盖测试：创建、详情、最近工单、状态更新、两条状态历史、不存在工单、Pydantic 参数校验、统一错误 envelope、重复幂等请求、内存 Repository、PostgreSQL Repository。

首次 Backend 单测为 4/5：Pydantic 校验错误上下文中的 `ValueError` 不能直接 JSON 序列化。改用 FastAPI `jsonable_encoder` 后复测 5/5。该问题未隐藏或从报告中删除。

## 幂等与并发

- 内存测试：40 个并发不同请求产生 40 个唯一工单号。
- PostgreSQL 实测：40 个并发不同请求产生 40 个唯一工单号。
- PostgreSQL 实测：10 个并发相同幂等键最终只有 1 个工单号。
- 手工 API 重放：同一幂等键第一次返回 `idempotent_replay=false`，第二次为 `true`，工单号同为 `QT2026071300000052`。

编号由 PostgreSQL `ticket_number_seq` 提供，不使用 Action/Backend 进程内计数器保证生产唯一性；序列空号是允许的。

## Action 异常路径

20 个 Action/网关测试覆盖：

- FastAPI 正常成功响应；
- 连接失败；
- 读取超时；
- 业务校验错误；
- 404 不存在工单；
- 非法/异常服务响应；
- 同一幂等键重复提交不重复建单；
- 地点前缀归一化和机构泛称拒绝；
- 原内存 Mock 的创建、查询、状态与清理。

后端失败时 Action 明确提示“尚未创建”，没有返回伪造编号。

## Docker 集成与持久化

最终 Compose 五个服务均为 healthy，服务间使用 `backend`、`postgres`、`action_server`、`duckling` 服务名；PostgreSQL 使用 `tingting-assistant_postgres_data` named volume。

真实链路：

1. REST 输入“幸福路的垃圾三天没人清理，我要投诉”。
2. Rasa 返回摘要：投诉、完整描述、幸福路、三天、垃圾。
3. 输入“确认”。
4. Action 异步调用 FastAPI，PostgreSQL 创建 `QT2026071300000055`，状态“待受理”。
5. 重启 Action Server。
6. 新对话输入“查询工单QT2026071300000055”。
7. Rasa → Action → FastAPI 返回同一工单“投诉 / 待受理”。

另用 `QT2026071300000054` 验证同时重启 PostgreSQL 与 Action Server 后，API 详情及初始状态历史仍存在。这证明数据来自持久化 volume，而不是 Action 内存。

## 产物

- 优化前：`results/round3-nlu-before/`
- 优化后：`results/round3-nlu-after/`
- Core：`results/round3-core/`
- 模型：`models/tingting-round3.tar.gz`

## 已知限制

- 120 条盲测不足以代表真实城市和方言分布。
- Regex 地点高召回但仍有机构泛称误报；Action 已做保守拒绝，歧义地点仍追问。
- DIET 地点自身 F1 没有提升，主要收益来自 Regex/Lookup。
- `occurred_at` 仍是用户原始文本，没有标准化时间字段。
- 无认证、权限、真实政务系统对接和自动派单；状态更新接口仅用于当前受控环境。
- Rasa legacy unused-intent/unused-utterance 校验警告仍存在，为保护原资产未删除。

