import logging
import re
import time
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .api.tickets import router as tickets_router
from .api.auth import router as auth_router
from .api.departments import router as departments_router
from .api.users import router as users_router
from .api.analytics import router as analytics_router
from .api.aftercare import router as aftercare_router
from .api.notifications import router as notifications_router
from .api.categories import router as categories_router
from .api.attachments import router as attachments_router
from .api.ai import router as ai_router
from .api.integrations import router as integrations_router
from .api.orchestrator import router as orchestrator_router
from .api.kb import router as kb_router
from .api.ai_usage import router as ai_usage_router
from .config import get_settings
from .errors import BusinessError
from .database import get_db
from .logging_config import configure_logging, request_id_context


settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Creator-Reference"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)
app.include_router(auth_router)
app.include_router(departments_router)
app.include_router(users_router)
app.include_router(tickets_router)
app.include_router(analytics_router)
app.include_router(categories_router)
app.include_router(attachments_router)
app.include_router(notifications_router)
app.include_router(aftercare_router)
app.include_router(ai_router)
app.include_router(integrations_router)
app.include_router(orchestrator_router)
app.include_router(kb_router)
app.include_router(ai_usage_router)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", incoming) else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    try:
        request_limit = settings.max_request_body_bytes
        if request.method == "POST" and (
            request.url.path.endswith("/attachments")
            or request.url.path.endswith("/kb/documents/upload")
        ):
            request_limit = settings.attachment_max_bytes + settings.attachment_request_overhead_bytes
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > request_limit:
            response = JSONResponse(
                status_code=413,
                content={"success": False, "error": {"code": "REQUEST_TOO_LARGE", "message": "请求体超过大小限制", "details": None}},
            )
        elif not content_length and request.method in ("POST", "PUT", "PATCH"):
            # Chunked or unknown body size: stream and enforce limit
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > request_limit:
                    break
            if len(body) > request_limit:
                response = JSONResponse(
                    status_code=413,
                    content={"success": False, "error": {"code": "REQUEST_TOO_LARGE", "message": "请求体超过大小限制", "details": None}},
                )
            else:
                # Re-inject consumed body for downstream handlers
                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = receive  # type: ignore[attr-defined]
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info("request method=%s path=%s status=%s duration_ms=%.2f", request.method,
                    request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        return response
    except Exception:
        logger.exception("request failed method=%s path=%s duration_ms=%.2f", request.method,
                         request.url.path, (time.perf_counter() - started) * 1000)
        raise
    finally:
        request_id_context.reset(token)


@app.get("/health/live")
def liveness():
    return {"success": True, "data": {"status": "alive"}}


@app.get("/health/ready")
@app.get("/health")
@app.get("/api/v1/system/health")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("readiness database probe failed")
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": {"code": "DATABASE_UNAVAILABLE", "message": "数据库暂不可用", "details": None}},
        )
    return {"success": True, "data": {"status": "ready", "database": "ok"}}


@app.exception_handler(BusinessError)
async def business_error_handler(_: Request, exc: BusinessError):
    response = JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
    if exc.status_code == 429 and isinstance(exc.details, dict):
        response.headers["Retry-After"] = str(exc.details.get("retry_after", 60))
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "details": jsonable_encoder(exc.errors())}},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    logger.exception("Unhandled ticket backend error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "工单服务内部错误",
                "details": None,
            },
        },
    )


@app.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Basic operational metrics for monitoring."""
    from sqlalchemy import func, select
    from .models import NotificationOutboxModel, TicketModel
    ticket_counts = dict(db.execute(
        select(TicketModel.status, func.count(TicketModel.id)).group_by(TicketModel.status)
    ).all())
    outbox_counts = dict(db.execute(
        select(NotificationOutboxModel.status, func.count(NotificationOutboxModel.id)).group_by(NotificationOutboxModel.status)
    ).all())
    return {
        "success": True,
        "data": {
            "tickets_by_status": ticket_counts,
            "tickets_total": sum(ticket_counts.values()),
            "outbox_by_status": outbox_counts,
        },
    }
