# 认证与权限

## 认证

密码使用 pwdlib 推荐的 Argon2 哈希。登录成功签发 HS256 JWT，密钥和分钟级有效期来自 `JWT_SECRET`、`JWT_ACCESS_TOKEN_MINUTES`。禁用账号、错误密码和不存在用户统一返回安全错误；无效/过期 Token 返回 401。

Action Server 通过 `TICKET_SERVICE_TOKEN` 读取与 Backend `SERVICE_API_TOKEN` 相同的部署秘密。该主体只能创建 Rasa 工单和查询与会话摘要匹配的脱敏工单，不是管理员。

## 权限矩阵

| 能力 | citizen | agent | department_staff | admin |
|---|---|---|---|---|
| 查看工单 | 本人创建 | 待受理/未派发 | 本部门 | 全部 |
| 创建 | 是 | 是 | 否 | 是 |
| 受理/拒绝/派发 | 否 | 是 | 否 | 是 |
| 处理/解决 | 否 | 否 | 本部门 | 是 |
| 办结 | 否 | 否 | 否 | 是 |
| 修改联系方式 | 本人工单 | 可见工单 | 否 | 是 |

权限判断集中在 `AuthorizationPolicy`；拒绝会写 `permission_denied` 审计。响应不包含内部 user_id、department_id 或审计内容，服务身份响应还会移除 contact。

管理员可通过 `/api/v1/users` 创建、列表和更新/启停用户，通过 `/api/v1/departments` 创建和更新/启停部门；密码只以新 Argon2 哈希写入，响应永不返回 password_hash。系统禁止管理员停用当前登录账号。

## 本地种子

`python -m app.seed_local` 只有显式提供至少 12 位 `LOCAL_SEED_PASSWORD` 才运行。四个 `_local` 账号仅限本地测试，不应在共享或生产环境初始化。
