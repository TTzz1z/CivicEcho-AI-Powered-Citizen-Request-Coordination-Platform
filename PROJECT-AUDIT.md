# 倾听助手项目全面现状审计

> 审计日期：2026-07-19（Asia/Shanghai）  
> 审计范围：当前工作区的代码、容器运行态、HTTP 接口、PostgreSQL/MinIO 数据、迁移、测试和脚本  
> 审计原则：只检查和记录；没有为了通过测试而改业务代码、重写架构或补功能

## 1. 执行摘要

当前项目不是纯演示壳。React 前端、FastAPI、PostgreSQL、MinIO、Rasa、Action Server 和 Duckling 七个服务实际存在；审计开始时七个 Compose 服务均为 `healthy`。本轮用真实 HTTP 请求和数据库查询走通了“建单—受理—派发—部门办理—提交结果—市民不满意—再次办理—申诉—审核重办—再次提交—市民确认—办结—管理员审计”的主闭环，并验证了越权拒绝、幂等建单、乐观锁冲突、附件可见性、AI 建议不改变状态以及关键记录落库。

但“核心闭环可运行”不等于“已具备生产上线条件”。默认前端测试门禁失败，Alembic 模型与迁移元数据存在漂移，附件恶意文件扫描默认关闭，通知仅站内真实、临期提醒依赖用户打开通知页才触发扫描，Rasa tracker 默认内存存储，外部政务/短信/地图/OIDC/监控全部未配置，备份脚本不包含 MinIO 对象。审计后段运行 Rasa 离线测试时 Docker 引擎曾持续无响应，七容器随后同时退出；引擎恢复后本轮用 `docker compose up -d --wait` 恢复了七服务 healthy，但 Rasa 离线门禁、Playwright 和恢复演练仍没有有效通过证据。

### 1.1 证据等级

| 标记 | 含义 |
|---|---|
| `D` | 文档声称；只代表预期，不作为实现结论 |
| `C` | 代码/配置/迁移中存在，但本轮未实际运行该分支 |
| `R` | 本轮已通过运行、HTTP、容器、数据库或对象存储验证 |
| `T` | 本轮自动化测试实际覆盖 |
| `U` | 当前无法验证；不得视为正常 |

### 1.2 状态口径

| 状态 | 判定标准 |
|---|---|
| 正常 | 主路径存在且本轮运行或有效自动化测试验证通过 |
| 部分正常 | 核心可用，但有明显缺口、只覆盖部分渠道或依赖手工触发 |
| 异常 | 代码/页面/脚本存在，但当前调用、门禁或行为失败 |
| 占位 | 有 UI、路由、状态端点或适配器骨架，没有业务实现 |
| Mock | 返回确定性模拟结果或使用内存替身，不是真实外部系统 |
| 未接入 | 适配器存在，但当前配置明确关闭或缺少凭据 |
| 未实现 | 所需页面、接口、数据模型或执行器不存在 |
| 无法验证 | 因当前环境/依赖异常没有得到有效证据 |

### 1.3 总体结论

| 领域 | 状态 | 结论与证据 |
|---|---|---|
| 四角色核心工单闭环 | 正常 | `R/T`；真实工单 `QT2026071900000005` 最终 `closed, version=12`，见第 7 节 |
| Rasa 新建诉求链 | 部分正常 | `R`；Rasa→Action→FastAPI→PostgreSQL 成功，但 tracker 内存化，裸工单号查询落入 fallback |
| 页面与真实后端连接 | 部分正常 | `C/T/R`；主要页面调用真实 API；部门端可见但无权限的“同步工单平台”按钮会返回 403 |
| 数据库业务一致性 | 部分正常 | `R/T`；业务落库完整，但 `alembic check` 报索引/Identity 元数据漂移 |
| 附件与 MinIO | 部分正常 | `R`；上传、下载、隔离、软删除和对象删除有效；恶意文件扫描为 disabled/skipped |
| 通知、回访、申诉 | 部分正常 | `R/T`；站内通知、回访任务、申诉重办真实；外部消息和自动回访未接入 |
| AI | 部分正常 | `R/T`；六类规则建议可持久化并人工复核，`advisory_only=true`；不是大模型能力 |
| 管理能力 | 部分正常 | `C/T/R`；用户、部门、分类、审计存在；平台配置管理未实现 |
| 安全与审计 | 部分正常 | `C/R/T`；JWT、Argon2、RBAC、审计、请求 ID 存在；限流单进程、体积限制依赖 Content-Length |
| 外部集成 | 未接入 | `R`；OIDC、目录、政务工单、短信、地图、区划、集中日志、监控均返回未配置 |
| 默认质量门禁 | 异常 | `R`；Vitest 默认 4 个测试超时并产生 7 个未处理异常 |
| Compose 最终状态 | 正常（恢复后） | 审计末尾 `docker compose up -d --wait` 成功；七服务 healthy，五个宿主 HTTP 探针均 200 |

按“可演示 MVP”口径估算实际完成度约 **82%**；按“可安全上线、可运维、可恢复”口径约 **55%**。这是依据本报告缺口做的审计估算，不是项目正式验收分数。

## 2. 审计边界、临时操作与保留数据

### 2.1 本轮做过的最小操作

1. 未修改任何业务代码、Compose、迁移、前端或测试。
2. 在运行中的 backend 容器临时安装 `requirements-dev.txt`，只用于执行 pytest/Ruff；容器层变化没有写入仓库。
3. 创建隔离数据库 `tingting_audit_20260719`，验证迁移、降级/升级、Seed 和后端测试后删除。
4. 通过现有后端 JWT 实现为数据库中四个既有角色生成短期审计令牌；未修改密码，报告不记录任何令牌或秘密。
5. 保留两条审计工单作为可追溯证据：HTTP 核心闭环 `QT2026071900000005`；Rasa 链路 `QT2026071900000007`。
6. Rasa 离线测试命令卡死后，只终止了本轮创建的两个 `docker compose run ... rasa test core` CLI 进程；没有重启 Docker Desktop、停止主栈或影响其他项目。
7. Ruff、TypeScript 和 Vite 命令刷新了 `.ruff_cache`、`frontend/tsconfig.app.tsbuildinfo` 和 `frontend/dist` 等生成物；没有人工编辑这些产物。
8. Docker 引擎自行恢复后发现本项目七容器均为 `Exited (255)`；为恢复审计开始时的运行态，仅执行 `docker compose up -d --wait`，143.2 秒后七服务全部 healthy，没有重建镜像或改配置。

首次审计探针有两次非业务失败：生产 backend 镜像没有 `httpx`；随后 PowerShell 管道把中文变为 `??`，请求得到 422。两次均发生在业务写入前，后续改用标准库和 Unicode 转义完成验证。

### 2.2 无法用 Git 证明差异

当前目录虽有 `.git` 路径痕迹，但 `git status --short` 返回 `fatal: not a git repository`。因此本报告只能确认本轮唯一人工新增文件为 `PROJECT-AUDIT.md`，不能提供可靠 Git diff；测试/构建生成物的时间戳变化见上一节。

## 3. 项目实际架构与运行方式

### 3.1 实际模块

| 模块 | 实际实现 | 本轮状态 | 证据 |
|---|---|---|---|
| Frontend | React + TypeScript + Vite，Nginx 托管并代理 `/api` | 审计开始 healthy；构建通过 | `frontend/src`、`frontend/nginx.conf.template`、`frontend/Dockerfile`；`npm run build` |
| Backend | FastAPI，业务真相源、RBAC、状态机、审计 | 真实闭环通过 | `backend/app/main.py`、`backend/app/api`、`backend/app/services` |
| Rasa | 中文诉求收集和旧英文 Helpdesk/ServiceNow 兼容意图 | HTTP 对话实测部分通过 | `domain.yml`、`data`、`endpoints.yml`、`config.yml` |
| Action Server | Rasa 自定义 Action，经服务令牌调用 FastAPI | POST/GET 实测 201/200 | `actions/actions.py`、`actions/ticket_store.py`、Action 日志 |
| PostgreSQL | 业务、状态历史、审计、通知、AI 建议等持久化 | 实际读写通过 | `backend/migrations/versions/0001_create_ticket_tables.py` 至 `0009_ai_and_platform_integrations.py`、数据库查询 |
| MinIO | S3 兼容附件对象存储 | 上传/下载/删除实测通过 | `backend/app/storage.py`、`ticket_attachments`、MinIO 对象操作 |
| Duckling | Rasa 时间实体解析服务 | 审计开始 healthy | `docker-compose.yml`、Rasa HTTP 配置 |

