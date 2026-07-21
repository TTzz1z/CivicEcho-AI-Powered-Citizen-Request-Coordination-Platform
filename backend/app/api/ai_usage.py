"""Admin endpoint: AI usage and safety metrics.

All metrics are aggregated from the real `ai_usage_logs` table — no static/mock data.

Provides:
- 每日调用次数 / Token 消耗 / 估算成本
- 各场景（route）用量
- 各角色（role）用量
- 各模型分层（model_tier）用量
- 缓存命中率
- 无关问题拦截次数（route=out_of_scope & success=true）
- 限流次数（rate_limited=true）
- 模型失败和降级情况（success=false / degraded=true）
- 近期调用明细（含 request_id）
- 每日时间序列
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..authorization import AuthorizationPolicy, Principal
from ..database import get_db
from ..models import AiUsageLogModel, AiUsageBudgetModel
from ..schemas import SuccessResponse
from .dependencies import get_current_principal

router = APIRouter(prefix="/api/v1/admin/ai-usage", tags=["admin-ai-usage"])


class AiUsageStats(BaseModel):
    """Aggregated AI usage stats for the admin dashboard."""
    # Overall totals (within the queried window)
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_rmb: float = 0.0
    # Quality metrics
    cache_hit_count: int = 0
    cache_hit_rate: float = 0.0
    rate_limited_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    out_of_scope_blocked_count: int = 0
    usage_unavailable_count: int = 0
    avg_latency_ms: float = 0.0
    # Breakdowns
    by_route: list[dict] = Field(default_factory=list)      # [{route, calls, tokens, cost}]
    by_role: list[dict] = Field(default_factory=list)       # [{role, calls, tokens, cost}]
    by_tier: list[dict] = Field(default_factory=list)       # [{tier, calls, tokens, cost}]
    by_capability: list[dict] = Field(default_factory=list)  # [{capability, calls, tokens, cost}]
    by_provider: list[dict] = Field(default_factory=list)   # [{provider, calls, tokens, cost}]
    by_model: list[dict] = Field(default_factory=list)      # [{model, calls, tokens, cost}]
    by_degrade_reason: list[dict] = Field(default_factory=list)  # [{reason, count}]
    # Daily timeseries (most recent first)
    timeseries: list[dict] = Field(default_factory=list)    # [{date, calls, tokens, cost, cache_hits, degraded, rate_limited}]


class AiUsageLogItem(BaseModel):
    id: int
    request_id: str
    user_id: Optional[int] = None
    role: Optional[str] = None
    route: Optional[str] = None
    model_name: str
    model_tier: str
    input_tokens: int
    output_tokens: int
    total_tokens: int = 0
    latency_ms: int
    cache_hit: bool
    rate_limited: bool
    degraded: bool
    estimated_cost_rmb: float
    success: bool
    error: Optional[str] = None
    created_at: datetime
    # Round 2 fields
    session_id: Optional[str] = None
    capability: Optional[str] = None
    provider: Optional[str] = None
    usage_unavailable: bool = False
    degrade_reason: Optional[str] = None
    budget_exceeded: bool = False
    error_code: Optional[str] = None
    text_count: Optional[int] = None
    text_chars: Optional[int] = None


class AiUsageLogsPage(BaseModel):
    items: list[AiUsageLogItem]
    total: int
    page: int
    page_size: int


def _require_admin(principal: Principal) -> None:
    AuthorizationPolicy.require_roles(principal, "admin")


def _utc_today(days_ago: int = 0) -> date:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()


@router.get("/stats", response_model=SuccessResponse[AiUsageStats])
def get_ai_usage_stats(
    days: int = Query(default=7, ge=1, le=90),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Aggregate AI usage stats over the last N days (default 7)."""
    _require_admin(principal)
    since_date = _utc_today(days - 1)  # inclusive today + (days-1) prior days

    base_filter = func.date(AiUsageLogModel.created_at) >= since_date

    # Totals
    total_calls = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(base_filter)
    ) or 0
    total_input = db.scalar(
        select(func.coalesce(func.sum(AiUsageLogModel.input_tokens), 0)).where(base_filter)
    ) or 0
    total_output = db.scalar(
        select(func.coalesce(func.sum(AiUsageLogModel.output_tokens), 0)).where(base_filter)
    ) or 0
    total_tokens = db.scalar(
        select(func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0)).where(base_filter)
    ) or 0
    total_cost = db.scalar(
        select(func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0)).where(base_filter)
    ) or 0.0
    avg_latency = db.scalar(
        select(func.coalesce(func.avg(AiUsageLogModel.latency_ms), 0.0)).where(base_filter)
    ) or 0.0
    cache_hit_count = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.cache_hit == True,  # noqa: E712
        ))
    ) or 0
    rate_limited_count = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.rate_limited == True,  # noqa: E712
        ))
    ) or 0
    degraded_count = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.degraded == True,  # noqa: E712
        ))
    ) or 0
    failed_count = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.success == False,  # noqa: E712
        ))
    ) or 0
    usage_unavailable_count = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.usage_unavailable == True,  # noqa: E712
        ))
    ) or 0
    # Out-of-scope blocked: route=out_of_scope, success=true (i.e., correctly rejected)
    out_of_scope_blocked = db.scalar(
        select(func.count(AiUsageLogModel.id)).where(and_(
            base_filter,
            AiUsageLogModel.route == "out_of_scope",
            AiUsageLogModel.success == True,  # noqa: E712
        ))
    ) or 0

    # Breakdowns (token sums use total_tokens so embedding-only rows are counted too)
    by_route_rows = db.execute(
        select(
            AiUsageLogModel.route,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.route)
    ).all()
    by_role_rows = db.execute(
        select(
            AiUsageLogModel.role,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.role)
    ).all()
    by_tier_rows = db.execute(
        select(
            AiUsageLogModel.model_tier,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.model_tier)
    ).all()
    by_capability_rows = db.execute(
        select(
            AiUsageLogModel.capability,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.capability)
    ).all()
    by_provider_rows = db.execute(
        select(
            AiUsageLogModel.provider,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.provider)
    ).all()
    by_model_rows = db.execute(
        select(
            AiUsageLogModel.model_name,
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
        ).where(base_filter).group_by(AiUsageLogModel.model_name)
    ).all()
    by_degrade_reason_rows = db.execute(
        select(
            AiUsageLogModel.degrade_reason,
            func.count(AiUsageLogModel.id),
        ).where(and_(base_filter, AiUsageLogModel.degrade_reason.is_not(None)))
         .group_by(AiUsageLogModel.degrade_reason)
    ).all()

    # Daily timeseries (group by date)
    ts_rows = db.execute(
        select(
            func.date(AiUsageLogModel.created_at).label("d"),
            func.count(AiUsageLogModel.id),
            func.coalesce(func.sum(AiUsageLogModel.total_tokens), 0),
            func.coalesce(func.sum(AiUsageLogModel.estimated_cost_rmb), 0.0),
            func.count(AiUsageLogModel.id).filter(AiUsageLogModel.cache_hit == True),  # noqa: E712
            func.count(AiUsageLogModel.id).filter(AiUsageLogModel.degraded == True),  # noqa: E712
            func.count(AiUsageLogModel.id).filter(AiUsageLogModel.rate_limited == True),  # noqa: E712
        ).where(base_filter).group_by("d").order_by(func.date(AiUsageLogModel.created_at).desc())
    ).all()

    cache_hit_rate = (cache_hit_count / total_calls) if total_calls else 0.0

    return SuccessResponse(data=AiUsageStats(
        total_calls=total_calls,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        total_cost_rmb=round(total_cost, 4),
        cache_hit_count=cache_hit_count,
        cache_hit_rate=round(cache_hit_rate, 4),
        rate_limited_count=rate_limited_count,
        degraded_count=degraded_count,
        failed_count=failed_count,
        out_of_scope_blocked_count=out_of_scope_blocked,
        usage_unavailable_count=usage_unavailable_count,
        avg_latency_ms=round(float(avg_latency), 2),
        by_route=[{"route": r or "unknown", "calls": int(c), "tokens": int(t), "cost": float(co)} for r, c, t, co in by_route_rows],
        by_role=[{"role": r or "anonymous", "calls": int(c), "tokens": int(t), "cost": float(co)} for r, c, t, co in by_role_rows],
        by_tier=[{"tier": t or "rules", "calls": int(c), "tokens": int(tk), "cost": float(co)} for t, c, tk, co in by_tier_rows],
        by_capability=[{"capability": r or "unknown", "calls": int(c), "tokens": int(t), "cost": float(co)} for r, c, t, co in by_capability_rows],
        by_provider=[{"provider": r or "unknown", "calls": int(c), "tokens": int(t), "cost": float(co)} for r, c, t, co in by_provider_rows],
        by_model=[{"model": r or "unknown", "calls": int(c), "tokens": int(t), "cost": float(co)} for r, c, t, co in by_model_rows],
        by_degrade_reason=[{"reason": r or "unknown", "count": int(c)} for r, c in by_degrade_reason_rows],
        timeseries=[{
            "date": str(d),
            "calls": int(c),
            "tokens": int(t),
            "cost": float(co),
            "cache_hits": int(ch),
            "degraded": int(dg),
            "rate_limited": int(rl),
        } for d, c, t, co, ch, dg, rl in ts_rows],
    ))


