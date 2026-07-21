"""Orchestrator API endpoint - unified entry point for citizen chat messages."""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..schemas import SuccessResponse
from ..services.orchestrator_service import get_orchestrator
from .dependencies import get_current_principal

router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])


class OrchestratorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    route_hint: Optional[str] = Field(default=None, max_length=64)
    session_context: Optional[dict] = None
    # Round 2 r2-5: per-session identifier. Callers (frontend / Rasa proxy)
    # MUST pass a fresh session_id per conversation so that turn counters,
    # guard buckets and ai_usage_logs are isolated per session — never shared
    # across all conversations via "user:default".
    session_id: Optional[str] = Field(default=None, max_length=128)


class OrchestratorResponse(BaseModel):
    primary_intent: str
    route: str
    confidence: float
    in_domain: bool = True
    requires_llm: bool = False
    model_tier: str = "rules"
    estimated_cost_level: str = "none"
    rejection_reason: str = ""
    urgency: str = "normal"
    sensitive_flags: list[str] = []
    routing_reason: str = ""
    should_create_ticket: bool = False
    should_clarify: bool = False
    clarify_question: Optional[str] = None
    message: str = ""
    payload: dict = {}
    cache_hit: bool = False
    degraded: bool = False
    degrade_reason: str = ""
    rate_limited: bool = False
    budget_exceeded: bool = False


@router.post("/chat", response_model=SuccessResponse[OrchestratorResponse])
def orchestrator_chat(
    payload: OrchestratorRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Process a citizen message through the unified orchestrator."""
    orchestrator = get_orchestrator()

    # Build user context from principal
    user_context = {
        "user_id": principal.user_id if principal.kind == "user" else None,
        "role": principal.role if principal.kind == "user" else "anonymous",
        "contact": "",  # Will be populated from user profile if available
    }
    if payload.session_context:
        user_context.update(payload.session_context)

    result = orchestrator.process(payload.message, user_context, payload.route_hint,
                                  db=db, principal=principal,
                                  session_id=payload.session_id)

    return SuccessResponse(data=OrchestratorResponse(
        primary_intent=result.primary_intent,
        route=result.route,
        confidence=result.confidence,
        in_domain=result.in_domain,
        requires_llm=result.requires_llm,
        model_tier=result.model_tier,
        estimated_cost_level=result.estimated_cost_level,
        rejection_reason=result.rejection_reason,
        urgency=result.urgency,
        sensitive_flags=result.sensitive_flags,
        routing_reason=result.routing_reason,
        should_create_ticket=result.should_create_ticket,
        should_clarify=result.should_clarify,
        clarify_question=result.clarify_question,
        message=result.message,
        payload=result.payload,
        cache_hit=result.cache_hit,
        degraded=result.degraded,
        degrade_reason=result.degrade_reason,
        rate_limited=result.rate_limited,
        budget_exceeded=result.budget_exceeded,
    ))