Compose 实际为七服务，而旧发布文档中的“六服务 healthy”已经过期。审计开始时 `docker compose ps` 显示 frontend、backend、rasa、action_server、postgres、minio、duckling 全部 healthy；宿主端口为 frontend 8081、backend 8001、Rasa 5005、Action 5055、Duckling 18080、MinIO 29000/29001，PostgreSQL仅容器网络可见。

### 3.2 真实调用链

```text
浏览器 React
  ├─ /api/v1/* ──> Nginx ──> FastAPI ──> PostgreSQL
  │                                      └─> MinIO
  └─ /webhooks/rest/webhook ──> Rasa ──> Action Server
                                           └─服务令牌──> FastAPI ──> PostgreSQL
```

FastAPI 是状态真相源：Action Server 的 HTTP gateway 只调用 `/api/v1/tickets` 和查询接口；状态、版本和审计由 backend 事务写入。`actions/ticket_store.py` 中的内存 gateway 是显式 Mock 后备，不是当前 Compose 默认路径。Compose 中 `TICKET_BACKEND_MODE=http`。

### 3.3 文档声称与现实差异

| 文档声称 | 代码/本轮现实 |
|---|---|
| README 把完整闭环描述为“可运行、可测试、可复现” | 核心 HTTP 闭环本轮真实通过；默认前端测试失败，Rasa 离线门禁和 Playwright 本轮无法完成，不能整体写成测试全绿 |
| `docs/project-overview.md` 记录 Backend 18、Action 21、Vitest 12、三浏览器 63 条 E2E | 当前后端为 32 passed；Action 拆分运行 18+3 passed；Vitest 当前 17 条但默认 4 fail；数字已经漂移 |
| `docs/round-7-release-report.md` 记录 0003 head、六服务、51/51 E2E | 当前迁移为 0009、七服务；旧报告是 2026-07-14 历史快照，不代表本轮结果 |
| README 声称备份恢复脚本 | 脚本存在，但只备份 PostgreSQL，不含 MinIO 对象；本轮恢复演练未执行 |
| README 明确外部能力默认关闭 | 与本轮运行态一致；八项集成均未配置，不能标正常 |

## 4. 四角色页面、菜单、功能与数据权限

路由注册证据：`frontend/src/routes/AppRoutes.tsx`；菜单证据：`frontend/src/layouts/WorkspaceLayout.tsx`；权限真相：`backend/app/authorization.py`、`backend/app/api/dependencies.py` 与各 API 的资源范围查询。

### 4.1 公共入口

| 路由 | 页面/功能 | 后端连接 | 状态 |
|---|---|---|---|
| `/welcome` | 产品入口 | 无业务写入 | 正常 `C` |
| `/login` | 密码登录 | `POST /api/v1/auth/login` | 正常 `C/T`；本轮未用真实密码登录 |
| `/auth/oidc/callback` | OIDC 回调 | config/exchange API | 未接入 `R`；config 返回 `enabled=false` |
| `/chat` | 匿名 Rasa 对话 | `/webhooks/rest/webhook` | 部分正常 `R`；可建单，身份只保存在浏览器 sender id |
| `/forbidden` | 越权提示 | 无 | 正常 `C` |

### 4.2 市民端

| 路由/菜单 | 真实功能 | 数据范围 | 状态与证据 |
|---|---|---|---|
| `/citizen/chat` | Rasa 自然语言登记/查询 | 登录 sender 为 `web-user-{id}`，后端用哈希关联本人 | 部分正常 `R`；显式查询意图成功，直接输入工单号失败 |
| `/citizen/tickets` | 本人诉求列表、状态筛选 | `creator_user_id` 或匿名创建键属于本人 | 正常 `C/T/R` |
| `/citizen/tickets/:id` | 详情、补充、确认/不满意、申诉、附件 | 仅本人；附件按可见性过滤 | 正常/部分 `R`；核心动作实测，内部附件不可见 |
| `/citizen/tickets/:id/intelligence` | 相似、摘要、完整性、风险等建议 | 只能分析自己的工单，市民只允许四类非内部建议 | 部分正常 `C/T`；规则 AI，刷新后不会主动加载历史建议 |
| `/citizen/notifications` | 站内通知、标记已读 | 仅本人通知 | 正常 `C/T/R` |
| `/citizen/aftercare` | 本人反馈与申诉结果 | 仅本人诉求 | 正常 `C/T/R` |

### 4.3 坐席端

| 路由/菜单 | 真实功能 | 数据范围 | 状态与证据 |
|---|---|---|---|
| `/agent/tickets` | 待办/在办列表、筛选 | 不能查看 closed/rejected | 正常 `C/T/R`；办结后访问 403 |
| `/agent/tickets/:id` | 受理、拒绝、派发、补充请求、联系信息、协同工单 | 非 closed/rejected | 正常/部分；受理派发实测，初次派发 UI 不加载具体人员列表，后续可在协同工单面板分配 |
| `/agent/tickets/:id/intelligence` | 六类建议、人工复核、外部同步 | 可查看工单 | 部分正常；AI 实测，外部同步未配置返回 409 |
| `/agent/notifications` | 本人站内通知 | 本人 | 正常 `C/T` |
| `/agent/aftercare` | 回访任务、电话记录、申诉列表 | 坐席可见范围 | 部分正常 `C/T/R`；电话记录是人工录入，无自动呼叫 |

### 4.4 部门人员端

| 路由/菜单 | 真实功能 | 数据范围 | 状态与证据 |
|---|---|---|---|
| `/department/tickets` | 本部门被派发/协办工单 | 主部门或本部门 work order | 正常 `R`；未派发前 403、派发后 200 |
| `/department/tickets/:id` | 开始办理、备注、退回、转派、协办、提交结果、暂停恢复 SLA | 只能本部门且动作受状态机限制 | 正常/部分 `T/R`；主流程实测，退回/转派/协办由后端测试覆盖 |
| `/department/tickets/:id/intelligence` | 六类建议 | 本部门工单 | 异常；页面显示“同步真实工单平台”按钮，但 backend 仅允许 agent/admin，点击必得 403 |
| `/department/notifications` | 本人站内通知 | 本人 | 正常 `C/T` |
| `/department/aftercare` | 只读相关后处理信息 | 本部门范围 | 部分正常 `C/T`；电话回访操作仅 agent/admin |

### 4.5 管理员端

| 路由/菜单 | 真实功能 | 数据范围 | 状态与证据 |
|---|---|---|---|
| `/admin/dashboard` | 数量、状态、SLA、部门统计 | 全局 | 正常 `C/T/R`；市民访问 403 |
| `/admin/tickets`、详情 | 全量工单和管理员干预 | 全局 | 正常 `C/T/R` |
| `/admin/intelligence`/详情 intelligence | AI 建议、热点 | 全局 | 部分正常；规则引擎，无真实 LLM |
| `/admin/notifications` | 本人站内通知 | 本人 | 正常 `C/T` |
| `/admin/aftercare` | 回访、申诉审核 | 全局 | 正常/部分 `R`；申诉审核实测，外呼未接入 |
| `/admin/categories` | 分类树增改停用 | 全局 | 正常 `C/T` |
| `/admin/users` | 用户增改停用 | 全局 | 正常 `C/T` |
| `/admin/departments` | 部门增改停用、目录同步 | 全局 | 部分正常；本地 CRUD 存在，外部目录未配置 |
| `/admin/audit` | 审计日志筛选 | 全局 | 正常 `R`；闭环审计日志已落库 |
| 平台配置 | 无页面、无配置表、无 CRUD API | 环境变量 | 未实现；只有集成状态与探针端点 |

