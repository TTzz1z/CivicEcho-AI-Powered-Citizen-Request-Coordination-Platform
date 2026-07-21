# CivicEcho / 倾听助手 v1.0.0 Release Notes

发布主题：**可信度收口（Credibility Closeout）**  
状态：代码与文档已收口；**仅在** GitHub Actions `main` 全绿（含 `production-compose`）且手动 `e2e-full` 通过后打 tag `v1.0.0`。

## Highlights

- 生产内网 MinIO 使用 HTTP（`OBJECT_STORAGE_SECURE=false`）；对外 TLS 由 Caddy 终止。
- KB 发版：先 staging 索引成功再 `PUBLISHED`，失败不撤回旧版；`FOR UPDATE` + `INDEX_IN_PROGRESS` 409。
- Embedding 代际隔离：hash/fallback 向量不进入 pgvector 检索路径。
- AI 工单建议审核强制 `advice_id` 证据链（一票一 advice，审核快照入 audit）。
- KB / 附件上传：ClamAV `stream: OK|FOUND` 严格解析；扫描通过后才写入 MinIO。
- 工单 assign/process 与 WorkOrder 同事务；失败整单回滚。
- 删除遗留 `POST /tickets/{id}/resolve`；正式办结仅 `review-resolve`。
- Rasa / 前端兜底文案 harden；匿名绑定三态反馈；citations / chat 隐私多标签清理。

## Migrations

- Alembic head：**`0023_ai_ticket_advice_review`**

## CI / Release gates

| Gate | When |
|---|---|
| unit / e2e-smoke / docker-integration | every `main` push |
| `production-compose`（PG + MinIO + ClamAV mock + backend/worker） | every `main` push |
| `e2e-full`（三浏览器） | `workflow_dispatch` 或 tag |

## Known CI note

`production-compose` 在 GitHub Actions 使用 `Dockerfile.clamav-mock`（协议兼容 mock），避免官方 ClamAV 镜像签名 CDN 拉取失败。真实部署仍应使用 `clamav/clamav:stable`（见 `docker-compose.prod.yml`）。

## After v1.0.0

仅修 Bug；不做 K8s / Kafka / 微服务拆分 / 小程序 / 大屏等范围外工作。
