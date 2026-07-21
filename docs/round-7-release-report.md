# 第七轮 V1.0 发布报告

测试日期：2026-07-14（Asia/Shanghai）  
目标版本：`v1.0.0`  
Git 操作：仅准备清单，未提交、未打 Tag；当前交付目录不含 `.git` 元数据。

## 封版摘要

- 六服务镜像使用明确标签并固定 OCI digest；Rasa 仍为 3.0.13，未升级。
- Backend 直接依赖与完整生产依赖锁定；前端 manifest 与 `package-lock.json` 对齐为精确版本。
- Rasa 模型固定为 `models/tingting-v1.0.0.tar.gz`，Compose 不再依赖“目录中最新模型”的隐式选择。
- `.gitignore` 仅放行该 V1.0 模型，继续排除旧模型、测试结果、本地缓存、数据库、备份与秘密文件。
- Starlette 兼容升级保留为 FastAPI 0.139.0 + Starlette 1.3.1。
- 删除两个确认无引用的旧中文 response；英文 Helpdesk、ServiceNow、handoff 与动态表单提示全部保留。
- 新增一键演示检查和五份求职展示/发布文档。

V1.0 Rasa 制品大小为 47,250,424 bytes，SHA-256 为 `12c3e0ecef207db77c0b7e1731ba1ba22147191dbacc56386e5266a4d1cbc27d`；归档完整性检查通过（48 members），运行中 `/status` 返回固定文件名。

## Starlette 安全兼容结论

升级前版本为 Starlette 0.41.3。截至 2026-07-14，GitHub Advisory Database 返回 6 项匹配公告：

| 公告 | 影响 | 项目升级前实际暴露 | 修复版本 |
|---|---|---|---|
| [CVE-2025-54121](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) | multipart 大文件阻塞 | 未使用 UploadFile/multipart；Nginx 限制 1 MiB | 0.47.2 |
| [CVE-2025-62727](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) | FileResponse Range 二次复杂度 DoS | Backend 未使用 FileResponse/StaticFiles | 0.49.1 |
| [CVE-2026-48710](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) | 恶意 Host 污染 `request.url.path` | 鉴权不依赖 URL path；Nginx 重写 Host，但仍升级 | 1.0.1 |
| [CVE-2026-48817](https://github.com/advisories/GHSA-x746-7m8f-x49c) | HTTPEndpoint 任意属性分派 | 项目只用 FastAPI 函数路由 | 1.1.0 |
| [CVE-2026-48818](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) | Windows StaticFiles UNC SSRF/NTLM 泄露 | Backend 在 Linux 容器且未用 StaticFiles | 1.1.0 |
| [CVE-2026-54283](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) | urlencoded form 限制失效 DoS | 只接 JSON，未调用 `request.form()`；有 1 MiB 限制 | 1.3.1 |

代码调用点审计说明升级前六项均没有可直接触发的业务路径，但这不是长期豁免理由。FastAPI 0.115.6 对 Starlette 有 `<0.42.0` 约束，因此两者一起升级。Backend 18/18 首轮兼容测试通过，最终全量结果见下表。

## Rasa 警告处理

删除：

- `utter_public_request_help`
- `utter_public_request_out_of_scope`

二者只存在于 `domain.yml`，没有故事、规则、表单自动命名、Action 动态模板或测试引用。

保留警告分三类：

- `handoff`、`trigger_handoff`：跨 Bot/按钮 payload，不应伪造 NLU 样本来压警告；
- `inform`：旧 Helpdesk 表单内通用输入，静态故事校验无法完整识别；
- `utter_ask_*` 与 Helpdesk/handoff 响应：由 Rasa 表单命名约定或 Action `template=` 动态调用。

TensorFlow、Pillow 等 DeprecationWarning 来自锁定的 Rasa 3.0.13 依赖树。本轮按约束不升级 Rasa，不用屏蔽警告伪装成修复。

## 回归结果

| 门禁 | 结果 |
|---|---|
| Python compile / Ruff | 通过 |
| Backend pytest | 18/18 通过（Starlette 1.3.1） |
| Actions unittest | 21/21 通过 |
| Rasa data validate | 通过；仅保留已解释动态/兼容警告 |
| Rasa Core | stories 24/24，actions 113/113，accuracy 1.0 |
| Rasa NLU | 31 条，30 条正确，accuracy 0.9677；1 条投诉/求助语义边界误判已记录 |
| TypeScript | 通过 |
| Vitest | 8/8 通过 |
| Vite production build | 通过 |
| Playwright Chromium / Firefox / WebKit | 17/17 + 17/17 + 17/17，合计 51/51 通过 |
| Docker Compose / Alembic / 集成 | config 通过；0003 head；真实闭环到 closed；六服务 healthy |
| Backend Python dependency audit | 0 known vulnerabilities；Starlette 公告清零 |
| Frontend production dependency audit | 0 vulnerabilities |
| 一键演示检查 | 8/8 通过 |

NLU 唯一错误样本为“昨晚工地施工到凌晨，孩子没法睡觉”，标注 `submit_complaint`、预测 `request_help`。这是投诉与现实困难求助的真实语义边界；本轮不为单一样本冒险改动已稳定的训练集，已保留到后续误差分析。

## 已知限制

- 单机 Compose，不提供多机高可用、自动扩缩容或零停机发布。
- Rasa 3.0.13 与 Python 3.8 依赖树较旧，保留上游弃用告警；主版本迁移尚未实施。
- 登录限流是 Backend 进程内实现，多实例前需迁移到共享限流或网关。
- 默认 tracker 与对话并发能力适合演示；E2E 有意使用单 worker 避免共享 sender 串扰。
- 默认 ServiceNow 本地模式，未接真实政务、短信、邮件、附件或组织 SSO。
- 日志输出到容器 stdout 和数据库审计表，尚未接集中日志与告警平台。
- `Dockerfile.chatroom` 是未参与六服务 Compose 的历史参考资产，保留其 Node 14 构建方式，不属于 V1.0 发布制品。

## Git 提交与 Tag 建议

建议在恢复/初始化 Git 元数据后先审核秘密和生成物，再分三次提交：

1. `chore(release): pin v1.0 dependencies images and rasa model`
2. `chore(quality): add demo preflight and compatibility regression`
3. `docs(release): add v1.0 portfolio and release materials`

候选 Tag：`v1.0.0`，建议使用 annotated tag，并只在干净工作树、CI 全绿和演示检查 8/8 后创建：

```bash
git status --short --ignored
git add -A
git status --short
# 确认 .env、backups、results、缓存和本地数据库没有进入暂存区；确认 V1.0 模型已进入暂存区
git tag -a v1.0.0 -m "Tingting Assistant V1.0"
```
