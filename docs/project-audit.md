# 项目审查

> 本文主体记录第一轮接管基线。第二轮已完成中文政务最小闭环；当前实现和测试结果以 [中文领域设计](chinese-domain-design.md)、[诉求流程](public-request-flow.md) 和 [第二轮测试报告](round-2-test-report.md) 为准。

审查日期：2026-07-13。结论基于仓库实际文件、容器运行结果和生成的测试报告，不仅依据原 README。

## 基线与兼容性

| 项目 | 事实 |
|---|---|
| Rasa | 固定为 3.6.20，搭配重新训练的 v1.1.0 模型 |
| Rasa SDK | 3.6.2，与 Action 镜像一致 |
| 模型格式 | `domain/config/data/tests` 均为 3.0；测试文件由 legacy 2.0 安全调整为 3.0 |
| Python | Docker 已验证 3.8.10；本机默认 3.14.6，不兼容旧 TensorFlow 2.6 |
| 策略 | AugmentedMemoizationPolicy + TEDPolicy + RulePolicy |
| NLU | 英文 Whitespace/CountVectors/DIET，Duckling 只提取 email |

Windows 原始安装的首个确定错误是 `psycopg2-binary 2.9.10` 缺少 cp38 Windows wheel，源码构建要求 `pg_config`。已用 `constraints-legacy.txt` 固定 2.9.9。后续 PyPI 大包下载长期停滞，所以本地 `.venv` 未完成安装，不能标记为成功。

## 对话资产盘点

- Domain 有 17 个 intent；NLU 有 14 组训练样本。`restart` 为控制意图，`handoff` 和 `trigger_handoff` 主要由结构化 payload 触发，没有普通 NLU 样本。
- 实体：`email`、`priority`、`handoff_to`。
- 槽位：`confirm`、`previous_email`、`caller_id`、`email`、`incident_title`、`priority`、`problem_description`、`requested_slot`、`handoff_to`。
- 表单：`open_incident_form`（邮箱、优先级、描述、标题、确认）和 `incident_status_form`（邮箱）。
- 第一轮审查时可训练业务意图只有英文 IT Helpdesk；第二轮已增量加入中文投诉、建议、咨询、求助和状态查询数据，legacy 意图仍保留。
- Stories 覆盖表单打断、表单切换、问候/帮助/感谢/超范围；Rules 负责表单开始/提交、fallback 和 bot challenge；handoff 单独保存在 `data/handoff.yml`。

## 工单创建与查询

创建流程：

1. `open_incident/password_reset/problem_email` 触发 `open_incident_form`。
2. `action_ask_email` 可询问是否复用 `previous_email`。
3. `validate_open_incident_form` 校验邮箱和优先级。
4. 用户确认后调用 `action_open_incident`。
5. local mode 只回显拟创建内容；真实模式调用 ServiceNow Table API 创建 `incident`。
6. Action 结束后清空槽位，只保留 `previous_email`。

查询流程：`incident_status` → `incident_status_form` → 收集/复用邮箱 → `action_check_incident_status` → 按邮箱查用户 `sys_id` → 查询其 incidents → 映射状态文本。

## ServiceNow 与 Action Server

- `actions/snow.py` 使用 Basic Auth 调用 `https://<instance>/api/now/table/sys_user` 和 `/table/incident`。
- 配置现优先读取 `SERVICENOW_*` 环境变量，legacy `snow_credentials.yml` 只作后备；默认 local mode 为 true。
- Rasa 根据 `endpoints.yml` 调用 Action Server `/webhook`；Action Server 注册 `actions/actions.py` 和 `actions/handoff.py` 中的 Action。
- 本轮补充了 10 秒默认超时、2xx 判断、RequestException/非法 JSON 处理，以及 ServiceNow 非列表响应保护。
- 未连接真实 ServiceNow，因此真实鉴权、字段 ACL、限流、重试和幂等性均未验证。

## 实际验证结果

| 检查 | 结果 |
|---|---|
| Docker / Compose | Docker 29.6.1、Compose v5.3.0，服务端可用 |
| `rasa data validate` | 成功，退出码 0；存在数据警告 |
| `rasa train` | 成功，约 154 秒；生成 `models/helpdesk-baseline.tar.gz` |
| `rasa test --fail-on-prediction-errors` | 成功，12/12 对话、50/50 Action 预测正确；intent accuracy 0.9977 |
| 裸 SDK Action 导入 | 失败：官方 SDK 镜像不含 `ruamel`；专用 Action 镜像构建、健康检查和实际 Action 调用均成功 |
| Duckling | 首次裸容器测试连接拒绝；Compose 回归时服务在线，连接错误消失 |
| Rasa / Action 服务 | 第一轮 `/status` 与 `/health` 成功；第二轮当前加载 `tingting-round2-final.tar.gz` |
| REST smoke test | local mode 建单与状态查询均完成，Rasa → Action Server 链路成功 |
| 真实 ServiceNow | 未执行（默认 local mode） |

测试精度来自训练集和少量端到端样本，不能代表中文政务场景效果。

## 可复用模块

- Rasa Form 的必填信息补全、确认和取消模式。
- `previous_email` 的会话内复用思路，可迁移为联系人/证件信息确认。
- RulePolicy + TEDPolicy 混合管理和表单打断/切换 stories。
- Custom Action → 外部工单 API 的适配层边界。
- local mode，可演进为确定性的 mock ticket repository。
- REST channel、Action Server 独立部署边界。

## 风险与处置

| 级别 | 风险 | 当前处置 |
|---|---|---|
| 中 | Sanic-Cors 的上游 CVE 尚无修复版本 | Action Server 仅绑定回环地址，CI 显式追踪该例外 |
| 高 | 旧 ServiceNow 实现曾把所有 `>=200` 状态当成功，且无通用异常/超时保护 | 本轮已做最小修复；下一轮补单元测试和幂等键 |
| 高 | 无中文政务 NLU、无数据规范、无隐私分级 | 下一轮先定义最小中文垂直切片和脱敏规则 |
| 中 | `yes thanks` 同时属于 `affirm`/`thank`；handoff intent 无 NLU 样本 | 保留警告，下一轮按数据验收标准修复 |
| 中 | 测试集小且大部分与训练样本接近 | 已将格式迁移到 3.0；后续增加独立中文 E2E/Action 单测 |
| 中 | 第一轮 local mode 查询随机返回状态，不利于可重复测试 | 第二轮中文工单改为确定性内存 Mock，legacy local mode 也固定为 awaiting triage |
| 中 | `rasa.db` 位于源码快照且未被当前 endpoints 引用 | 已加入忽略；迁移时确认无保留价值后再清理 |
| 中 | legacy handoff 依赖旧 Chatroom fork；Dockerfile 使用 Node 14 | 默认关闭目标，保留参考，不作为新前端基线 |
| 中 | 原 GitHub Actions 使用过时 actions、Python 3.6/3.7 和 Rasa `main` actions | 不在本轮启用；迁移后重建固定版本 CI |
| 低 | 原 README 引用不存在的 `.md` 数据路径、Dockerfile 和 Rasa X 工作流 | README 已按当前事实重写 |
