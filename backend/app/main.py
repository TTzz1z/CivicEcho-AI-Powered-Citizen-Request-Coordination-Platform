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
from starlette.requests import ClientDisconnect

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
from .api.dependencies import require_metrics_access
from .config import Settings, get_settings
from .errors import BusinessError
from .database import get_db
from .logging_config import configure_logging, request_id_context
from .model_governance import model_caller
from .storage import get_kb_object_storage, get_object_storage
from .telemetry import latency_metrics, tracer
from opentelemetry import context, trace
from opentelemetry.propagate import extract


settings = get_settings()
logger = logging.getLogger(__name__)


async def request_context(request: Request, call_next, active_settings: Settings | None = None):
    runtime_settings = active_settings or settings
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", incoming) else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    caller_token = model_caller.set(f"ip:{request.client.host if request.client else 'unknown'}")
    started = time.perf_counter()
    span = tracer.start_span(
        "http.request", context=extract(dict(request.headers)), record_exception=False,
        attributes={"http.request.method": request.method, "request.id": request_id},
    )
    span_token = context.attach(trace.set_span_in_context(span))
    try:
        request_limit = runtime_settings.max_request_body_bytes
        if request.method == "POST" and (
            request.url.path.endswith("/attachments")
            or request.url.path.endswith("/kb/documents/upload")
        ):
            request_limit = runtime_settings.attachment_max_bytes + runtime_settings.attachment_request_overhead_bytes
        content_length = request.headers.get("content-length")
        invalid_length = content_length is not None and not re.fullmatch(r"[0-9]{1,18}", content_length)
        if invalid_length:
            response = JSONResponse(
                status_code=400,
                content={"success": False, "error": {
                    "code": "INVALID_CONTENT_LENGTH", "message": "请求体长度格式无效", "details": None,
                }},
            )
        elif content_length is not None and int(content_length) > request_limit:
            response = JSONResponse(
                status_code=413,
                content={"success": False, "error": {"code": "REQUEST_TOO_LARGE", "message": "请求体超过大小限制", "details": None}},
            )
        elif content_length is None and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # Chunked or unknown body size: stream and enforce limit
            body = bytearray()
            try:
                async for chunk in request.stream():
                    if len(body) + len(chunk) > request_limit:
                        response = JSONResponse(
                            status_code=413,
                            content={"success": False, "error": {
                                "code": "REQUEST_TOO_LARGE", "message": "请求体超过大小限制", "details": None,
                            }},
                        )
                        break
                    body.extend(chunk)
                else:
                    # Re-inject consumed body for downstream handlers.
                    payload = bytes(body)

                    async def receive():
                        return {"type": "http.request", "body": payload, "more_body": False}

                    request._receive = receive  # type: ignore[attr-defined]
                    response = await call_next(request)
            except ClientDisconnect:
                response = JSONResponse(
                    status_code=400,
                    content={"success": False, "error": {
                        "code": "INCOMPLETE_REQUEST", "message": "请求体未完整接收", "details": None,
                    }},
                )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = format(span.get_span_context().trace_id, "032x")
        span.set_attribute("http.response.status_code", response.status_code)
        logger.info("request method=%s path=%s status=%s duration_ms=%.2f", request.method,
                    request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        return response
    except Exception:
        logger.exception("request failed method=%s path=%s duration_ms=%.2f", request.method,
                         request.url.path, (time.perf_counter() - started) * 1000)
        raise
    finally:
        context.detach(span_token)
        span.end()
        model_caller.reset(caller_token)
        request_id_context.reset(token)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active_settings = app_settings or settings
    configure_logging(active_settings.log_level)
    is_production = active_settings.app_env.strip().lower() in {"production", "prod"}
    application = FastAPI(
        title=active_settings.app_name,
        version="1.0.0",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-Creator-Reference",
            "X-Monitoring-Token",
            "Last-Event-ID",
            "Cache-Control",
        ],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    application.include_router(auth_router)
    application.include_router(departments_router)
    application.include_router(users_router)
    application.include_router(tickets_router)
    application.include_router(analytics_router)
    application.include_router(categories_router)
    application.include_router(attachments_router)
    application.include_router(notifications_router)
    application.include_router(aftercare_router)
    application.include_router(ai_router)
    application.include_router(integrations_router)
    application.include_router(orchestrator_router)
    application.include_router(kb_router)
    application.include_router(ai_usage_router)

    @application.middleware("http")
    async def _request_context_middleware(request: Request, call_next):
        return await request_context(request, call_next, app_settings)

    @application.get("/health/live")
    def liveness():
        return {"success": True, "data": {"status": "alive"}}

    @application.get("/health/ready")
    @application.get("/health")
    @application.get("/api/v1/system/health")
    def readiness(db: Session = Depends(get_db)):
        runtime_settings = app_settings or settings
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("readiness database probe failed")
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": {"code": "DATABASE_UNAVAILABLE", "message": "数据库暂不可用", "details": None}},
            )
        checks = {"status": "ready", "database": "ok"}
        if runtime_settings.object_storage_readiness_required:
            try:
                if not all(storage.bucket_exists()
                           for storage in (get_object_storage(), get_kb_object_storage())):
                    raise RuntimeError("required bucket missing")
            except Exception as exc:
                logger.warning("readiness object storage probe failed type=%s", type(exc).__name__)
                return JSONResponse(
                    status_code=503,
                    content={"success": False, "error": {
                        "code": "OBJECT_STORAGE_UNAVAILABLE", "message": "对象存储暂不可用", "details": None,
                    }},
                )
            checks["object_storage"] = "ok"
        return {"success": True, "data": checks}

    @application.exception_handler(BusinessError)
    async def business_error_handler(_: Request, exc: BusinessError):
        response = JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
        if exc.status_code == 429 and isinstance(exc.details, dict):
            response.headers["Retry-After"] = str(exc.details.get("retry_after", 60))
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "请求参数校验失败", "details": jsonable_encoder(exc.errors())}},
        )

    @application.exception_handler(Exception)
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

    @application.get("/metrics")
    def metrics(db: Session = Depends(get_db), _: None = Depends(require_metrics_access)):
        """Internal operational metrics — requires monitoring token or admin JWT."""
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
                "stage_latency": latency_metrics(),
            },
        }

    return application


app = create_app()