## 5. 完整功能清单

| 功能 | 状态 | 实现/验证证据 | 限制 |
|---|---|---|---|
| 自然语言诉求登记 | 部分正常 | `actions/actions.py`、Rasa REST 实测创建 `QT2026071900000007` | NLU/离线门禁本轮未完成；tracker 内存化 |
| 工单创建 | 正常 | `POST /api/v1/tickets` 201；`tickets`/history/audit 落库 | 匿名身份绑定依赖 sender hash |
| 受理/拒绝 | 正常 | accept 实测；reject 后端测试 | 状态边严格 |
| 派发 | 正常 | assign 实测，创建 primary work order | agent 初次派发 UI 对人员选择不完整 |
| 办理/处理备注 | 正常 | department start、ticket processing 实测 | 无富文本/复杂流程引擎 |
| 退回/转派/协办 | 正常（测试证据） | work-order router 与 backend pytest | 本轮主栈未逐一人工点击 |
| 复核 | 部分正常 | review 型 work order 模型和测试存在 | 不是独立可配置审批流 |
| 结果提交 | 正常 | work order submit + ticket summary 实测 | 结果以文本/附件为主 |
| 市民确认和办结 | 正常 | satisfied 后 `resolved→closed` 实测 | 未确认不会自动办结 |
| 市民不满意重新办理 | 正常 | dissatisfied 后 `resolved→processing` 实测 | 依赖原部门继续处理 |
| 分类 | 正常 | categories API/模型/管理页/测试 | Seed 只有基础分类集合 |
| 优先级 | 正常 | ticket 字段、表单、筛选、规则 | 无独立优先级配置表 |
| SLA | 部分正常 | due_at、pause/resume、breach/due-soon 逻辑与测试 | 按分钟墙钟计算，无工作日/节假日日历 |
| 催办 | 正常 | remind API 写通知/历史/审计 | 无短信渠道 |
| 临期/超期 | 部分正常 | dashboard/通知逻辑存在 | due-soon 扫描由打开通知列表触发，无 scheduler/worker |
| 附件上传/下载 | 正常 | MinIO 实传 23 bytes、部门下载 200 | 市民看不到 internal 文件 |
| 附件权限/可见性 | 正常 | citizen list 0、download 403；department 200 | 可见性为枚举级策略 |
| 附件软删除 | 正常 | DB `deleted=true`，对象随后不可 stat | 无回收站恢复 |
| 文件校验 | 部分正常 | 大小、扩展名、MIME、哈希存在 | malware scanner 未启用，结果 `skipped/disabled` |
| 站内通知 | 正常 | 本轮闭环生成 16 条 | 直接写表，不是可靠消息队列/outbox |
| 短信/微信/邮件/政务消息 | 未接入 | channels API 标记 reserved；SMS 409 | 无真实发送 |
| 回访任务 | 正常 | resolve 自动生成任务，本工单 2 条 | 无后台自动拨号/定时执行器 |
| 电话回访记录 | 部分正常 | API/表/页面存在 | 本轮工单 0 条；需要人工录入 |
| 评价 | 正常 | 满意/不满意均实测，2 条 feedback | 评价模型较简单 |
| 申诉/审核/重新办理 | 正常 | submitted→reprocessing→completed 实测 | 仅管理员审核 |
| AI 部门建议 | 部分正常 | rules provider，建议持久化 | 非模型推理、非外部 AI |
| 相似工单 | 部分正常 | 规则/关键词相似度 | 不是向量检索/RAG |
| 摘要/完整性检查/文书草稿/风险提示 | 部分正常 | 六类 analyze 全部 200、DB 6 条 | 确定性规则模板 |
| 热点聚类 | 部分正常 | hotspots API/页面 | 分类/文本规则聚合，不是模型聚类 |
| advisory_only/人工复核 | 正常 | 全部建议 `advisory_only=true`，review 实测 | 前端刷新后不重新拉取历史建议 |
| 用户/部门/分类管理 | 正常 | 管理页 + CRUD API + 测试 | 外部目录同步未接入 |
| 审计日志 | 正常 | 本闭环直接 resource audit 18 条 | 日志查询仅管理员 |
| 平台配置管理 | 未实现 | 无表、无 UI、无 CRUD | 运行配置依赖环境变量 |

## 6. 全部后端接口及测试状态

接口清单来自本轮运行时 OpenAPI，并以 `backend/app/api/*.py` 的 73 个 path-method operation（包含健康别名）交叉核对。所有 `/api/v1` 成功响应使用统一 success envelope；认证失败、越权、冲突、限流和体积超限实际使用 JSON error envelope。OpenAPI 操作多数只声明成功响应和 422，没有完整声明实际可能出现的 401/403/409/413/429/500，属于接口契约文档缺口。

状态缩写：`RV` 本轮主栈 HTTP 验证，`BT` 后端 pytest，`CE` 代码存在/静态核对，`UV` 本轮无法运行验证。

### 6.1 健康与认证

| 方法与路径 | 调用端/权限 | 主要参数与响应 | 状态 |
|---|---|---|---|
| `GET /health/live` | Compose/公开 | `{status}` | `RV` 200 |
| `GET /health/ready` | Compose/公开 | DB、对象存储等 readiness | `RV/BT` 200（审计开始） |
| `GET /health` | 兼容探针/公开 | health alias | `CE/BT`，重复兼容端点 |
| `GET /api/v1/system/health` | 前端/公开 | API health alias | `CE/BT`，重复兼容端点 |
| `POST /api/v1/auth/login` | Login/公开 | `username,password`→JWT/user | `BT`；本轮未用真实密码 |
| `GET /api/v1/auth/me` | 路由守卫/登录用户 | 当前用户 | `CE/BT` |
| `GET /api/v1/auth/oidc/config` | Login/公开 | enabled/provider | `RV` 200，enabled=false |
| `POST /api/v1/auth/oidc/exchange` | OIDC callback/公开 | authorization code | `CE/BT`；当前禁用 |

### 6.2 用户、部门、分类与管理员分析

| 方法与路径 | 调用端/权限 | 主要参数与响应 | 状态 |
|---|---|---|---|
| `GET /api/v1/users` | Admin；工单组件有限使用 | filters→users | `CE/BT` |
| `POST /api/v1/users` | Admin | user create→user | `CE/BT` |
| `PATCH /api/v1/users/{id}` | Admin | partial update→user | `CE/BT` |
| `GET /api/v1/departments` | 全部登录用户；inactive 仅 Admin | filters→departments | `CE/BT` |
| `POST /api/v1/departments` | Admin | department create | `CE/BT` |
| `PATCH /api/v1/departments/{id}` | Admin | partial update | `CE/BT` |
| `GET /api/v1/departments/{id}/staff` | Agent/Admin/同部门 | staff list | `CE/BT` |
| `GET /api/v1/categories` | 全部登录用户；inactive 仅 Admin | tree/list | `CE/BT` |
| `POST /api/v1/categories` | Admin | category create | `CE/BT` |
| `PATCH /api/v1/categories/{id}` | Admin | partial update | `CE/BT` |
| `GET /api/v1/admin/dashboard` | Admin | aggregate counts/SLA | `RV/BT`；citizen 403 |
| `GET /api/v1/admin/audit-logs` | Admin | filters/paging→logs | `RV/BT` |

### 6.3 工单与协同办理

