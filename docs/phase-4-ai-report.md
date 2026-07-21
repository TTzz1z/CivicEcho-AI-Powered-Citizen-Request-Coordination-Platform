# 阶段四：AI 与求职展示 — 集成与验证报告

> 日期：2026-07-19  
> 范围：接入 DeepSeek（OpenAI 兼容）真实大模型，保留规则降级；固定演示剧本；隔离旧资产；文档对齐。

## 1. AI 接入架构

```text
IntelligencePage / Chat
        │  POST /api/v1/ai/tickets/{id}/analyze
        ▼
AiService.analyze()
   ├─ suggestion_type ∈ {summary, document_draft, risk, assignment}
   │        └─ LlmClient.complete()  ──►  DeepSeek /chat/completions
   │                 │ 成功            （OpenAI 兼容, response_format=json_object）
   │                 ▼
   │            provider=deepseek, 记录 model / prompt_version / latency_ms
   │                 │ 失败 / 无密钥 / 超时
   │                 ▼  降级
   └─ 规则引擎 builders[type]()  ──►  provider=rules
        ▼
   写入 ai_suggestions（advisory_only=true，与工单状态/版本解耦）
        ▼
   审计 generate_ai_suggestion（provider, model, prompt_version, latency_ms）
```

关键文件：

- `backend/app/llm_client.py`：OpenAI 兼容客户端，system prompt + 每类型 prompt，强制 JSON、markdown 兼容解析、`PROMPT_VERSION`、耗时统计。
- `backend/app/services/ai_service.py`：LLM 优先、规则降级；`_llm_context()` 组装上下文；审计记录 provider/model/prompt_version/latency。
- `backend/app/config.py`：`ai_provider`（rules|deepseek）、`ai_api_key`、`ai_base_url`、`ai_model`、`ai_timeout_seconds`、`ai_max_tokens`；生产 guard 允许 deepseek。
- `backend/tests/conftest.py`：强制单元测试用规则引擎，保持确定性、零网络请求。

## 2. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `AI_PROVIDER` | `rules` | `deepseek` 启用大模型；`rules` 纯离线 |
| `AI_API_KEY` | 空 | 留空即降级规则引擎 |
| `AI_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `AI_MODEL` | `deepseek-chat` | 可改为其他 DeepSeek 模型，无需改代码 |
| `AI_TIMEOUT_SECONDS` | `30` | 超时即降级 |
| `AI_MAX_TOKENS` | `1024` | 单次输出上限 |

`.env`、`.env.example`、`.env.prod.example`、`docker-compose.yml` 均已透出以上变量。

## 3. 验证证据

| 检查项 | 结果 |
|---|---|
| 真实 DeepSeek 调用 | 成功；燃气泄漏正确识别为 `urgent`，延迟 1691ms |
| 端到端工单建议 | `QT2026071900000375` 摘要+风险经 DeepSeek 生成，`provider=deepseek`、`model=deepseek-chat` 落库 |
| AI 边界 | 生成建议后工单状态仍 `pending`、`version=1`，AI 未改变业务状态 |
| 无密钥降级 | `AI_API_KEY` 留空 → `available=False` → `provider=rules` |
| Backend pytest | 34 passed；AI 测试经 conftest 用规则引擎稳定通过 |
| alembic check | clean |
| Frontend Vitest | 11 files, 17 tests, 0 errors |
| 8 服务 | 全部 healthy |

## 4. 阶段四验收对照

- **无模型密钥时仍可完整演示** — 降级路径验证通过（provider=rules）。
- **AI 不改变业务状态** — 工单状态/版本未变，`advisory_only=true`。
- **输出可追溯、可复核、可回放** — provider/model/prompt_version/latency 全量记录 + 人工复核接口 `POST /ai/suggestions/{id}/review`。
- **10 分钟内稳定演示主闭环和申诉流程** — 见 `docs/demo-script.md` 三条固定剧本。

## 5. 资产隔离

- 旧 Chatroom 资产 `Dockerfile.chatroom`、`chatroom_handoff.html` 迁移至 `legacy/`，附 `legacy/README.md` 说明其不参与当前 8 服务链路。
- ServiceNow local（`actions/snow.py`、`actions/snow_credentials.yml`）保留为默认关闭的预留集成，已在 `legacy/README.md` 标注状态。

## 6. 已知边界

- DeepSeek 官方模型线无 “v4 flash” 名称；当前使用标准 `deepseek-chat`，实测调用成功。切换模型只需改 `AI_MODEL`。
- `similarity`、`completeness`、`hotspots` 仍由规则引擎实现（依赖 PostgreSQL 全文与 trigram 更合适，未引入独立向量库，符合升级计划边界）。
- 单元测试刻意不触发真实 LLM，避免网络依赖与不确定性；真实调用通过手动/演示验证。
