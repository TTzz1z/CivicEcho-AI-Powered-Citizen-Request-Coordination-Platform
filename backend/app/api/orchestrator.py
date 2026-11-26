"""Orchestrator API endpoint - unified entry point for citizen chat messages."""
import asyncio
import inspect
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..authorization import Principal
from ..database import get_db
from ..errors import PermissionDenied
from ..logging_config import request_id_context
from ..model_governance import model_caller
from ..schemas import SuccessResponse
from ..services.language_guard import ensure_chinese_response
from ..services.orchestrator_service import get_orchestrator
from .dependencies import get_optional_principal
from .notifications import _format_sse

logger = logging.getLogger(__name__)
_STREAM_DONE = object()

router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])


class OrchestratorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    route_hint: Optional[str] = Field(default=None, max_length=64)
    # Round 2 r2-5: per-session identifier. Callers (frontend / API clients)
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
    advisory_only: bool = True


@router.post("/chat", response_model=SuccessResponse[OrchestratorResponse])
def orchestrator_chat(
    payload: OrchestratorRequest,
    request: Request,
    principal: Principal = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    """Process a citizen message through the unified orchestrator.

    Visitors (no token) are allowed — rate/budget limits still apply via Guard.
    """
    orchestrator = get_orchestrator()
    if principal.kind == "service":
        raise PermissionDenied()

    client_ip = request.client.host if request.client else "anon"
    # Build user context from principal
    if principal.kind == "user":
        user_context = {
            "user_id": principal.user_id,
            "role": principal.role,
            "contact": "",
            "ip": client_ip,
        }
    else:
        user_context = {
            "user_id": None,
            "role": "anonymous",
            "contact": "",
            "ip": client_ip,
        }
    result = orchestrator.process(payload.message, user_context, payload.route_hint,
                                  db=db, principal=principal,
                                  session_id=payload.session_id)

    # Defense-in-depth: never return non-Chinese citizen-facing text
    message = ensure_chinese_response(result.message, source="orchestrator")
    clarify = result.clarify_question
    if clarify:
        clarify = ensure_chinese_response(clarify, source="orchestrator_clarify")

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
        clarify_question=clarify,
        message=message,
        payload=result.payload,
        cache_hit=result.cache_hit,
        degraded=result.degraded,
        degrade_reason=result.degrade_reason,
        rate_limited=result.rate_limited,
        budget_exceeded=result.budget_exceeded,
        advisory_only=result.advisory_only,
    ))


@router.post("/chat/stream")
async def orchestrator_chat_stream(
    payload: OrchestratorRequest,
    request: Request,
    principal: Principal = Depends(get_optional_principal),
):
    """Stream citizen orchestrator responses as SSE (`meta` -> `delta` -> `done`)."""
    orchestrator = get_orchestrator()
    if principal.kind == "service":
        raise PermissionDenied()

    client_ip = request.client.host if request.client else "anon"
    if principal.kind == "user":
        user_context = {
            "user_id": principal.user_id,
            "role": principal.role,
            "contact": "",
            "ip": client_ip,
        }
        caller_value = f"user:{principal.user_id}"
    else:
        user_context = {
            "user_id": None,
            "role": "anonymous",
            "contact": "",
            "ip": client_ip,
        }
        caller_value = f"ip:{client_ip}"

    captured_request_id = request_id_context.get()
    if not captured_request_id or captured_request_id == "-":
        captured_request_id = uuid.uuid4().hex
    db_provider = request.app.dependency_overrides.get(get_db, get_db)

    async def event_generator():
        db_gen = None
        sync_gen = None
        closed = False

        def _open_stream():
            nonlocal db_gen, sync_gen
            raw_db = db_provider()
            if inspect.isgenerator(raw_db):
                db_gen = raw_db
                db = next(db_gen)
            else:
                db = raw_db
            caller_tok = model_caller.set(caller_value)
            req_tok = request_id_context.set(captured_request_id)
            try:
                sync_gen = orchestrator.process_stream(
                    payload.message,
                    user_context,
                    payload.route_hint,
                    db=db,
                    principal=principal,
                    session_id=payload.session_id,
                )
            finally:
                request_id_context.reset(req_tok)
                model_caller.reset(caller_tok)

        def _next_event():
            caller_tok = model_caller.set(caller_value)
            req_tok = request_id_context.set(captured_request_id)
            try:
                return next(sync_gen, _STREAM_DONE)
            finally:
                request_id_context.reset(req_tok)
                model_caller.reset(caller_tok)

        def _close_stream():
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                if sync_gen is not None and hasattr(sync_gen, "close"):
                    try:
                        sync_gen.close()
                    except Exception:
                        pass
            finally:
                if db_gen is not None:
                    try:
                        db_gen.close()
                    except Exception:
                        pass

        try:
            await run_in_threadpool(_open_stream)
            while True:
                if await request.is_disconnected():
                    break
                item = await run_in_threadpool(_next_event)
                if item is _STREAM_DONE:
                    break
                event_name, event_data = item
                yield _format_sse(event_name, event_data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Orchestrator SSE stream error: %s", type(exc).__name__)
            yield _format_sse(
                "error",
                {
                    "code": "STREAM_ERROR",
                    "message": "智能对话流式输出暂时不可用，请重试。",
                    "advisory_only": True,
                },
            )
        finally:
            try:
                await run_in_threadpool(_close_stream)
            except BaseException:
                _close_stream()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
