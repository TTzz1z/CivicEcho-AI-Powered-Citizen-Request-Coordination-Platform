# 倾听助手 Release Notes — v1.0.0 基线说明

> 工作区收口基线：相对 Commit `438047c776787da6c5b412c403c7799ba52364c8` 的 v1.0.0 冻结改动；Alembic head **`0025`**。
> 本地门禁（2026-07-22 重测）：backend pytest **162 passed / 0 failed**；frontend Vitest **49 passed**；Chromium Smoke **6 passed**；Alembic **0025**；Rasa `data validate` + Action Server **21** unittest 通过。
> tag `v1.0.0` 仅在该 SHA 的远程默认 CI 全绿后打出；E2E Full **非**门禁；ClamAV / prod 健康本机 **未验证**。

## 产品形态

- 市民诉求受理 + 跨部门协同办理的**演示/工程化 MVP**（Docker Compose）。
- 四角色：citizen / agent / department_staff / admin。
- AI（`triage_assistant` / `handling_assistant`）**advisory only**：采纳只记决策，不自动派发/填结果/办结。
- 外部 OIDC / 短信 / 地图 / 政务工单平台等为可配置适配器，默认 disabled，不伪造成功。

## 业务状态机（正式路径）

```text
pending → accepted → assigned → processing
  →（部门 WO submit + summary → collaboration_status=awaiting_review，主单仍 processing）
  → 坐席 review-resolve → resolved
  → 市民满意 feedback 或管理员 close → closed

不满意 feedback → 保持 resolved
申诉 submitted →（管理员批准）→ processing 重办
```

已删除遗留「部门直接 `/resolve` 办结主单」路径；正式办结入口为 `review-resolve`。

## Highlights（相对早期基线）

| 主题 | 说明 |
|---|---|
| 职责分离 | 部门提交待审；坐席复核办结；市民/管理员闭环关闭 |
| AI 角色拆分 | `0024`：`triage_assistant` vs `handling_assistant`；Schema/Prompt/权限分离 |
| 市政分类 | `0025`：城市管理等叶子分类幂等扩展，便于演示归口 |
| KB | staging 索引成功再发布；Embedding 代际隔离；可见性过滤 |
| 对象存储 | 生产内网 MinIO HTTP；对外 TLS 由网关；ClamAV 严格解析 |
| 安全 | `/metrics` 需监控令牌或 admin JWT（backend 匿名 → 401）；backend 绑 loopback；生产弱密钥 fail-fast |
| CI | 默认门禁 = 单元/集成/构建 + Playwright **Smoke** + production-compose；**不是**全量 E2E |

## Migrations

- Alembic head：**`0025`**（含 advice 审核、`0024` 分诊/办件类型、`0025` 市政分类）。

## CI / Release gates

| Gate | 何时 |
|---|---|
| static / frontend / backend / action / rasa / e2e-smoke / dependency-security | PR 与 push |
| docker-integration | main push |
| production-compose | main push / tag / workflow_dispatch |
| e2e-full | 仅手动勾选；**非**默认门禁 |

打 tag 前请确认该 SHA 的 Actions 默认 jobs 全部成功。

## 本轮本地验证摘要（2026-07-22）

| 项 | 结果 |
|---|---|
| backend `pytest -q` | 162 passed / 0 failed |
| frontend vitest / lint:types / build | 49 passed；types OK；build OK |
| Chromium Smoke | 6 passed |
| Alembic | head=`0025`；check OK |
| Rasa data validate | exit 0 |
| Action Server unittest | 21 passed |
| 开发 Compose 8 服务 | healthy；live/ready 200 |
| MinIO | put/open/delete OK |
| `demo_reset` ×2 | 终态一致（7/15/4/1） |
| pip-audit / npm audit | 无已知漏洞（npm 用 registry.npmjs.org） |
| 生产 Compose | 仅 `config -q`；健康 **未验证** |
| ClamAV | **未验证** |

人工主流程：`acceptance_main_flow.py` 19 PASS；另抽查 citations、triage analyze、403、409、AI review 不改状态。

## 明确非目标 / 已知限制

- 不宣称微服务、K8s、高并发压测达标、等保合规、真实政府生产上线。
- 无业务 SSE 推送；AI 成本为估算字段。
- 不训练/微调模型；不自动行政决策。
- 匿名绑定非跨设备找回；`ticket_advice` 为兼容审核路径。
- E2E Full 非门禁；ClamAV / prod 健康本机未验证。

## 文档入口

- [README.md](../README.md) · [PRODUCT.md](../PRODUCT.md) · [ENGINEERING.md](../ENGINEERING.md)
- [DEMO.md](./DEMO.md) · [TESTING.md](./TESTING.md) · [DEPLOYMENT.md](./DEPLOYMENT.md) · [database-design.md](./database-design.md)
