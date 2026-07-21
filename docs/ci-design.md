# CI 设计

唯一有效工作流是 `.github/workflows/ci.yml`；三份使用 Python 3.6/3.7、过时 checkout 和浮动 Rasa Action 的旧工作流已删除。

| Job | 内容 |
|---|---|
| static-checks | Python 3.11 compileall、固定 ruff 0.8.6 严重错误检查 |
| backend-tests | PostgreSQL 16 service、Alembic、全部 Backend/PostgreSQL 测试 |
| action-tests | 构建固定 Rasa SDK 3.6.2 镜像，运行两组 unittest |
| rasa-regression | 数据校验、固定 round3 模型 Core 回归 |
| docker-integration | 仅 main push：五服务启动、种子、完整流转脚本 |

Compose 所需密码/Token 只使用 CI 临时示例值，不打印 Token。Backend/Action 依赖版本固定；Rasa Core/SDK 固定为 3.6 系列并使用已训练的 v1.1.0 模型。`make ci-*` 与 `scripts/docker_round4_integration.py` 提供本地复现路径。

本地已执行与这些 Job 等价的检查；由于本目录不是 Git 工作树且未 push，GitHub 托管 runner 尚未实际执行，不能宣称远端 CI 已通过。