| 方法与路径 | 调用端/权限 | 主要参数与响应 | 状态 |
|---|---|---|---|
| `POST /api/v1/tickets` | Rasa 服务身份/市民/坐席等 | create + `idempotency_key`→ticket/replay | `RV/BT`；重复请求返回同 ID |
| `GET /api/v1/tickets` | 四角色 | filters/paging，按角色 SQL scope | `CE/BT/RV` |
| `GET /api/v1/tickets/{id}` | 四角色 | ticket + history/work orders/etc. | `RV/BT` |
| `POST /tickets/{id}/accept` | Agent/Admin | `version,note` | `RV/BT` |
| `POST /tickets/{id}/reject` | Agent/Admin | `version,reason` | `BT` |
| `POST /tickets/{id}/assign` | Agent/Admin | dept/assignee/version | `RV/BT` |
| `POST /tickets/{id}/supplement-request` | Agent/Admin | fields/message/version | `CE/BT` |
| `POST /tickets/{id}/supplement` | Citizen owner/Admin | supplied fields/version | `CE/BT` |
| `GET /tickets/{id}/work-orders` | Authorized viewer | work-order list | `CE/BT`；前端详情已内嵌，单独端点未调用 |
| `POST /tickets/{id}/work-orders` | Agent/Admin/authorized flow | type/dept/assignee/version | `BT` |
| `POST /tickets/{ticket_id}/work-orders/{work_order_id}/assign` | Agent/Admin/department scope | assignee/version | `BT` |
| `POST /tickets/{ticket_id}/work-orders/{work_order_id}/start` | Department scope | version/note | `RV/BT` |
| `POST /tickets/{ticket_id}/work-orders/{work_order_id}/return` | Department/authorized | version/reason | `BT` |
| `POST /tickets/{ticket_id}/work-orders/{work_order_id}/transfer` | Department/authorized | target/version | `BT` |
| `POST /tickets/{ticket_id}/work-orders/{work_order_id}/submit` | Department scope | result/version | `RV/BT` |
| `POST /tickets/{id}/summary` | Agent/Department/Admin | summary/version | `RV/BT` |
| `POST /tickets/{id}/dispute` | Authorized user | reason/version | `CE/BT`；兼容业务动作 |
| `POST /tickets/{id}/dispute/resolve` | Authorized staff | result/version | `CE/BT` |
| `POST /tickets/{id}/process` | Department/Admin | version/note | `RV/BT` |
| `POST /tickets/{id}/note` | Department/Admin | note/version | `CE/BT` |
| `POST /tickets/{id}/resolve` | Department/Admin | result/version | `RV/BT` |
| `POST /tickets/{id}/close` | Citizen owner/Admin | version/note | `CE/BT`；市民 UI 主要走 feedback |
| `POST /tickets/{id}/feedback` | Citizen owner | satisfied/comment/version | `RV/BT` |
| `PATCH /tickets/{id}/status` | 兼容调用/角色受限 | status/version | `CE/BT`；前端未调用，和动作端点有语义重复 |
| `PATCH /tickets/{id}/contact` | Citizen owner/authorized staff | contact/version | `CE/BT` |
| `POST /tickets/{id}/sla/pause` | Department/Admin | reason/version | `BT` |
| `POST /tickets/{id}/sla/resume` | Department/Admin | version | `BT` |
| `POST /tickets/{id}/remind` | Citizen owner/Agent/Admin | message/version | `BT` |

### 6.4 附件、通知、回访与申诉

| 方法与路径 | 调用端/权限 | 主要参数与响应 | 状态 |
|---|---|---|---|
| `POST /tickets/{id}/attachments` | Authorized viewer/actioner | multipart file + visibility | `RV/BT`；MinIO 实传 |
| `GET /tickets/{id}/attachments` | Authorized viewer | visibility-filtered list | `RV/BT` |
| `GET /attachments/{id}/download` | 可查看该附件的用户 | binary + security headers | `RV/BT`；citizen 403/dept 200 |
| `DELETE /attachments/{id}` | uploader/authorized role | soft delete | `RV/BT` |
| `GET /notifications` | 登录用户 | filters/paging；顺带 due-soon scan | `CE/BT` |
| `POST /notifications/{id}/read` | notification owner | read result | `CE/BT` |
| `POST /notifications/read-all` | 登录用户 | count | `CE/BT` |
| `GET /notifications/channels` | 登录用户 | in-app + reserved channels | `CE`；外部渠道 false |
| `GET /follow-ups` | Agent/Admin | scoped tasks | `CE/BT` |
| `POST /follow-ups/{id}/phone-record` | Agent/Admin | manual record | `CE/BT` |
| `GET /appeals` | 四角色按 scope | filters/list | `CE/BT/RV` |
| `POST /tickets/{id}/appeals` | Citizen owner | reason/version | `RV/BT` |
| `POST /appeals/{id}/review` | Admin | approve/reject/version | `RV/BT` |

### 6.5 AI 与外部集成

| 方法与路径 | 调用端/权限 | 主要参数与响应 | 状态 |
|---|---|---|---|
| `POST /ai/tickets/{id}/analyze` | Viewer；citizen 类型受限 | suggestion type→advisory result | `RV/BT`；六类均 200 |
| `GET /ai/tickets/{id}/suggestions` | Viewer | persisted suggestions | `CE/BT`；前端 API 封装存在但页面未调用 |
| `POST /ai/suggestions/{id}/review` | Viewer/authorized staff | decision/comment | `RV/BT` |
| `GET /ai/hotspots` | Agent/Department/Admin | period/filters | `CE/BT` |
| `GET /integrations/status` | Admin | 8 integrations + configured flags | `RV`；全部 false |
| `POST /integrations/directory/sync` | Admin | sync request | `CE`；未配置返回冲突 |
| `POST /integrations/tickets/{id}/sync` | Agent/Admin | external sync | `RV` 未配置；部门 UI 错配为 403 |
| `GET /integrations/map/geocode` | 登录用户 | address | `RV` 409 `MAP_NOT_CONFIGURED` |
| `GET /integrations/divisions` | 登录用户 | division query | `CE`；未配置 |
| `GET /integrations/metrics` | Admin | integration counters | `CE`；不等于 Prometheus 接入 |
| `POST /integrations/sms/send` | Admin | recipient/message | `RV` 409 `SMS_NOT_CONFIGURED` |
| `POST /integrations/{kind}/probe` | Admin | kind | `CE`；只探测已配置适配器 |

### 6.6 未调用、重复、失效和字段问题

1. `GET /ai/tickets/{id}/suggestions` 在 `frontend/src/api/intelligence.ts` 有封装，但 IntelligencePage 不调用；建议已持久化，页面刷新后不能恢复展示。
2. `GET /tickets/{id}/work-orders` 与详情响应中的 work orders 重复，前端没有单独调用。
3. `PATCH /tickets/{id}/status` 是兼容端点，当前前端使用命名动作端点；两套入口增加维护面。
4. 三个 health alias 是有意兼容，但文档/API 消费者应明确主端点。
5. map、divisions、metrics、sms、probe 没有普通业务页面；只有部分 admin 状态/同步入口。
6. 部门端 IntelligencePage 展示 agent/admin 才可调用的同步按钮，是已确认的页面—接口权限断链。
7. 没有发现核心工单列表/详情返回硬编码假数据；Mock 主要位于 ServiceNow local mode、Action 内存 gateway 和测试 fixtures。

## 7. 页面—接口—数据库对应关系

