# 安全加固

> **【已收敛】** 现行安全边界请以 **[DEPLOYMENT.md](../DEPLOYMENT.md)** 与 `ENGINEERING.md` 为准。本文保留；文中扫描数字未在本轮重跑 → 以 Actions `dependency-security` 为准或标未验证。

## 已实施

- FastAPI CORS 精确白名单；生产环境拒绝空白名单和 `*`。
- Nginx CSP、X-Content-Type-Options、X-Frame-Options、Referrer-Policy、Permissions-Policy，隐藏版本。
- JWT 包含 `iss`、`aud`、`jti`、`iat`、`exp`，默认 30 分钟；前端遇到 401 清除会话 Token。
- 登录按客户端 IP 与用户名做进程内基础限流，默认 5 次/60 秒并返回 429/Retry-After。
- Nginx 和 Backend 请求体限制 1 MiB；代理、数据库、Action HTTP 调用均设置超时。
- Backend JSON 日志和审计详情递归脱敏密码、Token、Authorization、Cookie、身份证字段及完整身份证号模式。
- 前端没有 Token、密码或完整身份证号控制台输出；Token 只存 sessionStorage。
- `APP_ENV=production` 拒绝短密钥、占位密钥、弱数据库密码和宽泛 CORS。
- Seed 拒绝空密码、少于 12 位密码和常见默认密码；密码仅来自环境变量。

## 扫描与兼容结果（2026-07-14）

- `npm audit --omit=dev --registry=https://registry.npmjs.org`：0 vulnerabilities。
- 升级前 Starlette 0.41.3 命中 6 项当前 GitHub 公告。调用点审计确认项目不使用受影响的文件响应、静态文件、multipart、urlencoded form 或 `HTTPEndpoint`，鉴权也不依赖 `request.url.path`。
- Backend 已独立升级到 FastAPI 0.139.0 / Starlette 1.3.1；后端与完整链路回归通过，Starlette 匹配公告清零。详细结论见 [最终测试报告](final-test-report.md)。
- Rasa 3.0.13 与其 Python 3.8 依赖树未升级；仅使用原配置/数据重新训练并固定 V1.0 模型制品。

纵深缓解仍保留：只通过 Nginx 暴露 Backend、保持 1 MiB 请求体限制和超时、限制可信来源并监控 4xx/5xx。Rasa 主版本升级继续作为独立迁移工作处理。

## 秘密管理

`.env` 已忽略，不应提交。生产秘密应从部署平台秘密存储注入并定期轮换。审计日志与系统日志均不得记录请求体、Authorization 或密码。
