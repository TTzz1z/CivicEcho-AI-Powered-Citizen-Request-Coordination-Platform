# Third-Party Notices

CivicEcho / 倾听助手（本仓库）基于 Apache License 2.0 发布。

## Project copyright

Copyright 2026 CivicEcho / Tingting Assistant contributors.

本仓库当前产品代码、中文政务领域扩展、FastAPI 工单后端、React 工作台、Orchestrator/RAG、
知识库、审计与 Docker 编排由项目作者扩展与维护。

## Upstream attribution

This repository historically derived structure and some conversation assets from the
Rasa Helpdesk Assistant example:

Copyright 2020 Rasa Technologies GmbH

Licensed under the Apache License, Version 2.0.
See the root `LICENSE` file for the full Apache 2.0 text.

Remaining Rasa / ServiceNow Helpdesk paths (for example legacy `open_incident_form`
actions) are compatibility residues and are not the official CivicEcho ticket path.
The official ticket lifecycle is Orchestrator draft → FastAPI `/api/v1/tickets` →
WorkOrder collaboration → `/review-resolve`.

## Runtime dependencies

Third-party libraries are declared in:

- `backend/requirements.txt` / `backend/requirements.lock.txt`
- `frontend/package.json` / `frontend/package-lock.json`
- `actions/requirements-actions.txt`
- Docker base images referenced by Compose / Dockerfiles

Their respective licenses apply to those components.
