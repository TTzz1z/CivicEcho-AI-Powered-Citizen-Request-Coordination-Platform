# 第四轮测试报告

测试时间：2026-07-13，Asia/Shanghai。环境：Windows、Docker Desktop、PostgreSQL 16、Backend Python 3.11、Rasa 3.0.13 / SDK 3.0.7。

## 结论

企业工单流转的本地验收链路通过：认证/授权、四角色边界、严格状态机、部门派发、处理与审计记录、时间标准化、乐观锁、旧库迁移和五服务中文集成均完成。GitHub workflow 已重建但尚未在远端 runner 触发。

## 真实结果

| 范围 | 结果 |
|---|---|
| 静态检查 | compileall + ruff 严重错误规则通过 |
| Backend/PostgreSQL | 17 passed；认证、授权、管理员管理、流程、部门、时间、幂等与并发 |
| Actions | 17 + 3 = 20 passed |
| Rasa 数据校验 | 退出码 0；仅保留 legacy unused 警告 |
| Rasa Core | 24/24 stories、113/113 actions、100% |
| migration | 0001→0002；87→87 条旧工单，7 个部门 |
| Docker 集成 | 中文建单→受理→派发→处理→解决→聊天查询→办结，通过 |
| 五服务 | rasa/action_server/duckling/backend/postgres 均 healthy |

第一次实际迁移前抽样状态为“受理中/待受理”，升级后为 `accepted/pending`，原编号不变。迁移在已有 named volume 上执行，没有删除 volume。

Docker 手工验收工单 `QT2026071300000163` 完成至 closed；补齐管理员管理 API、全部最终代码和固定依赖重建后，可重复脚本创建 `QT2026071300000332` 并再次通过至 closed。聊天查询返回同一编号，证明走 Rasa → Action → 认证 Backend，而非内存 Mock。

## 覆盖点

- 登录成功、错误密码、不存在/禁用用户、无效/过期 Token、`/auth/me`。
- citizen 他人工单 403、跨部门 staff 403、agent 受理派发、staff 本部门处理、admin 办结。
- 完整流转、非法跳转、拒绝、resolved 退回 processing、旧 version 409、历史备注完整。
- 停用部门拒绝派发；分页、状态筛选与角色查询范围。
- 昨天晚上、三天前、上周一、最近一个月、不可解析、跨年时区边界。
- 旧幂等/并发创建与 PostgreSQL 持久化回归继续通过。

## 已知限制

- 远端 GitHub Actions 未触发；这里只报告本地等价命令和 Docker 结果。
- 旧匿名工单没有 conversation 摘要，迁移后保留服务身份按编号的脱敏查询兼容性。
- 没有 React、动态 RBAC、AI 自动派发、真实政务平台、短信或第三方登录。
- 中文时间规则是保守子集，无法确定的表达有意不标准化。
