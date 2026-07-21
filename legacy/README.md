# Legacy / 已隔离的历史资产

本目录存放**不参与当前 8 服务 Docker Compose 主链路**的历史兼容资产，仅作参考，不属于 V1.x 交付制品。

## 清单

| 资产 | 来源 | 现状 |
|---|---|---|
| `Dockerfile.chatroom` | RasaHQ 官方 Chatroom fork 的 Node 14 构建 | 未被任何 compose 引用；当前前端为 `frontend/`（React 19 + Nginx） |
| `chatroom_handoff.html` | 旧 Rasa Chatroom 挂载页 | 直连 `localhost:5005`，绕过后端鉴权/状态机，仅历史演示用 |

## 为什么隔离而不是删除

- 保留 Rasa 原生 handoff 能力的历史脉络，便于回溯 `domain.yml` 中 `utter_wouldve_handed_off` 等兼容 utterance 的来源；
- 阶段四要求“隔离无引用的旧 Chatroom、ServiceNow local 和陈旧资产”，而非删除。

## 与当前系统的关系

当前对话入口是 `frontend/src/pages/ChatPage.tsx`（经 Nginx/Caddy 反代到 Rasa REST webhook），所有工单状态、权限、审计均由 FastAPI 后端在 PostgreSQL 事务中完成。上述 Chatroom 资产**不再使用**。

## ServiceNow local 说明

`actions/snow.py`、`actions/snow_credentials.yml` 为 ServiceNow 兼容适配器，默认 `SERVICENOW_LOCAL_MODE=true` 走本地桩，不发起真实外呼。它们仍被 Action 层保留为“可选、默认关闭”的预留集成，不在本目录隔离，但同样不参与真实政务链路。
