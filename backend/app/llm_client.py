"""OpenAI-compatible LLM client for DeepSeek integration with graceful fallback.

Round 2 changes:
- LlmResult now carries prompt_tokens / completion_tokens / total_tokens / usage_unavailable
  parsed from the model response `usage` block. Tokens are NEVER hardcoded to 0
  when the model actually returned a usage block; if the block is absent,
  usage_unavailable=True is recorded honestly (no fabrication).
- New `complete_raw()` method returns the full raw response so callers that
  need the original content (e.g. orchestrator's policy/service-guide prompts
  that don't ask for JSON) can still benefit from usage parsing.
- All HTTP calls go through a single `_post_chat()` helper so prompt version,
  timeout and auth header stay consistent.
"""
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import get_settings

logger = logging.getLogger(__name__)

PROMPT_VERSION = "phase4-deepseek-v1"

SYSTEM_PROMPT = """你是倾听助手 AI 辅助研判引擎，服务于政务诉求受理与协同办理场景。你只生成建议供人工参考，绝不做出行政决定。
输出必须是合法 JSON，不要包含 markdown 代码块标记。
所有建议必须标注 advisory_only=true。
要求：
- 建议必须具体、可操作，指明具体部门、具体步骤、具体时限
- 结合工单的类型、地点、分类等信息给出针对性分析
- 避免笼统、模板化的表述"""

PROMPTS = {
    "summary": """请为以下政务工单生成结构化摘要，包含核心问题、影响范围、紧迫程度判断。
输出 JSON: {"summary": "不超过100字的精准摘要", "location": "事发地点", "impact": "影响范围和受影响人群", "urgency_hint": "紧迫程度判断（如：影响居民基本生活/存在安全隐患/一般性诉求）", "editable": true, "advisory_only": true}

工单信息：
- 类型：{request_type}
- 描述：{description}
- 地点：{location}
- 时间：{occurred_at_text}
- 优先级：{priority}
- 分类：{category_name}""",

    "document_draft": """请为以下政务工单生成处理答复草稿。草稿必须标注需要人工核实的地方。
输出 JSON: {"title": "关于...的处理答复", "body": "完整答复正文（包含事实确认、处理措施、时限承诺、联系方式）", "requires_fact_check": true, "prohibited_use": "不得未经人工核实直接作为办结、拒绝或其他行政决定文书发送", "advisory_only": true}

工单信息：
- 工单号：{ticket_id}
- 描述：{description}
- 地点：{location}
- 处理摘要：{resolution_summary}
- 处理措施：{resolution_measures}
- 公开回复：{public_reply}
- 责任部门：{departments}""",

    "risk": """请分析以下政务工单的风险等级，并给出具体的处置建议。
评估维度：是否涉及人身安全、是否影响群体利益、是否有升级趋势、是否需要多部门联动。
输出 JSON: {"level": "urgent|sensitive|none", "matched_signals": ["具体风险信号"], "recommendation": "具体处置建议（包含应联系的具体部门、建议时限、注意事项）", "suggested_departments": ["建议联系的部门"], "time_limit_hint": "建议处理时限", "automatic_decision": false, "advisory_only": true}

工单信息：
- 描述：{description}
- 事件：{event}
- 地点：{location}
- 优先级：{priority}
- 类型：{request_type}
- 可选部门：{departments}""",

    "assignment": """请根据工单信息建议最合适的责任部门，并说明推荐理由。
输出 JSON: {"recommended_departments": [{"department_name": "部门名", "reason": "推荐理由（结合职责范围和工单内容）", "confidence": "high|medium|low"}], "dispatch_hint": "派发建议（如是否需要协办、注意事项）", "requires_human_confirmation": true, "advisory_only": true}

工单信息：
- 描述：{description}
- 类型：{request_type}
- 地点：{location}
- 分类：{category_name}
- 可选部门：{departments}""",

    "pre_review": """请分析以下市民诉求描述，提取结构化信息并生成规范化描述。
要求：
1. identified_type 必须是投诉、建议、咨询或求助之一
2. 从描述中提取地点、时间、涉及对象，提取不到则填"未提供"
3. impact 说明影响范围和受影响人群
4. urgency_hint 必须是：影响居民基本生活 / 存在安全隐患 / 一般性诉求 之一
5. normalized_description 用正式、清晰的语言重写诉求（不超过200字），保留关键事实
输出 JSON: {"identified_type": "...", "identified_location": "...", "identified_time": "...", "identified_target": "...", "impact": "...", "urgency_hint": "...", "normalized_description": "...", "advisory_only": true}

市民描述：{description}
已知信息：
- 类型：{request_type}
- 地点：{location}
- 时间：{occurred_at_text}
- 对象：{target}""",
}


