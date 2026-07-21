# 第六轮测试报告

测试日期：2026-07-14（Asia/Shanghai）

## 结果摘要

| 门禁 | 结果 |
|---|---|
| Python compile/ruff | 通过 |
| Backend pytest | 18/18 通过 |
| Actions unittest | 21/21 通过 |
| Rasa data validate | 通过，保留历史未使用项警告 |
| Rasa Core | stories 24/24，actions 113/113，accuracy 1.0 |
| TypeScript | 通过 |
| Vitest | 8/8 通过 |
| Vite production build | 通过，无大包警告 |
| Playwright Chromium | 17/17 通过 |
| Playwright Firefox | 17/17 通过 |
| Playwright WebKit | 17/17 通过 |
| Docker Compose config | 通过 |
| Alembic | 0003 (head) |
| 六服务健康 | 全部 healthy |

## 独立 E2E

`scripts/run-e2e.ps1` 创建 `tingting-e2e` Compose 项目与独立 `tingting_e2e` 数据库/Volume，自动迁移、导入 7 部门和 4 账号、执行 51 项测试并在 finally 中删除容器、网络和 Volume。第一次并发运行暴露 Rasa sender 跨浏览器串扰（48/51）；配置单 worker 后，全新数据库重跑 51/51 通过。

## 分包

路由页面使用 React.lazy。ECharts 仅看板动态加载且只注册 Pie/Bar/Grid/Legend/Tooltip/Canvas。最终最大 chunk：`charts-vendor` 539.64 kB（gzip 184.66 kB），通用 `index` 519.42 kB（gzip 173.77 kB），React 231.55 kB，Table 175.96 kB；Vite 未报告超限 warning。

## 安全与恢复

前端 npm 审计 0；Python 扫描发现 Starlette 0.41.3 的 8 条公告，未自动升级。生产弱密钥检查、CORS、限流、JWT 声明、请求体/超时、安全头和日志脱敏已加入。

备份恢复在独立环境实测：建单并受理、备份、删除 schema 并确认业务表不存在、恢复、检查迁移与数据完整性全部通过。恢复后工单 1、用户 4、部门 7、处理记录 2、审计日志 4。

request_id 以 `round6rasa9012` 实测：Rasa tracker metadata 保留该值，Action 调用日志命中，Backend 审计表关联工单记录命中 1 条。PostgreSQL 断连时 liveness=200、readiness=503，恢复后六服务回到 healthy。

## 已知限制

- Rasa 3.0.13 与旧模型保留依赖/弃用警告。
- Starlette 公告需在单独兼容性升级轮次处理。
- E2E 单 worker 是保证共享 Rasa tracker 隔离的有意选择。
