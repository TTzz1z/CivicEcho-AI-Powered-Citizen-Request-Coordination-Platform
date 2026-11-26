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

CivicEcho v2 uses the FastAPI Orchestrator for conversations and the ticket API
for submission, work-order collaboration, and review. The attribution above
records the project's origins.

## Runtime dependencies

Third-party libraries are declared in:

- `backend/requirements.txt` / `backend/requirements.lock.txt`
- `frontend/package.json` / `frontend/package-lock.json`
- Docker base images referenced by Compose / Dockerfiles

Their respective licenses apply to those components.