| 页面/控件 | 实际接口 | 主要数据表 | 审计结论 |
|---|---|---|---|
| Login 表单 | `/auth/login`、`/auth/me` | `users` | 真实后端；JWT 存 sessionStorage |
| OIDC 按钮/回调 | `/auth/oidc/config|exchange` | `users`（映射后） | 适配器存在，运行态禁用 |
| Chat 消息框 | Rasa REST webhook→Action→`POST/GET tickets` | `tickets`,`ticket_status_history`,`audit_logs` | 新建链实测；裸 ID 查询意图识别异常 |
| TicketList 筛选/分页 | `GET /tickets` | `tickets`,`departments`,`categories`,`work_orders` | SQL 层按角色 scope，不是只靠前端隐藏 |
| TicketDetail 操作按钮 | accept/assign/process/resolve/feedback/appeal 等 | `tickets`,`ticket_status_history`,`work_orders`,`work_order_history` | 真实状态机与 version 校验 |
| 协同工单面板 | work-order create/assign/start/return/transfer/submit | `work_orders`,`work_order_history` | 真实接口；本轮 start/submit 实测，其余 pytest |
| 附件上传/列表/下载/删除 | attachment APIs | `ticket_attachments` + MinIO bucket | DB 元数据和对象存储同时使用；隔离实测 |
| IntelligencePage 六类按钮 | AI analyze/review | `ai_suggestions` | 规则建议真实落库；历史 list 未接 UI |
| IntelligencePage 同步按钮 | integration ticket sync | `integration_events`（成功/尝试记录） | 外部未配置；部门角色按钮与后端权限不一致 |
| NotificationsPage | notification list/read/read-all | `notifications` | 站内真实；列表请求隐式触发临期扫描 |
| AftercarePage | follow-ups/phone-record/appeals/review | `follow_up_tasks`,`phone_follow_up_records`,`appeals` | 回访任务与申诉真实；外呼手工 |
| Dashboard | `/admin/dashboard` | tickets/work orders/departments 聚合 | admin-only，citizen 403 实测 |
| AuditPage | `/admin/audit-logs` | `audit_logs` | 真实审计查询 |
| Users/Departments/Categories 管理 | CRUD APIs | `users`,`departments`,`categories` | 真实本地管理 |
| Platform config | 无 | 无 | 未实现；环境变量不是平台配置管理 |

## 8. 数据库表、关系、迁移与 Seed 审计

### 8.1 当前真实数据库

本轮初始数据库版本为 `0009`，实际存在 18 张表：

```text
ai_suggestions, alembic_version, appeals, audit_logs, categories,
departments, follow_up_tasks, integration_events, notifications,
phone_follow_up_records, ticket_attachments, ticket_feedbacks,
ticket_status_history, tickets, users, work_order_history, work_orders
```

没有名为 `ticket_processing_records` 的表；“处理记录”由 `ticket_status_history` 和 `work_order_history` 承担。任何文档若把它描述成独立表均不准确。

审计主流程执行前基线计数：users 4、departments 7、categories 3、tickets 3、ticket history 12、work orders 2、work order history 3、attachments 1、notifications 22、follow-ups 2、phone records 0、appeals 1、AI suggestions 6、integration events 0、feedbacks 2、audit logs 56。四种角色各 1 个激活用户。

### 8.2 关系与约束

| 主表 | 关键关系/约束 | 结论 |
|---|---|---|
| `departments` | 用户、分类默认部门、工单 assigned dept、work order dept | 真实外键关系存在 |
| `users` | role、department；被工单/历史/审计/通知引用 | 四角色枚举和激活状态存在 |
| `categories` | 自引用 parent、默认部门、active | 可表达树形分类 |
| `tickets` | creator/category/assigned dept/assignee；status/priority/version/idempotency | 业务聚合根；幂等键有唯一语义，version 用于乐观锁 |
| `ticket_status_history` | ticket、actor、from/to、action、visibility | 主状态历史；闭环 10 条 |
| `work_orders` | ticket、department、assignee、type/status/version | 部门协同与独立乐观锁 |
| `work_order_history` | work order/ticket/actor/action | 协同处理轨迹；闭环 3 条 |
| `ticket_attachments` | ticket/uploader/object key/visibility/hash/scan/deleted | 元数据真实，内容在 MinIO |
| `notifications` | recipient/ticket/type/read/delivery | 当前真实渠道为 in_app |
| `follow_up_tasks`/`phone_follow_up_records` | ticket、assignee、task、operator | resolve 生成任务；电话结果独立记录 |
| `ticket_feedbacks` | ticket/citizen/satisfied/comment | 支持多轮反馈；闭环 2 条 |
| `appeals` | ticket/citizen/reviewer/status/version | 申诉审核和重新办理 |
| `ai_suggestions` | ticket/type/content/advisory/review | 可审计建议持久化 |
| `audit_logs` | actor/resource/action/request_id/details | 安全与敏感读取审计 |
| `integration_events` | kind/resource/status/payload/error | 外部同步事件；当前基线为 0 |

迁移为 `backend/migrations/versions/0001_create_ticket_tables.py` 至 `0009_ai_and_platform_integrations.py`。空库 `upgrade head` 成功；`0009→0008→0009` 降级/再升级成功。Seed 在隔离数据库连续执行两次，结果均为 departments=7、users=4、tickets=0，内容层面幂等；用户密码哈希会因 Argon2 salt 重写，不应据此判定行重复。

### 8.3 迁移漂移

`alembic check` **失败**，报告模型想删除数据库索引 `ix_audit_request_id`、`ix_tickets_external_reference`，并认为多张表的 BIGINT 主键 Identity/default 与 ORM 元数据不一致，涉及 audit_logs、categories、departments、ticket_feedbacks、ticket_status_history、tickets、users、work_order_history。运行数据库仍可用，但“模型定义与迁移 head 完全一致”不成立；未来 autogenerate 有误删索引或产生噪音迁移的风险。

数据库迁移包含状态/角色等 CheckConstraint，而部分 ORM 模型没有完整镜像这些数据库约束，这也是元数据漂移的来源之一。

## 9. 核心状态机与业务闭环实测

### 9.1 主状态机

代码证据：`backend/app/services/ticket_service.py`、`backend/app/services/work_order_service.py`、`backend/app/authorization.py`、`backend/app/api/tickets.py`。

```text
pending --accept--> accepted --assign--> assigned --process--> processing
   |                                                         |
 reject                                                   resolve
   v                                                         v
rejected                    processing <--process-- resolved --close--> closed
                                                   |
                                      citizen dissatisfied / approved appeal
```

`note` 是 processing 自环。非法状态边在策略/服务事务内校验，不依赖 UI。work order 另有 `pending→processing→submitted`，并支持 returned/transferred/cancelled；primary/support/review 类型独立于 ticket 主状态。

### 9.2 本轮真实步骤

审计工单：`QT2026071900000005`，source=`audit-runtime`。除特别说明外均为主栈真实 HTTP 调用。

| 步骤 | 实际结果 | 数据证据 |
|---|---|---|
| health/readiness | 200 | 审计开始 backend ready |
| request_id 透传 | 200，响应回显 `AUDITREQ20260719` | `X-Request-ID` 与日志/审计关联 |
| CORS 预检 | 200，允许 `http://localhost:8081` | 显式 allow-origin |
| 1 MiB+ 普通 POST | 413 `REQUEST_TOO_LARGE` | request body middleware |
| 市民访问 admin dashboard | 403 | `permission_denied` 审计 |
| 首次建单 | 201，`idempotent_replay=false` | ticket/history/audit |
| 同 key 重放 | 201，`idempotent_replay=true`，相同 ticket ID | 没有重复 ticket |
| 未派发时部门读取 | 403 | 数据范围生效 |
| 市民执行 accept | 403 | 动作权限生效 |
| Agent 从 pending 直接 assign | 409 `INVALID_STATUS_TRANSITION` | 非法状态跳转被拒绝 |
| Agent accept | accepted，version 2 | history/audit |
| 使用旧 version=1 assign | 409 `VERSION_CONFLICT` | 乐观锁生效 |
| 使用当前 version assign | assigned，version 3 | primary work order 创建 |
| 派发后部门读取 | 200 | 部门 scope 生效 |
| 市民启动 work order | 403 | work-order 越权拒绝 |
| 部门启动 work order | processing，work-order version 2；ticket version 4 | 两类历史落库 |
| 六类 AI analyze | 全部 200，全部 `advisory_only=true` | 6 条 `ai_suggestions` |
| AI review | 200 | review actor/time 落库 |
| AI 前后 ticket version | 均为 4 | AI 没有改变工单状态或版本 |
| 上传 internal `.txt` | 201，scan=`skipped` | MinIO + attachment row |
| 市民列附件/下载 | 列表 0，下载 403 | 可见性/权限有效 |
| 部门下载 | 200，23 bytes，`nosniff` | 对象内容真实可取 |
| 部门提交 work order | submitted，version 3 | work_order_history |
| 提交处理结果 | resolved，ticket version 6 | 自动创建 follow-up |
| 市民不满意 | processing，version 7 | feedback + history |
| 部门再次 resolve | resolved，version 8 | 第二轮办理 |
| 市民申诉 | submitted | appeal row/history/audit |
| Admin 审核通过 | reprocessing | ticket 回到 processing |
| 部门完成重办 | resolved，version 11 | appeal completed |
| 市民满意确认 | closed，version 12，closure=`citizen_confirmed` | feedback/history/audit |
| 办结后 Agent 读取 | 403 | Agent scope 排除 closed |
| Admin 读取 | 200 | 全局权限 |
| 软删除附件 | 200 | DB deleted=true，对象随后无法 stat |

