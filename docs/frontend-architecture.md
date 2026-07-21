# 前端架构

## 分层

- `api/`：唯一的 URL 与 Axios 边界；请求自动携带 JWT，响应统一转换为 `ApiError`。
- `auth/`：从 `sessionStorage` 恢复 token，通过 `/auth/me` 获取可信角色；401 会清理状态。
- `routes/`：认证守卫与四角色守卫。按钮可见性用于体验，后端权限仍是最终依据。
- `pages/`：聊天、列表、详情和管理页面；服务端数据只由 TanStack Query 持有。
- `components/`：工单状态、服务端分页表格、ECharts 和安全错误态。

列表 Query Key 包含完整筛选对象；部门端“分派给我”使用 `mine=true` 由后端按 `assigned_user_id` 过滤，不在浏览器加载后再筛选。写操作成功后同时失效列表和详情缓存。409 不做乐观伪成功，而是提示冲突并重新拉取详情。

## 会话和安全

登录 token 仅保存于会话存储。Rasa `sender_id` 对登录用户稳定派生为 `web-user-{id}`，匿名用户使用一次生成并持久化的 UUID。后端只把与当前 JWT 用户 ID 精确匹配的稳定 sender 哈希纳入该市民的数据范围，因此聊天创建的工单可进入详情和“我的工单”，其他市民仍被拒绝。聊天文本使用 React 文本节点渲染，不使用 `dangerouslySetInnerHTML`；工单卡片按当前 `QT + 日期 8 位 + 序号 8 位` 格式识别。

## 部署

Vite 开发代理连接本机服务。生产构建由 Nginx 提供静态资源、SPA fallback 和同源 `/api`、`/rasa` 代理；上游通过 `BACKEND_UPSTREAM` 与 `RASA_UPSTREAM` 注入。
