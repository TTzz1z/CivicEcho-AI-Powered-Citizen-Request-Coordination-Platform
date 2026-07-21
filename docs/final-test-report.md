# 最终测试报告（v1.0.0 Credibility Closeout）

测试日期：2026-07-22（Asia/Shanghai）  
版本：CivicEcho / 倾听助手 **v1.0.0** 可信度收口  
说明：本文件为当前 main 发布门禁记录。`docs/archive/` 内历史报告不代表当前 main。

## 范围

- A1–A9：MinIO 内网 HTTP、KB 发布原子性 + FOR UPDATE、Embedding 代际隔离、advice_id 证据链、KB 恶意扫描、工单/WorkOrder 单事务、删除 `/resolve`、Rasa 伪成功 harden、匿名绑定反馈
- Soft：citations UI、chat 隐私/多标签、demo_reset 护栏+MinIO 清理、ClamAV 严格解析、WorkOrder 409
- CI：`production-compose` + `e2e-full`（workflow_dispatch / tag）

## 本地门禁（以执行输出为准）

| 门禁 | 命令 | 期望 |
|---|---|---|
| 后端 pytest | `cd backend; pytest -q` 或 compose exec | 含 `test_v1_credibility_closeout` 全绿 |
| 前端 vitest | `cd frontend; npm test` | citations / bind / WorkOrder 409 / chatStorage 全绿 |
| tsc / build | `npm run lint:types` / `npm run build` | 0 errors |
| Alembic | `alembic upgrade head && alembic check` | head=`0023`，无漂移 |
| 生产 Compose | `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait` | healthy；EICAR → infected |
| E2E | `sh scripts/run-e2e.sh smoke` 日常；`full` 打 tag 前 | smoke 绿；full 绿后方可 tag |

## 发布步骤

1. Push main → Actions 全绿（含 `production-compose`）
2. workflow_dispatch 触发 `e2e-full`
3. [RELEASE_NOTES_v1.0.0.md](./RELEASE_NOTES_v1.0.0.md) → tag `v1.0.0` → 之后仅修 Bug