### 9.3 最终落库核对

| 数据 | 最终值/数量 |
|---|---|
| ticket | closed，version 12 |
| ticket_status_history | 10 |
| work_orders | 1 |
| work_order_history | 3 |
| feedbacks | 2 |
| attachments | 1，其中 deleted=1 |
| notifications | 16 |
| follow_up_tasks | 2 |
| phone_follow_up_records | 0 |
| appeals | 1，其中 completed=1 |
| ai_suggestions | 6 |
| 直接关联 resource audit logs | 18 |

历史动作依次包含 create、accept、assign、summary、citizen_feedback、resolve、submit_appeal、approve_appeal、resolve、citizen_feedback。直接关联审计动作统计含 accept 1、assign 1、change_ticket_status 2、confirm_triage 1、create 1、permission_denied 3、feedback 2、summary 1、view_sensitive 6。

结论：状态历史、协同处理、附件、通知、回访、申诉、评价、AI 建议和审计均有实际落库证据。没有通用 `ticket_processing_records` 表；处理证据分散在两类 history 表。电话回访在这条工单中没有产生记录，因为系统没有自动外呼，不能把 0 条包装成已验证。

## 10. Rasa 与 Action Server 调用链

### 10.1 实测链路

对 sender `audit-rasa-20260719-v1` 依次发送 `/submit_complaint`、描述、地点和 `/affirm`，Rasa 返回收集问题、确认摘要并创建 `QT2026071900000007`。Action Server 日志记录：

```text
action_backend_call request_id=RASA_AUDIT_20260719
method=POST path=/api/v1/tickets status=201 duration_ms=521.52
```

数据库核对：source=`rasa`、status=`pending`、version=1、creator_user_id=NULL、anonymous_creator_key 非空；有 1 条 create history；审计 actor_type=`service` 且 request_id=`RASA_AUDIT_20260719`。随后显式发送 `/query_request_status{"ticket_id":"QT2026071900000007"}`，Action 对 FastAPI GET 返回 200 并由 Rasa 回复状态。

这证明当前默认链路中 Rasa 负责槽位/对话编排，Action 负责协议转换，FastAPI/PostgreSQL 负责业务事务和状态真相。

### 10.2 已确认缺口与兼容资产

1. Chat 输入框提示可直接输入工单号，但直接发送 `QT2026071900000007` 落入 fallback；显式 intent 才能查询，页面文案与 NLU 实际能力不一致。
2. `endpoints.yml` 的 tracker store 没有启用，Rasa 默认内存 tracker；重启会丢失会话状态。
3. `rasa.db` 是当前主链未使用的兼容/陈旧资产，不能作为 tracker 持久化证据。
4. `actions/ticket_store.py` 的 MemoryTicketGateway 是 Mock fallback；当前 Compose 使用 HTTP gateway。
5. 旧 ServiceNow intents/actions 仍可触发；Compose 默认 `SERVICENOW_LOCAL_MODE=true`，返回“would be opened”式确定性模拟结果，属于 **Mock**，不是真实 ServiceNow。
6. `Dockerfile.chatroom`、`chatroom_handoff.html`、`handoff.gif` 等旧 Chatroom/Handoff 资产不在当前主 Compose React 链路中，属于未使用兼容资产。

## 11. 附件、通知、回访、申诉和 AI 专项

### 11.1 附件

- `backend/app/api/attachments.py`、`backend/app/services/attachment_service.py`、`backend/app/storage.py` 实现 multipart 校验、对象键、SHA-256、可见性、权限、下载安全头和软删除。
- 本轮 internal 附件由部门成功下载、市民被拒；删除后 DB 保留元数据而 MinIO 对象不可再读取，符合“软删业务记录 + 清理物理对象”的当前设计。
- 文件扫描适配器存在，但当前运行态为 disabled；审计上传记录为 `scan_status=skipped`。因此只能标“存储正常，安全扫描未接入”。
- 对普通 JSON POST 的请求体上限只在 POST 且依赖 Content-Length；chunked 请求和非 POST 大请求的覆盖不完整。Nginx 另有 `client_max_body_size 22m`，但它不是应用层统一保证。

### 11.2 通知与 SLA

- `notifications` 表和站内页面/API 为真实实现；闭环产生 16 条记录。
- 短信、微信、邮件、政务消息在 channels 响应中是 reserved/false；SMS 实测 409，不能标正常。
- 临期扫描函数在 `GET /notifications` 时执行，没有独立 scheduler、worker 或 cron。无人打开通知页时，临期提醒可能不生成，故为部分正常。
- SLA 支持 due_at、暂停/恢复、催办、临期和超期判断，但没有工作日/法定节假日日历，也没有可配置 SLA policy 表。

### 11.3 回访与申诉

- 每次 resolve 可生成 follow-up task；本工单经历两次 resolve，最终 2 条任务。
- 电话记录 API/表存在，但只由 agent/admin 人工提交；本工单 0 条，不存在自动外呼证据。
- 申诉 submitted、管理员 approve/reprocessing、部门 resolve/completed 均实测落库，随后市民确认 closed，闭环成立。

### 11.4 AI

- `backend/app/config.py`、`backend/app/services/ai_service.py`、`backend/app/repositories/ai.py` 当前只接受/实现 `rules` provider；不存在真实 LLM、向量数据库或 RAG 运行证据。
- assignment、similarity、summary、completeness、document_draft、risk 六类建议均返回并持久化。
- 全部建议 `advisory_only=true`，有 provider、input/output、reviewer 和 review timestamp，可审计。
- 生成及 review 前后工单 version 不变，证明 AI 不会自动推进状态。
- 前端不加载历史 suggestions，人工复核结果刷新后可见性不足；建议持久化机制正常，使用体验部分实现。

## 12. 权限、安全、日志与审计

| 项目 | 状态 | 证据与风险 |
|---|---|---|
| 密码哈希 | 正常 | `backend/app/security.py` 使用 pwdlib recommended/Argon2 |
| JWT | 正常/部分 | 自实现 HS256 校验 iss/aud/jti/iat/exp、恒定时间签名比较；浏览器 token 存 sessionStorage |
| 服务令牌 | 正常 | 恒定时间比较，Action→Backend 实测 service actor |
| RBAC + 数据范围 | 正常 | `AuthorizationPolicy` + SQL scope；3 个越权动作和多次资源读取实测拒绝 |
| 状态机 | 正常 | 非法 pending→assign 409 |
| 乐观锁 | 正常 | stale version 409 `VERSION_CONFLICT` |
| 幂等 | 正常 | 同 key 重放同 ID，不重复建单 |
| 登录限流 | 部分正常 | 进程内内存计数、按 client host+username；多副本不共享，代理来源识别有限 |
| CORS | 正常 | 显式 allowlist、credentials=false；本轮预检 200 |
| 请求体限制 | 部分正常 | POST + Content-Length 生效，实测 413；chunked/非 POST 覆盖不足 |
| 文件校验 | 部分正常 | 类型/大小/hash/可见性存在；malware scanner disabled |
| 错误响应 | 正常/部分 | 统一 JSON error + request_id；OpenAPI 未完整声明非 2xx 响应 |
| 安全响应头 | 正常 | Nginx CSP/XFO/nosniff/referrer/permissions；附件下载 nosniff 实测 |
| 结构化日志 | 部分正常 | JSON stdout + request_id；无集中日志平台；redaction 对任意自由文本不是完整 DLP |
| 审计日志 | 正常 | 权限拒绝、敏感读取、状态动作真实落库 |
| 弱密钥保护 | 部分正常 | production validator 拒绝弱 secret/不安全对象存储；dev/test 有显式占位默认值 |
| 硬编码秘密 | 未发现真实秘密 | 源码/CI 只发现开发或测试固定值；未输出或检查本地 `.env` 秘密内容 |

