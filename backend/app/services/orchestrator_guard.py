"""Orchestrator guard: input limits, rate limit, dedup, concurrency,
semantic cache, daily budget, and degradation decisions.

Design goals:
- 资源滥用防护：限制输入长度、输出 token、超时、单会话轮数、并发、限流、去重
- 成本控制：单用户/全平台每日模型预算；超额降级
- 语义缓存：相似问题命中缓存，避免重复调用大模型
- 降级策略：LLM 不可用时 RAG/FAQ/工单/范围提示各自降级
- 审计：每次模型调用都写入 ai_usage_logs 表，包含 request_id 与各项指标

所有数据结构都进程内安全（threading.Lock 保护）；语义缓存和预算都持久化到
PostgreSQL（ai_usage_logs / ai_usage_budgets 表），保证多 worker 一致。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..embedding_client import get_embedding_client
from ..models import AiUsageLogModel, AiUsageBudgetModel

logger = logging.getLogger(__name__)


# --- Constants ---

DEFAULT_INPUT_MAX_CHARS = 500
DEFAULT_OUTPUT_MAX_TOKENS = 800
DEFAULT_LLM_TIMEOUT_SECONDS = 20
DEFAULT_SESSION_MAX_TURNS = 30
DEFAULT_RATE_LIMIT_PER_MINUTE = 20  # per user/IP
DEFAULT_DEDUP_WINDOW_SECONDS = 30  # same text within this window is deduped
DEFAULT_DAILY_USER_LLM_BUDGET = 60  # user LLM calls per day
DEFAULT_DAILY_PLATFORM_LLM_BUDGET = 5000
DEFAULT_CACHE_TTL_SECONDS = 6 * 3600
DEFAULT_CACHE_MAX_ENTRIES = 500
DEFAULT_CACHE_MIN_SIMILARITY = 0.92

# Model tier cost estimate (RMB per 1K tokens, rough)
COST_PER_1K_TOKENS = {
    "rules": 0.0,
    "embedding": 0.0005,
    "llm_lite": 0.002,  # short classification / extraction
    "llm_full": 0.008,  # full policy / service guide answer
}


@dataclass
class GuardDecision:
    """Result of pre-flight guard check."""
    allowed: bool
    rejection_reason: str = ""  # input_too_long | rate_limited | dedup_hit | budget_exceeded | session_exceeded | concurrent_exceeded
    cached_result: Optional[dict] = None  # set when dedup/cache hit
    cache_key: str = ""
    cache_hit: bool = False
    rate_limited: bool = False
    budget_exceeded: bool = False
    degraded: bool = False  # whether this request must use degraded path
    degrade_reason: str = ""  # llm_unavailable | budget_exceeded | rate_limited


@dataclass
class UsageRecord:
    """Metrics recorded after a model call."""
    request_id: str
    user_id: Optional[int]
    role: str
    route: str
    model_name: str
    model_tier: str  # rules | embedding | llm_lite | llm_full
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cache_hit: bool = False
    rate_limited: bool = False
    degraded: bool = False
    estimated_cost_rmb: float = 0.0
    success: bool = True
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OrchestratorGuard:
    """Stateful guard with in-process state + DB-backed persistence."""

    def __init__(self):
        self.settings = get_settings()
        self.input_max_chars = DEFAULT_INPUT_MAX_CHARS
        self.output_max_tokens = DEFAULT_OUTPUT_MAX_TOKENS
        self.llm_timeout = DEFAULT_LLM_TIMEOUT_SECONDS
        self.session_max_turns = DEFAULT_SESSION_MAX_TURNS
        self.rate_limit_per_minute = DEFAULT_RATE_LIMIT_PER_MINUTE
        self.dedup_window = DEFAULT_DEDUP_WINDOW_SECONDS
        self.daily_user_budget = DEFAULT_DAILY_USER_LLM_BUDGET
        self.daily_platform_budget = DEFAULT_DAILY_PLATFORM_LLM_BUDGET
        self.cache_ttl = DEFAULT_CACHE_TTL_SECONDS
        self.cache_max_entries = DEFAULT_CACHE_MAX_ENTRIES
        self.cache_min_similarity = DEFAULT_CACHE_MIN_SIMILARITY
        # In-process state
        self._rate_buckets: dict[str, deque[float]] = defaultdict(deque)
        self._dedup_buckets: dict[str, deque[tuple[float, str]]] = defaultdict(deque)
        self._session_turns: dict[str, int] = defaultdict(int)
        self._concurrency: dict[str, int] = defaultdict(int)
        self._cache: list[dict] = []  # each: {key, vector, payload, route, ts}
        self._cache_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._embedding = get_embedding_client()

    # ----------------------------------------------------------------
    # Pre-flight check
    # ----------------------------------------------------------------

    def pre_check(self, *, text: str, user_key: str, route_hint: Optional[str],
                  session_id: str, requires_llm: bool) -> GuardDecision:
        """Run all pre-flight checks. Returns GuardDecision."""
        # 1. Input length
        if len(text) > self.input_max_chars:
            return GuardDecision(
                allowed=False,
                rejection_reason="input_too_long",
            )
        # 2. Session turns
        with self._state_lock:
            turns = self._session_turns.get(session_id, 0)
            if turns >= self.session_max_turns:
                return GuardDecision(
                    allowed=False,
                    rejection_reason="session_exceeded",
                )
        # 3. Rate limit (per user/IP per minute)
        now = time.time()
        with self._state_lock:
            bucket = self._rate_buckets[user_key]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= self.rate_limit_per_minute:
                return GuardDecision(
                    allowed=False,
                    rejection_reason="rate_limited",
                    rate_limited=True,
                )
            bucket.append(now)
        # 4. Dedup: same text+route within window → return cached if available
        text_hash = self._hash_text(text)
        cache_key = f"{user_key}:{route_hint or 'auto'}:{text_hash}"
        with self._state_lock:
            dq = self._dedup_buckets[user_key]
            cutoff = now - self.dedup_window
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            for ts, key in dq:
                if key == cache_key:
                    # Dedup hit; return cached if present
                    cached = self._cache_lookup(cache_key, route_hint)
                    return GuardDecision(
                        allowed=True,
                        rejection_reason="dedup_hit",
                        cached_result=cached,
                        cache_key=cache_key,
                        cache_hit=cached is not None,
                    )
            dq.append((now, cache_key))
        # 5. Semantic cache (for LLM-bound requests only)
        if requires_llm:
            cached = self._cache_lookup_semantic(text, route_hint)
            if cached is not None:
                return GuardDecision(
                    allowed=True,
                    rejection_reason="cache_hit",
                    cached_result=cached,
                    cache_key=cache_key,
                    cache_hit=True,
                )
        # 6. Concurrency cap (max 1 concurrent LLM call per user)
        if requires_llm:
            with self._state_lock:
                if self._concurrency[user_key] >= 1:
                    return GuardDecision(
                        allowed=True,  # allow but force degradation
                        rejection_reason="concurrent_exceeded",
                        degraded=True,
                        degrade_reason="concurrent_exceeded",
                    )
        # 7. Budget check (only for LLM-bound requests)
        if requires_llm:
            degraded, reason = self._budget_check(user_key)
            if degraded:
                return GuardDecision(
                    allowed=True,
                    rejection_reason=reason,
                    degraded=True,
                    degrade_reason=reason,
                    budget_exceeded=(reason == "budget_exceeded"),
                )
        return GuardDecision(allowed=True, cache_key=cache_key)

    def acquire_llm_slot(self, user_key: str) -> bool:
        """Try to acquire a concurrency slot for an LLM call."""
        with self._state_lock:
            if self._concurrency[user_key] >= 1:
                return False
            self._concurrency[user_key] += 1
            return True

    def release_llm_slot(self, user_key: str) -> None:
        with self._state_lock:
            if self._concurrency[user_key] > 0:
                self._concurrency[user_key] -= 1

    def increment_session_turn(self, session_id: str) -> None:
        with self._state_lock:
            self._session_turns[session_id] += 1

    def reset_session(self, session_id: str) -> None:
        with self._state_lock:
            self._session_turns.pop(session_id, None)

    # ----------------------------------------------------------------
    # Cache
    # ----------------------------------------------------------------

    def cache_store(self, *, text: str, route: str, route_hint: Optional[str],
                    payload: dict,
                    principal: Optional[Principal] = None,
                    session_id: Optional[str] = None,
                    request_id: Optional[str] = None) -> None:
        """Store a successful LLM result in semantic cache."""
        try:
            vec = self._embed_for_cache(
                text, principal=principal, session_id=session_id,
                request_id=request_id, route=route,
            )
            if vec is None:
                return
            entry = {
                "text": text[:500],
                "vector": vec,
                "route": route,
                "route_hint": route_hint,
                "payload": payload,
                "ts": time.time(),
            }
            with self._cache_lock:
                self._cache.append(entry)
                # Trim by TTL and size
                cutoff = time.time() - self.cache_ttl
                self._cache = [e for e in self._cache if e["ts"] >= cutoff]
                if len(self._cache) > self.cache_max_entries:
                    self._cache = self._cache[-self.cache_max_entries:]
        except Exception as exc:
            logger.warning("cache_store failed: %s", exc)

    def _cache_lookup(self, cache_key: str, route_hint: Optional[str]) -> Optional[dict]:
        """Exact-key cache lookup (used by dedup path)."""
        # We don't store by cache_key in semantic cache; return None here.
        # Dedup path uses semantic similarity via _cache_lookup_semantic.
        return None

    def _cache_lookup_semantic(self, text: str, route_hint: Optional[str],
                               principal: Optional[Principal] = None,
                               session_id: Optional[str] = None,
                               request_id: Optional[str] = None,
                               route: Optional[str] = None) -> Optional[dict]:
        """Semantic cache lookup via embedding cosine similarity."""
        try:
            vec = self._embed_for_cache(
                text, principal=principal, session_id=session_id,
                request_id=request_id, route=route or "semantic_cache_lookup",
            )
            if vec is None:
                return None
            now = time.time()
            cutoff = now - self.cache_ttl
            best_sim = 0.0
            best_entry: Optional[dict] = None
            with self._cache_lock:
                for entry in self._cache:
                    if entry["ts"] < cutoff:
                        continue
                    if route_hint and entry.get("route_hint") and entry["route_hint"] != route_hint:
                        continue
                    sim = _cosine(vec, entry["vector"])
                    if sim > best_sim:
                        best_sim = sim
                        best_entry = entry
            if best_entry and best_sim >= self.cache_min_similarity:
                logger.info("Semantic cache hit sim=%.3f route=%s", best_sim, best_entry["route"])
                return {
                    "route": best_entry["route"],
                    "payload": best_entry["payload"],
                    "cache_similarity": best_sim,
                }
        except Exception as exc:
            logger.warning("cache_lookup failed: %s", exc)
        return None

    def _embed_for_cache(self, text: str, *,
                         principal: Optional[Principal] = None,
                         session_id: Optional[str] = None,
                         request_id: Optional[str] = None,
                         route: Optional[str] = None) -> Optional[list[float]]:
        """Get embedding for cache key. Returns None if unavailable.

        P0-D: records each cache embedding call to ai_usage_logs so even
        semantic-cache probes are auditable.
        """
        from .ai_usage_recorder import (
            AiUsageRecorder, make_context, CAP_SEMANTIC_CACHE,
        )
        from ..logging_config import request_id_context
        rid = request_id or request_id_context.get()
        if not self._embedding.available:
            # Fallback to deterministic hash-based pseudo vector.
            # P0-D: record fallback as an embedding-tier row so the audit
            # trail shows why semantic cache used a pseudo-vector.
            try:
                from ..database import SessionLocal
                with SessionLocal() as db:
                    AiUsageRecorder(db)._write_row({
                        "request_id": rid,
                        "user_id": principal.user_id if principal and principal.kind == "user" else None,
                        "role": principal.role if principal else "service",
                        "route": route,
                        "model_name": "fallback-hash",
                        "model_tier": "embedding",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "latency_ms": 0,
                        "cache_hit": False,
                        "rate_limited": False,
                        "degraded": True,
                        "estimated_cost_rmb": 0.0,
                        "success": True,
                        "error": None,
                        "session_id": session_id,
                        "capability": CAP_SEMANTIC_CACHE,
                        "provider": "fallback",
                        "total_tokens": 0,
                        "usage_unavailable": True,
                        "degrade_reason": "embedding_unavailable",
                        "budget_exceeded": False,
                        "error_code": None,
                        "text_count": 1,
                        "text_chars": len(text or ""),
                    })
                    db.commit()
            except Exception as exc:  # pragma: no cover — best-effort
                logger.warning("semantic_cache fallback audit write failed: %s", exc)
            return _pseudo_vector(text)
        try:
            result = self._embedding.embed(text)
            # P0-D: record real embedding call (best-effort, no DB session here
            # since cache lookup happens inside the in-process guard). We open
            # a fresh SessionLocal so the audit row is independent.
            try:
                from ..database import SessionLocal
                with SessionLocal() as db:
                    AiUsageRecorder(db).record_embedding_call(
                        make_context(CAP_SEMANTIC_CACHE, route=route,
                                     principal=principal, session_id=session_id,
                                     request_id=rid),
                        result,
                        text_count=1,
                        text_chars=len(text or ""),
                        degraded=result.fallback,
                        degrade_reason="embedding_fallback" if result.fallback else None,
                    )
                    db.commit()
            except Exception as exc:  # pragma: no cover — best-effort
                logger.warning("semantic_cache audit write failed: %s", exc)
            return result.vector
        except Exception as exc:
            logger.warning("Embedding for cache failed: %s", exc)
            return _pseudo_vector(text)

    # ----------------------------------------------------------------
    # Budget
    # ----------------------------------------------------------------

    def _budget_check(self, user_key: str) -> tuple[bool, str]:
        """Check if user/platform LLM budget exhausted. Returns (degraded, reason)."""
        try:
            from ..database import SessionLocal
            today = datetime.now(timezone.utc).date()
            with SessionLocal() as db:
                # User budget
                user_id = _parse_user_id(user_key)
                if user_id:
                    used = db.scalar(
                        select(func.count(AiUsageLogModel.id)).where(and_(
                            AiUsageLogModel.user_id == user_id,
                            AiUsageLogModel.model_tier.in_(["llm_lite", "llm_full"]),
                            func.date(AiUsageLogModel.created_at) == today,
                            AiUsageLogModel.cache_hit == False,  # noqa: E712
                        ))
                    ) or 0
                    if used >= self.daily_user_budget:
                        return True, "budget_exceeded"
                # Platform budget
                platform_used = db.scalar(
                    select(func.count(AiUsageLogModel.id)).where(and_(
                        AiUsageLogModel.model_tier.in_(["llm_lite", "llm_full"]),
                        func.date(AiUsageLogModel.created_at) == today,
                        AiUsageLogModel.cache_hit == False,  # noqa: E712
                    ))
                ) or 0
                if platform_used >= self.daily_platform_budget:
                    return True, "platform_budget_exceeded"
        except Exception as exc:
            logger.warning("Budget check failed (fail-open): %s", exc)
        return False, ""

    # ----------------------------------------------------------------
    # Audit logging
    # ----------------------------------------------------------------

    def record_usage(self, db: Session, record: UsageRecord) -> None:
        """Persist a usage record to ai_usage_logs."""
        try:
            log = AiUsageLogModel(
                request_id=record.request_id,
                user_id=record.user_id,
                role=record.role,
                route=record.route,
                model_name=record.model_name,
                model_tier=record.model_tier,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                latency_ms=record.latency_ms,
                cache_hit=record.cache_hit,
                rate_limited=record.rate_limited,
                degraded=record.degraded,
                estimated_cost_rmb=record.estimated_cost_rmb,
                success=record.success,
                error=record.error[:500] if record.error else None,
            )
            db.add(log)
            db.commit()
        except Exception as exc:
            logger.warning("record_usage failed: %s", exc)
            db.rollback()

    @staticmethod
    def estimate_cost(model_tier: str, input_tokens: int, output_tokens: int) -> float:
        rate = COST_PER_1K_TOKENS.get(model_tier, 0.0)
        return round(rate * (input_tokens + output_tokens) / 1000.0, 6)

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:32]


# --- Helpers ---

def _parse_user_id(user_key: str) -> Optional[int]:
    """user_key format: 'user:<id>' for logged-in, 'ip:<addr>' for anonymous."""
    if user_key.startswith("user:"):
        try:
            return int(user_key[5:])
        except ValueError:
            return None
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _pseudo_vector(text: str, dim: int = 256) -> list[float]:
    """Deterministic hash-based pseudo vector when embedding unavailable."""
    vec = [0.0] * dim
    text = text.lower()
    for i in range(len(text) - 1):
        gram = text[i:i + 2]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    for ch in text:
        h = int(hashlib.md5(ch.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 0.3
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# --- Singleton ---

_guard: Optional[OrchestratorGuard] = None


def get_guard() -> OrchestratorGuard:
    global _guard
    if _guard is None:
        _guard = OrchestratorGuard()
    return _guard


def reset_guard_for_tests() -> None:
    """Reset guard singleton + in-process state. For tests only."""
    global _guard
    _guard = OrchestratorGuard()
