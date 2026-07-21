"""Unified AI usage recorder for Round 2.

Single write path for `ai_usage_logs` rows covering all 10 capabilities:
  orchestrator_classify | ticket_draft | policy_rag | service_guide |
  ticket_advice | ai_analyze | pre_review |
  embedding_index | embedding_query | semantic_cache

Design principles (P0-D fix):
1. Tokens MUST come from the real model `usage` block. NEVER hardcode 0.
2. When the model did not return usage, record `usage_unavailable=True`
   honestly — do not fabricate zero-token successes.
3. RAG retrieval and LLM generation are logged separately so one user
   request does not produce a single ambiguous row.
4. Embedding calls record text_count, text_chars, model, dimensions and
   fallback status for traceability.
5. Failed, timed-out and degraded calls MUST also be logged.
6. Writing is best-effort: a logging failure MUST NOT break the main flow.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..llm_client import LlmResult
from ..embedding_client import EmbeddingResult
from ..models import AiUsageLogModel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# --- Capability constants ---

CAP_ORCHESTRATOR_CLASSIFY = "orchestrator_classify"
CAP_TICKET_DRAFT = "ticket_draft"
CAP_POLICY_RAG = "policy_rag"
CAP_SERVICE_GUIDE = "service_guide"
CAP_TICKET_ADVICE = "ticket_advice"
CAP_AI_ANALYZE = "ai_analyze"
CAP_PRE_REVIEW = "pre_review"
CAP_EMBEDDING_INDEX = "embedding_index"
CAP_EMBEDDING_QUERY = "embedding_query"
CAP_SEMANTIC_CACHE = "semantic_cache"

ALL_CAPABILITIES = {
    CAP_ORCHESTRATOR_CLASSIFY, CAP_TICKET_DRAFT, CAP_POLICY_RAG, CAP_SERVICE_GUIDE,
    CAP_TICKET_ADVICE, CAP_AI_ANALYZE, CAP_PRE_REVIEW,
    CAP_EMBEDDING_INDEX, CAP_EMBEDDING_QUERY, CAP_SEMANTIC_CACHE,
}

# Map capability -> model_tier (used by admin dashboards and cost estimates).
_TIER_FOR_CAPABILITY = {
    CAP_ORCHESTRATOR_CLASSIFY: "llm_lite",
    CAP_TICKET_DRAFT: "llm_lite",
    CAP_POLICY_RAG: "llm_full",
    CAP_SERVICE_GUIDE: "llm_full",
    CAP_TICKET_ADVICE: "llm_full",
    CAP_AI_ANALYZE: "llm_full",
    CAP_PRE_REVIEW: "llm_lite",
    CAP_EMBEDDING_INDEX: "embedding",
    CAP_EMBEDDING_QUERY: "embedding",
    CAP_SEMANTIC_CACHE: "embedding",
}

# Map model_tier -> cost per 1k tokens (RMB). Mirror orchestrator_guard pricing.
_COST_PER_1K = {
    "rules": 0.0,
    "embedding": 0.0005,
    "llm_lite": 0.002,
    "llm_full": 0.008,
}


def _estimate_cost(tier: str, prompt_tokens: int, completion_tokens: int) -> float:
    rate = _COST_PER_1K.get(tier, 0.0)
    return round(((prompt_tokens + completion_tokens) / 1000.0) * rate, 6)


@dataclass
class UsageContext:
    """Per-call context carried alongside the LLM/embedding result."""
    capability: str
    route: Optional[str] = None
    principal: Optional[Principal] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None

    def __post_init__(self):
        if not self.request_id:
            self.request_id = uuid.uuid4().hex


def make_context(capability: str, *, route: Optional[str] = None,
                 principal: Optional[Principal] = None,
                 session_id: Optional[str] = None,
                 request_id: Optional[str] = None) -> UsageContext:
    """Convenience factory."""
    return UsageContext(
        capability=capability,
        route=route,
        principal=principal,
        session_id=session_id,
        request_id=request_id,
    )


class AiUsageRecorder:
    """Best-effort recorder for `ai_usage_logs` rows."""

    def __init__(self, db: Optional[Session]):
        self.db = db

    # --- LLM calls ---

    def record_llm_call(
        self,
        ctx: UsageContext,
        result: LlmResult,
        *,
        provider: Optional[str] = None,
        cache_hit: bool = False,
        rate_limited: bool = False,
        degraded: bool = False,
        degrade_reason: Optional[str] = None,
        budget_exceeded: bool = False,
    ) -> None:
        capability = ctx.capability
        tier = _TIER_FOR_CAPABILITY.get(capability, "llm_full")
        usage = result.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total = usage.total_tokens if usage else (prompt_tokens + completion_tokens)
        unavailable = bool(usage.unavailable) if usage else True

        model_name = result.model or "unknown"
        prov = provider or _derive_provider_from_model(model_name)

        cost = _estimate_cost(tier, prompt_tokens, completion_tokens)

        # Map error_code to degrade_reason if not provided
        if degraded and not degrade_reason:
            degrade_reason = "llm_unavailable"
        if rate_limited and not degrade_reason:
            degrade_reason = "rate_limited"
        if budget_exceeded and not degrade_reason:
            degrade_reason = "budget_exceeded"

        success = result.success and not rate_limited and not budget_exceeded

        self._write_row({
            "request_id": ctx.request_id,
            "user_id": ctx.principal.user_id if ctx.principal and ctx.principal.kind == "user" else None,
            "role": ctx.principal.role if ctx.principal else "service",
            "route": ctx.route,
            "model_name": model_name,
            "model_tier": tier,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "latency_ms": result.latency_ms or 0,
            "cache_hit": cache_hit,
            "rate_limited": rate_limited,
            "degraded": degraded or bool(degrade_reason),
            "estimated_cost_rmb": cost,
            "success": success,
            "error": (result.error or "")[:500] if not success else None,
            "session_id": ctx.session_id,
            "capability": capability,
            "provider": prov,
            "total_tokens": total,
            "usage_unavailable": unavailable,
            "degrade_reason": degrade_reason,
            "budget_exceeded": budget_exceeded,
            "error_code": result.error_code if not success else None,
            "text_count": None,
            "text_chars": None,
        })

    # --- Embedding calls ---

    def record_embedding_call(
        self,
        ctx: UsageContext,
        result: EmbeddingResult,
        *,
        text_count: int = 1,
        text_chars: int = 0,
        cache_hit: bool = False,
        rate_limited: bool = False,
        degraded: bool = False,
        degrade_reason: Optional[str] = None,
        budget_exceeded: bool = False,
    ) -> None:
        capability = ctx.capability
        tier = _TIER_FOR_CAPABILITY.get(capability, "embedding")
        usage = result.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        total = usage.total_tokens if usage else prompt_tokens
        unavailable = bool(usage.unavailable) if usage else True

        model_name = result.model or "unknown"
        prov = _derive_provider_from_model(model_name)
        if result.fallback:
            prov = "fallback"
            degraded = True
            degrade_reason = degrade_reason or "embedding_unavailable"

        cost = _estimate_cost(tier, prompt_tokens, 0)

        if rate_limited and not degrade_reason:
            degrade_reason = "rate_limited"
        if budget_exceeded and not degrade_reason:
            degrade_reason = "budget_exceeded"

        success = result.success and not rate_limited and not budget_exceeded

        self._write_row({
            "request_id": ctx.request_id,
            "user_id": ctx.principal.user_id if ctx.principal and ctx.principal.kind == "user" else None,
            "role": ctx.principal.role if ctx.principal else "service",
            "route": ctx.route,
            "model_name": model_name,
            "model_tier": tier,
            "input_tokens": prompt_tokens,
            "output_tokens": 0,
            "latency_ms": 0,
            "cache_hit": cache_hit,
            "rate_limited": rate_limited,
            "degraded": degraded or bool(degrade_reason),
            "estimated_cost_rmb": cost,
            "success": success,
            "error": result.error if not success else None,
            "session_id": ctx.session_id,
            "capability": capability,
            "provider": prov,
            "total_tokens": total,
            "usage_unavailable": unavailable,
            "degrade_reason": degrade_reason,
            "budget_exceeded": budget_exceeded,
            "error_code": None,
            "text_count": text_count,
            "text_chars": text_chars,
        })

    # --- Rules-only "calls" (deterministic paths, zero tokens) ---

    def record_rules_call(
        self,
        ctx: UsageContext,
        *,
        model_name: str = "rules",
        latency_ms: int = 0,
        cache_hit: bool = False,
        degrade_reason: Optional[str] = None,
        success: bool = True,
        rate_limited: bool = False,
        budget_exceeded: bool = False,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Log a rules-tier decision (no LLM/embedding involved).

        Records honestly that no tokens were consumed. This is the ONLY
        legitimate path that writes zero tokens. Used for rule-based routing,
        cache hits, and Guard rejections (rate_limited / budget_exceeded /
        input_too_long / session_exceeded / etc.).
        """
        self._write_row({
            "request_id": ctx.request_id,
            "user_id": ctx.principal.user_id if ctx.principal and ctx.principal.kind == "user" else None,
            "role": ctx.principal.role if ctx.principal else "service",
            "route": ctx.route,
            "model_name": model_name,
            "model_tier": "rules",
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency_ms,
            "cache_hit": cache_hit,
            "rate_limited": rate_limited,
            "degraded": bool(degrade_reason),
            "estimated_cost_rmb": 0.0,
            "success": success,
            "error": (error[:500] if error else None),
            "session_id": ctx.session_id,
            "capability": ctx.capability,
            "provider": "rules",
            "total_tokens": 0,
            "usage_unavailable": False,  # rules path genuinely consumed no tokens
            "degrade_reason": degrade_reason,
            "budget_exceeded": budget_exceeded,
            "error_code": error_code,
            "text_count": None,
            "text_chars": None,
        })

    # --- Internal ---

    def _write_row(self, fields: dict) -> None:
        if self.db is None:
            return
        try:
            row = AiUsageLogModel(**fields)
            self.db.add(row)
            self.db.commit()
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("ai_usage_logs write failed (best-effort): %s", exc)
            try:
                self.db.rollback()
            except Exception:
                pass


def _derive_provider_from_model(model_name: str) -> str:
    """Best-effort provider derivation from model name."""
    if not model_name:
        return "unknown"
    name = model_name.lower()
    if "deepseek" in name:
        return "deepseek"
    if "qwen" in name:
        return "silicon_flow"
    if "gpt" in name or "openai" in name:
        return "openai"
    if "doubao" in name or "ark" in name:
        return "volcengine"
    if "fallback" in name or "hash" in name:
        return "fallback"
    if name == "rules":
        return "rules"
    return "unknown"