生产校验位于 `backend/app/config.py`/启动逻辑：生产环境要求非弱 JWT/service secret、显式 CORS、HTTPS 对象存储，并要求 malware HTTP scanner clean。它能防止一部分错误配置，但不替代秘密管理服务。

静态扫描第一方运行目录没有发现 `TODO`/`FIXME`/`HACK` 标记；但 `.env.example`、`docker-compose.yml` 和 `backend/app/config.py` 明确含 `minioadmin`、`change-me`、development token 等开发默认值，`SERVICENOW_LOCAL_MODE` 默认 true。它们不是泄露的真实凭据，但若绕过 production validator 直接按开发模式暴露服务会形成风险。

## 13. Docker、迁移、测试、部署与恢复

### 13.1 本轮实际命令与结果

| 检查 | 结果 |
|---|---|
| `docker compose config --services` | 7 服务：frontend/backend/rasa/action_server/postgres/minio/duckling |
| `docker compose ps`（审计开始） | 7 服务全部 healthy |
| 实际 health/API/核心闭环 | 通过，见第 9 节 |
| 空库 `alembic upgrade head` | 通过，head=`0009` |
| `alembic downgrade 0008` 再 upgrade | 通过 |
| `alembic check` | **失败**，索引和 Identity/default 元数据漂移 |
| Seed 连续两次 | 通过，7 departments/4 users/0 tickets，无重复行 |
| Backend `pytest` | **32 passed in 12.60s** |
| Backend `compileall` | exit 0 |
| Ruff `E9,F63,F7,F82` | exit 0 |
| Actions public/store tests | **18 passed** |
| Actions HTTP gateway tests | **3 passed** |
| Frontend `npm run lint:types` | 通过 |
| Frontend `npm run build` | 通过；5538 modules，35.32s |
| Frontend 默认 `npm test -- --run` | **失败**：7 files passed/4 failed；13 tests passed/4 timeout；7 unhandled `window is not defined` |
| 诊断性 Vitest 20s timeout | 11 files/17 tests passed in 73.27s，但不能替代默认失败 |
| Rasa validate/core/nlu/overlap | **无法验证**：命令 424s 无输出并导致/伴随 Docker engine 无响应；未重复冒险执行 |
| Playwright 三浏览器 | **未运行/无法验证**：计划执行时 Docker engine 无响应；恢复后未启动端口会冲突的隔离栈 |
| PostgreSQL restore drill | **未运行/无法验证**：同上 |

前端默认失败文件为 TicketsPage、IntelligencePage、ChatPage、AftercarePage，均在默认 5 秒超时；测试结束后还有 7 个 jsdom `window is not defined` 未处理异常。增加 test/hook timeout 到 20 秒后通过，说明核心断言可完成，但默认门禁存在性能/清理问题。另有 NaN CSS height、Ant Design deprecated List/Alert、`getComputedStyle` pseudo-element 警告。构建产生约 523 kB 和 540 kB 的大 chunk 警告。

### 13.2 Rasa 离线检查导致的环境异常

本轮以一次批处理尝试 `rasa data validate`、`rasa test core`、`rasa test nlu` 和 overlap 检查，424 秒无输出超时；留下两个由本轮命令创建的 `docker compose run ... rasa test core` CLI 进程。只终止这两个进程后，`docker ps`、`docker version` 以及各宿主 health 端点仍持续超时。本轮没有重启 Docker Desktop。稍后引擎自行恢复，`docker compose ls --all` 显示 `tingting-assistant exited(7)`，七容器均 `Exited (255)`。执行一次 `docker compose up -d --wait` 后：

- frontend、backend、rasa、action_server、postgres、minio、duckling 七服务全部 healthy；
- frontend `/`、backend `/health/ready`、Rasa `/status`、Action `/health`、MinIO `/minio/health/live` 均返回 200；
- 没有重新执行会卡死的 Rasa 离线命令，也不把它、Playwright 或恢复演练写成通过。

服务最终恢复不消除稳定性问题：一次离线测试审计与引擎无响应、七容器同时退出有明显时间关联，但本轮没有足够证据证明因果根源。

### 13.3 脚本和 CI 漂移

1. `scripts/check-demo.ps1` 仍匹配 migration `0004` 并输出“six services”；当前为 0009/七服务，脚本已过期，直接运行会误报失败。
2. `scripts/run-e2e.ps1` 和 `scripts/run-e2e.sh` 把 frontend 写死为 18080；当前主栈 Duckling 正占宿主 18080。脚本也没有覆盖 MinIO 端口，和运行中的主栈并行会冲突。
3. `.github/workflows/ci.yml` 包含 static/frontend/backend/action/rasa/e2e/dependency-security/docker-integration，但 dependency security 为 `continue-on-error`，发现依赖漏洞也不会阻断 CI。
4. 旧发布报告的 0003、六服务、51/51 E2E 只是历史快照；当前脚本/代码已演进，不能用于本轮背书。

### 13.4 备份恢复

`scripts/backup-database.ps1`、`scripts/restore-database.ps1` 和 `backend/app/verify_restore.py` 存在，但只处理 PostgreSQL `pg_dump`/restore。MinIO bucket 和对象不在备份中；恢复 DB 可能得到附件元数据却缺失文件，`verify_restore` 也不逐个 stat 对象。这是上线前 P0/P1 级恢复闭环缺失。脚本面向当前数据库执行覆盖式恢复；本轮遵守 audit-only 边界，没有在主数据上做破坏性 restore drill。

## 14. 外部集成边界

运行时 `/api/v1/integrations/status` 返回八项 `configured=false`：OIDC、directory、work_order、sms、map、division、logging、monitoring。Map 与 SMS 调用分别得到 `MAP_NOT_CONFIGURED` 和 `SMS_NOT_CONFIGURED` 409。

| 能力 | 代码状态 | 当前运行态 | 审计标记 |
|---|---|---|---|
| OIDC | config/exchange 适配器 | disabled | 未接入 |
| 组织目录 | sync 适配器 | unconfigured | 未接入 |
| 政务/ServiceNow 工单 | generic adapter + legacy local action | generic unconfigured；legacy local mock | 未接入 + Mock |
| 短信 | adapter/status/send | unconfigured | 未接入 |
| 地图/地理编码 | adapter/status | unconfigured | 未接入 |
| 行政区划 | adapter/status | unconfigured | 未接入 |
| 集中日志 | 状态占位 | unconfigured | 占位/未接入 |
| 监控 | status/metrics 局部数据 | unconfigured | 占位/未接入 |
| AI provider | rules provider | configured as rules | 真实规则实现，不是真实大模型 |

## 15. 正常、部分实现、异常和未实现清单

### 15.1 已实际确认正常

