# 倾听助手前端

React 19 + TypeScript + Vite + Ant Design 6 单页应用。使用 React Router 角色路由、TanStack Query 服务端状态、Axios 错误转换、ECharts 运营图表、Vitest 组件测试和 Playwright E2E。

```powershell
npm install
npm run dev       # http://localhost:5173
npm run build
npm test
npm run test:e2e  # 需先启动 Compose；真实账号用 E2E_PASSWORD 注入
```

部署镜像采用多阶段构建，Nginx 处理 SPA 回退，并把 `/api`、`/rasa` 代理到运行时配置的上游服务。
