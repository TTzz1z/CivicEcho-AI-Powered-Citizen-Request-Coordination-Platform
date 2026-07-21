# 第三阶段：附件与办理证据（P0/P1）

## 已实现范围

- 市民可上传公开的 `citizen_material`、`other` 附件。
- 承办部门可上传 `site_photo`、`official_document`、`processing_proof`、`other`，并选择 `public` 或 `internal`。
- 管理员可管理全部附件；坐席仍受原工单可见范围约束。
- PostgreSQL 的 `ticket_attachments` 只保存元数据、SHA-256、扫描结果和对象键，不保存文件大字段。
- 文件正文保存到 S3 兼容对象存储。本地 Compose 使用 MinIO，适配层位于 `app/storage.py`，后续可替换政务云实现。
- 下载不返回预签名直链，必须经过后端工单权限和附件可见范围校验。
- 删除采用软删除元数据，随后删除对象；每次上传、下载、拒绝、删除和权限拒绝均写审计日志。

## API

### 上传

`POST /api/v1/tickets/{ticket_id}/attachments`

请求为 `multipart/form-data`：

- `file`：文件正文。
- `attachment_type`：`citizen_material | site_photo | official_document | processing_proof | other`。
- `visibility`：`public | internal`，默认 `public`。

### 查询、下载与删除

- `GET /api/v1/tickets/{ticket_id}/attachments`
- `GET /api/v1/attachments/{attachment_id}/download`
- `DELETE /api/v1/attachments/{attachment_id}`，JSON 请求体示例：`{"reason":"误传文件"}`。

市民查询结果自动过滤内部附件。服务端响应下载时设置 `Content-Disposition` 和 `X-Content-Type-Options: nosniff`。

## 类型与大小限制

默认允许 JPG/JPEG、PNG、WebP、PDF、DOC/DOCX、XLS/XLSX 和 TXT。校验同时覆盖：

1. 扩展名白名单；
2. 声明的 MIME 白名单；
3. 扩展名与 MIME 的对应关系；
4. 文件头魔数；
5. DOCX/XLSX 必需的 OOXML 目录结构、条目数和解压后总大小上限；
6. 流式读取时的大小上限。

默认图片上限 10 MB，其他材料上限 20 MB，可通过 `ATTACHMENT_IMAGE_MAX_BYTES` 和 `ATTACHMENT_MAX_BYTES` 调整。危险的 HTML、SVG、脚本和压缩包不在白名单内。

## 恶意内容扫描接口

开发环境默认 `MALWARE_SCAN_MODE=disabled`，元数据记为 `skipped`。生产环境配置校验会强制要求：

```dotenv
MALWARE_SCAN_MODE=http
MALWARE_SCAN_URL=https://scanner.internal/v1/scan
MALWARE_SCAN_TOKEN=replace-with-secret
MALWARE_SCAN_REQUIRE_CLEAN=true
```

后端以文件原始字节作为 POST 请求体，发送 `Content-Type`、URL 编码的 `X-Filename` 和可选 Bearer Token。扫描服务应返回：

```json
{"status":"clean","engine":"clamav","detail":"optional"}
```

`status` 仅接受 `clean` 或 `infected`。`infected` 文件在进入对象存储前被拒绝；扫描超时、异常或返回格式错误，在强制扫描模式下返回 503。

## 本地启动与迁移

1. 在 `.env` 设置 MinIO 账号密码；开发默认值仅供本机使用。
2. 启动 `docker compose up -d --build`。
3. 后端启动时执行 Alembic `0006_ticket_attachments` 迁移，并自动创建私有附件桶。
4. MinIO API 默认位于 `http://localhost:9000`，管理控制台位于 `http://localhost:9001`。

生产环境必须启用 TLS，并使用独立的对象存储密钥。对象桶不应配置公共读策略。