- FastAPI/PostgreSQL 为工单状态真相源；Rasa 默认 HTTP Action 链不会自行维护业务状态。
- 四角色资源范围、动作权限、非法状态跳转、幂等键和 ticket/work-order 乐观锁。
- 核心建单、受理、派发、部门办理、结果提交、不满意重办、申诉审核、再次办理、确认办结。
- 工单/协同历史、反馈、申诉、通知、回访任务、AI 建议和审计落库。
- MinIO 上传、授权下载、可见性隔离、软删除与物理对象删除。
- JWT/Argon2/服务身份、CORS、request_id、统一错误、Nginx 安全头的核心实现。
- 空库迁移、单步降级/升级、Seed 内容幂等、Backend/Action 测试、TypeScript 和生产构建。

### 15.2 部分实现或占位

- Rasa：新建链真实，但 tracker 内存、裸 ID 查询失败，旧 ServiceNow 为 local Mock。
- AI：六类建议、持久化和复核真实，但只是规则 provider，前端不恢复历史建议。
- SLA：暂停/恢复/催办/临期/超期代码存在，无工作日历，临期通知没有后台调度。
- 回访：任务和人工记录真实，无自动外呼。
- 通知：站内真实，短信/微信/邮件/政务渠道未接入。
- 文件安全：元数据和权限完整，恶意文件扫描未启用。
- 管理：本地用户/部门/分类/审计存在，平台配置管理缺失。
- 日志/监控：JSON stdout 与本地 metrics 存在，没有集中日志、告警和真正监控系统。

### 15.3 异常、断链或失效

- 部门端显示无权调用的外部工单同步按钮，必得 403。
- Chat 文案承诺可输入工单号，但裸号被 NLU fallback。
- 默认 Vitest 4 个超时、7 个异步 teardown 异常。
- `alembic check` 报 ORM/migration 元数据漂移。
- `scripts/check-demo.ps1` 的 migration/服务数已过期。
- E2E 脚本默认端口与当前主栈冲突，缺少完整隔离。
- Rasa 离线测试卡住且 Docker engine 随后无响应、七容器退出；服务已恢复，但根因未确认。
- 备份只含 PostgreSQL，附件对象无法随库恢复。

### 15.4 未实现或未接入

- 可由管理员在 UI 中管理的平台运行配置。
- 真正的 LLM/RAG/向量相似检索或模型热点聚类。
- 持久化 Rasa tracker store。
- 可靠后台任务调度、通知 outbox/队列、自动临期扫描和自动外呼。
- 真实 OIDC、目录、政务工单、SMS、地图、区划、集中日志与监控。
- MinIO 对象备份/恢复与附件完整性恢复验证。
- 生产 TLS、集中秘密管理、多副本共享限流、高可用与灾备。

## 16. MVP 完成度、上线缺口与优先级

### 16.1 MVP 实际完成度

核心四角色业务、状态机、权限和持久化已经超过“静态原型”；可演示 MVP 约 82%。扣分主要来自 Rasa 稳定性、默认测试门禁、前端断链、SLA/通知调度、扫描器、外部集成和恢复不完整。生产就绪度约 55%，主要不是缺页面，而是缺可靠运行、恢复、安全外接和持续门禁。

### 16.2 上线前缺失能力与后续完善优先级

| 优先级 | 必须处理 | 验收证据 |
|---|---|---|
| P0 | 恢复 Docker/Rasa 稳定性，定位离线测试卡死；让默认 Vitest、Rasa validate/core/nlu、Playwright 稳定通过 | 默认命令连续通过，不能靠扩大 timeout 掩盖 |
| P0 | 修正 Alembic/ORM 元数据漂移，保护现有索引和 Identity | `alembic check` clean；空库/升级库双路径通过 |
| P0 | 建立 PostgreSQL + MinIO 一致备份、恢复和附件完整性校验 | 隔离环境完整 restore drill，逐对象校验 |
| P0 | 启用强秘密、TLS、生产对象存储 TLS、恶意文件扫描；验证生产 config guard | 生产等价环境启动与拒绝弱配置测试 |
| P1 | 修复部门同步按钮权限错配、Chat 裸工单号查询、AI 历史建议加载 | 浏览器按四角色 E2E 通过 |
| P1 | 将临期/超期扫描和通知投递移到可靠 scheduler/outbox；加入失败重试 | 时间推进与重试集成测试 |
| P1 | 持久化 Rasa tracker；明确匿名到登录用户的身份迁移策略 | Rasa 重启后会话/工单归属测试 |
| P1 | 修复 `check-demo` 和 E2E 端口隔离；消除默认测试 teardown 泄漏 | 一键脚本在主栈并行场景可重复执行 |
| P1 | 建立集中日志、指标、告警和 request_id 跨服务追踪 | 故障演练可由 request_id 定位全链路 |
| P2 | 若业务确需，再接 OIDC、目录、短信、地图、区划、政务工单 | 每个适配器使用真实沙箱凭据的契约测试 |
| P2 | 若产品确需，再引入真实 AI；保持 advisory-only 和人工复核 | 模型输出审计、提示词/版本、回放与安全评估 |
| P2 | 清理或隔离旧 Chatroom、ServiceNow local、`rasa.db` 等兼容资产 | 资产清单和无引用证明；不在本轮删除 |

## 17. 结论

项目的核心业务闭环、四角色权限和关键持久化是“代码存在且本轮真实运行验证”，不是 README 自述；AI 也是“真实落库的规则建议”，但绝不是已接入大模型。与此同时，默认前端门禁、迁移元数据、Rasa/Docker 稳定性、后台调度、附件扫描、对象备份和全部外部集成仍是明确缺口。

因此当前最准确的定位是：**可运行、可演示、核心闭环较完整的工程化 MVP；尚不是可直接上线的生产系统。** 在 P0 问题完成并用默认门禁、真实恢复演练和生产等价配置重新验证前，不应使用“生产就绪”“全部测试通过”“完整外部集成”等表述。

## 附录 A：关键证据文件

- 架构/Compose：`docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf.template`
- Backend 入口/中间件：`backend/app/main.py`、`backend/app/config.py`、`backend/app/rate_limit.py`
- 认证/权限：`backend/app/security.py`、`backend/app/api/dependencies.py`、`backend/app/authorization.py`
- 工单/协同：`backend/app/api/tickets.py`、`backend/app/services/ticket_service.py`、`backend/app/services/work_order_service.py`、`backend/app/models.py`
- 附件：`backend/app/api/attachments.py`、`backend/app/services/attachment_service.py`、`backend/app/storage.py`
- 通知/回访/申诉：`backend/app/api/notifications.py`、`backend/app/api/aftercare.py`、`backend/app/services/aftercare_service.py`
- AI/集成：`backend/app/api/ai.py`、`backend/app/services/ai_service.py`、`backend/app/repositories/ai.py`、`backend/app/api/integrations.py`
- 审计/日志：`backend/app/repositories/identity.py`、`backend/app/logging_config.py`、`backend/app/api/analytics.py`
- 数据库：`backend/migrations/versions/`、`backend/app/seed.py`
- 前端路由/API/页面：`frontend/src/routes/AppRoutes.tsx`、`frontend/src/layouts/WorkspaceLayout.tsx`、`frontend/src/api/`、`frontend/src/pages/`
- Rasa/Actions：`domain.yml`、`data/`、`endpoints.yml`、`actions/actions.py`、`actions/ticket_store.py`
- 测试/CI/脚本：`backend/tests/`、`actions/tests/`、`frontend/src/**/*.test.tsx`、`tests/e2e/`、`.github/workflows/ci.yml`、`scripts/`

## 附录 B：未验证声明

以下项目本轮没有足够证据，必须保持 `U`：

1. Rasa data validate、Core、NLU 和 overlap 的当前通过情况。
2. Playwright Chromium/Firefox/WebKit 的当前通过情况。
3. 当前脚本的 PostgreSQL restore 成功性，以及 PostgreSQL/MinIO 联合恢复（后者脚本本身未实现）。
4. 真实 OIDC、目录、政务工单、SMS、地图、区划、集中日志和监控服务。
5. 多实例 backend 下的限流、并发锁、高可用和故障切换。
6. 生产容量、长时间稳定性、灾备 RPO/RTO 和安全渗透测试。
