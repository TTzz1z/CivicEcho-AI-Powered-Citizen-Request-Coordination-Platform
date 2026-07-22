# 最终测试报告（v1.0.0 Credibility Closeout）

> **【已收敛】** 现行测试命令、门禁与「未验证」约定请以 **[TESTING.md](../TESTING.md)** 为准。本文为历史收口稿；其中部分 Alembic head 表述可能过期（当前 `0025`）。本轮文档整理**未重跑**下列命令。

测试日期：2026-07-22（Asia/Shanghai）  
版本：CivicEcho / 倾听助手 **v1.0.0** 可信度收口  
说明：本文件为当前 main 发布门禁记录。`docs/archive/` 内历史报告不代表当前 main。

## 范围

- A1–A9：MinIO 内网 HTTP、KB 发布原子性 + FOR UPDATE、Embedding 代际隔离、advice_id 证据链、KB 恶意扫描、工单/WorkOrder 单事务、删除 `/resolve`、Rasa 伪成功 harden、匿名绑定反馈
- Soft：citations UI、chat 隐私/多标签、demo_reset 护栏+MinIO 清理、ClamAV 严格解析、WorkOrder 409
- CI：默认门禁为 `e2e-smoke` + unit/backend/`production-compose`；`e2e-full` 仅 workflow_dispatch 可选

## 本地门禁（以执行输出为准）

| 门禁 | 命令 | 期望 |
|---|---|---|
| 后端 pytest | `cd backend; pytest -q` 或 compose exec | 含 `test_v1_credibility_closeout` 全绿 |
| 前端 vitest | `cd frontend; npm test` | citations / bind / WorkOrder 409 / chatStorage 全绿 |
| tsc / build | `npm run lint:types` / `npm run build` | 0 errors |
| Alembic | `alembic upgrade head && alembic check` | 当时稿为 head=`0023`；现行 head 见 `docs/TESTING.md`（写作时 `0025`） |
| 生产 Compose | `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait` | healthy；EICAR → infected |
| E2E | `sh scripts/run-e2e.sh smoke` | smoke 绿即可作为默认 e2e 信号；`full` 可选 |

## 发布步骤

1. Push main → Actions 默认 jobs 全绿（含 `e2e-smoke`、`production-compose`）
2. [RELEASE_NOTES_v1.0.0.md](../RELEASE_NOTES_v1.0.0.md) → tag `v1.0.0` → 之后仅修 Bug
3. （可选）workflow_dispatch 勾选 `run_e2e_full` 做三浏览器回归，失败不回滚 tag 门禁定义
