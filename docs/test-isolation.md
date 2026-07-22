# 测试数据库隔离策略

**背景**：倾听助手在 R4 之前曾因 pytest / Playwright 直接向演示数据库写入测试数据，导致演示环境被严重污染（57+ 测试工单、32+ 测试账号、20+ 测试部门）。R4 通过白名单 demo_reset 实现了"可确定清理",R5 在此之上补充隔离策略。

## 一、当前方案

倾听助手采用 **"单库 + 确定性清理"** 方案，而不是多库隔离：

| 测试类型 | 数据库 | 清理方式 |
|---|---|---|
| 后端 pytest(`backend/tests/`) | 演示库 `tingting` | 测试通过 UUID 后缀创建账号/部门/工单；**demo_reset 白名单方式统一清除** |
| 前端 vitest(`frontend/src/**/*.test.tsx`) | 不触库（jsdom + mock API) | 无需清理 |
| Playwright E2E(`frontend/e2e/`) | 演示库 `tingting` | globalTeardown 调用 demo_reset 重置 |
| Rasa unittest(`actions/tests/`) | 不触演示库（独立 SQLite) | 无需清理 |
| demo_reset 手工调用 | 演示库 `tingting` | 白名单重置 |

## 二、为什么不引入独立测试库

- **复杂度**：单仓单 docker-compose 维护一份数据库已足够；多库需要额外的 init 脚本、迁移同步、CI 配置。
- **演示可信**：演示前必须 demo_reset，测试也必须 demo_reset,**两条路径共用同一个白名单清理逻辑**，避免双套维护。
- **成本可控**：在求职作品规模下，"确定性清理"已经能保证演示前状态一致。

## 三、demo_reset 确定性保证

`backend/scripts/demo_reset.py` 使用**白名单方式**:

- 只保留 4 个账号：`citizen_local`、`agent_local`、`department_local`、`admin_local`
- 只保留 7 个部门：`urban-management`、`transport`、`housing-property`、`education`、`health`、`community-civil`、`general-intake`
- 只保留演示分类白名单（城市管理市政树）：`CSGL` 及下级 `CSGL-GGSS` / `CSGL-GS` / `CSGL-HW` / `CSGL-YL` 与对应末级（含路灯、道路、水电、环卫、绿化等，见 `DEMO_CATEGORY_CODES`）
- 清空所有事务表（tickets、work_orders、notifications、appeals、follow_ups、ai_usage、audit、outbox、integration_events)
- 清空测试 KB 文档（`P0-KB-*`、`P0-D-*` 等）
- 通过 `app.seed.seed()` 重新插入演示种子

**确定性验证**：连跑两次，最终统计完全一致：

```
departments: 7, categories: 15, users: 4, tickets: 1, kb_documents: 14, kb_chunks: 27
```

## 四、Playwright 自动清理

`frontend/e2e/global-teardown.ts` 在全部 E2E 结束后自动调用 demo_reset，避免测试残留：

```typescript
// global-teardown.ts(摘要)
// 1. 登录 admin
// 2. 通过 docker exec 调用 backend 的 demo_reset
// 3. 等待完成
```

如果 E2E 因失败中断，下一次 demo 前**仍需手动跑 demo_reset**。

## 五、日常使用建议

| 场景 | 命令 |
|---|---|
| 写完 pytest 想立刻演示 | `docker compose exec -T -e SEED_PASSWORD=... backend python -m scripts.demo_reset` |
| CI 跑完 E2E 退出前 | 自动（globalTeardown) |
| 不确定演示库是否干净 | 直接跑 demo_reset |
| 演示前 5 分钟 | 必须跑 demo_reset，并验证 `users=4, departments=7, tickets=1` |

## 六、何时考虑多库隔离

仅当项目进入多人协作或 CI 必须并行跑测试时，才考虑引入独立 `tingting_test` 库。当前规模下不必要。

---

**相关文件**:
- `backend/scripts/demo_reset.py`
- `frontend/e2e/global-setup.ts` / `global-teardown.ts`
- `backend/tests/conftest.py`