@router.get("/logs", response_model=SuccessResponse[AiUsageLogsPage])
def get_ai_usage_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    route: Optional[str] = Query(default=None),
    model_tier: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    capability: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
    degraded: Optional[bool] = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Recent AI usage logs (paginated)."""
    _require_admin(principal)
    conditions = []
    if route:
        conditions.append(AiUsageLogModel.route == route)
    if model_tier:
        conditions.append(AiUsageLogModel.model_tier == model_tier)
    if role:
        conditions.append(AiUsageLogModel.role == role)
    if capability:
        conditions.append(AiUsageLogModel.capability == capability)
    if provider:
        conditions.append(AiUsageLogModel.provider == provider)
    if session_id:
        # Substring match so admins can search by partial session id.
        conditions.append(AiUsageLogModel.session_id.like(f"%{session_id}%"))
    if success is not None:
        conditions.append(AiUsageLogModel.success == success)
    if degraded is not None:
        conditions.append(AiUsageLogModel.degraded == degraded)

    base_query = select(AiUsageLogModel)
    count_query = select(func.count(AiUsageLogModel.id))
    if conditions:
        base_query = base_query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total = db.scalar(count_query) or 0
    rows = list(db.scalars(
        base_query.order_by(AiUsageLogModel.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all())

    return SuccessResponse(data=AiUsageLogsPage(
        items=[AiUsageLogItem(
            id=r.id,
            request_id=r.request_id,
            user_id=r.user_id,
            role=r.role,
            route=r.route,
            model_name=r.model_name,
            model_tier=r.model_tier,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            total_tokens=r.total_tokens or 0,
            latency_ms=r.latency_ms,
            cache_hit=r.cache_hit,
            rate_limited=r.rate_limited,
            degraded=r.degraded,
            estimated_cost_rmb=r.estimated_cost_rmb,
            success=r.success,
            error=r.error,
            created_at=r.created_at,
            session_id=r.session_id,
            capability=r.capability,
            provider=r.provider,
            usage_unavailable=r.usage_unavailable or False,
            degrade_reason=r.degrade_reason,
            budget_exceeded=r.budget_exceeded or False,
            error_code=r.error_code,
            text_count=r.text_count,
            text_chars=r.text_chars,
        ) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    ))


@router.get("/budgets", response_model=SuccessResponse[list[dict]])
def list_ai_usage_budgets(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """List per-user LLM budget overrides."""
    _require_admin(principal)
    rows = list(db.scalars(
        select(AiUsageBudgetModel).order_by(AiUsageBudgetModel.created_at.desc()).limit(200)
    ).all())
    return SuccessResponse(data=[{
        "id": r.id,
        "user_id": r.user_id,
        "role": r.role,
        "daily_llm_call_limit": r.daily_llm_call_limit,
        "daily_token_limit": r.daily_token_limit,
        "notes": r.notes,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows])