@dataclass
class LlmUsage:
    """Token usage parsed from the model response `usage` block.

    `unavailable=True` means the response did not include a usage block.
    Callers MUST record this honestly rather than fabricating zero tokens.
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    unavailable: bool = False


@dataclass
class LlmResult:
    """Result of an LLM call. Carries parsed JSON (when applicable), the raw
    content, model metadata, latency and token usage."""
    success: bool
    data: dict | None
    model: str
    content: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0
    usage: LlmUsage = None  # type: ignore[assignment]
    error: str | None = None
    error_code: str | None = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = LlmUsage(unavailable=True)


def _parse_usage(usage_block: dict | None) -> LlmUsage:
    """Parse the OpenAI-style `usage` block. Returns unavailable=True if absent."""
    if not usage_block or not isinstance(usage_block, dict):
        return LlmUsage(unavailable=True)
    try:
        prompt = int(usage_block.get("prompt_tokens", 0) or 0)
        completion = int(usage_block.get("completion_tokens", 0) or 0)
        total = int(usage_block.get("total_tokens", prompt + completion) or 0)
        # If all three are 0 and the block exists, treat as unavailable
        if prompt == 0 and completion == 0 and total == 0:
            return LlmUsage(unavailable=True)
        return LlmUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total or (prompt + completion),
        )
    except (TypeError, ValueError):
        return LlmUsage(unavailable=True)


def _strip_code_fence(content: str) -> str:
    content = (content or "").strip()
    if content.startswith("```"):
        # strip opening fence line and trailing ```
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]
    return content.strip()


class LlmClient:
    """Calls DeepSeek (OpenAI-compatible) chat completions API."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url.rstrip("/")
        self.model = settings.ai_model
        self.timeout = settings.ai_timeout_seconds
        self.max_tokens = settings.ai_max_tokens

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def provider(self) -> str:
        """Short provider label derived from base_url, for ai_usage_logs.provider."""
        host = (self.base_url or "").lower()
        if "deepseek" in host:
            return "deepseek"
        if "siliconflow" in host:
            return "silicon_flow"
        if "openai.com" in host:
            return "openai"
        if "volcengine" in host or "ark.cn-beijing" in host:
            return "volcengine"
        return host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0][:60] or "unknown"

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def complete(self, suggestion_type: str, context: dict) -> LlmResult:
        """Generate a JSON suggestion using the LLM. Returns LlmResult with parsed JSON."""
        if not self.available:
            return LlmResult(success=False, data=None, model="rules", error="no_api_key", error_code="no_api_key")

        prompt_template = PROMPTS.get(suggestion_type)
        if not prompt_template:
            return LlmResult(success=False, data=None, model=self.model,
                             error=f"no prompt for {suggestion_type}", error_code="no_prompt")

        try:
            user_prompt = _render(prompt_template, context)
        except (KeyError, ValueError) as exc:
            return LlmResult(success=False, data=None, model=self.model,
                             error=f"prompt format error: {exc}", error_code="prompt_format_error")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return self._post_chat(
            messages=messages,
            temperature=0.3,
            max_tokens=self.max_tokens,
            json_mode=True,
            capability=suggestion_type,
        )

    def complete_raw(self, *, system: str, user: str, temperature: float = 0.3,
                     max_tokens: int | None = None, json_mode: bool = False,
                     capability: str = "raw") -> LlmResult:
        """Call the LLM with arbitrary prompts. Returns the raw content (no JSON parsing).

        Used by orchestrator (intent classification, ticket draft extraction,
        service guide) and kb_service (RAG answer generation) so all LLM calls
        go through one helper and uniformly parse usage.
        """
        if not self.available:
            return LlmResult(success=False, data=None, model="rules",
                             error="no_api_key", error_code="no_api_key")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self._post_chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or self.max_tokens,
            json_mode=json_mode,
            capability=capability,
        )

    # ----------------------------------------------------------------
    # Internal helper — single HTTP path for all chat completions
    # ----------------------------------------------------------------

    def _post_chat(self, *, messages: list[dict], temperature: float,
                   max_tokens: int, json_mode: bool,
                   capability: str) -> LlmResult:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            err_msg = f"HTTP {exc.code}: {exc.reason}"
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:400]
                err_msg = f"{err_msg} | {err_body}"
            except Exception:
                pass
            logger.warning("LLM HTTP error for %s: %s", capability, err_msg)
            return LlmResult(
                success=False, data=None, model=self.model, latency_ms=latency_ms,
                error=err_msg[:500], error_code=f"http_{exc.code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("LLM network error for %s: %s", capability, exc)
            return LlmResult(
                success=False, data=None, model=self.model, latency_ms=latency_ms,
                error=str(exc)[:500], error_code=type(exc).__name__,
            )

        # Parse content + usage
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("LLM response missing choices for %s: %s", capability, str(result)[:300])
            return LlmResult(
                success=False, data=None, model=self.model, latency_ms=latency_ms,
                error="malformed_response", error_code="malformed_response",
                usage=_parse_usage(result.get("usage")),
            )

        content = content or ""
        usage = _parse_usage(result.get("usage"))

        # Try JSON parsing when json_mode was requested; otherwise keep raw content
        data: dict | None = None
        if json_mode:
            stripped = _strip_code_fence(content)
            try:
                data = json.loads(stripped)
                if isinstance(data, dict):
                    data["advisory_only"] = True
            except json.JSONDecodeError:
                logger.warning("LLM JSON parse failed for %s: %s", capability, stripped[:200])
                # Return success=False for JSON-mode calls that didn't yield valid JSON
                return LlmResult(
                    success=False, data=None, model=self.model, content=content,
                    latency_ms=latency_ms, error="json_decode_error",
                    error_code="json_decode_error", usage=usage,
                )
        return LlmResult(
            success=True, data=data, model=self.model, content=content,
            latency_ms=latency_ms, usage=usage,
        )


class _SafeDict(dict):
    """Returns placeholder for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return f"{{{key}}}"


def _render(template: str, context: dict) -> str:
    """Substitute {key} placeholders without touching literal JSON braces."""
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


_client: LlmClient | None = None


def get_llm_client() -> LlmClient:
    global _client
    if _client is None:
        _client = LlmClient()
    return _client


def reset_llm_client_for_tests() -> None:
    """Reset the singleton. For tests only."""
    global _client
    _client = LlmClient()
