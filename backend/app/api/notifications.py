import asyncio
from datetime import datetime, timezone
import json
import time

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..authorization import Principal
from ..database import SessionLocal, get_db
from ..errors import AuthenticationError, PermissionDenied
from ..repositories.aftercare import AftercareRepository, NotificationRepository
from ..repositories.identity import AuditRepository
from ..schemas import NotificationChannelRead, NotificationList, NotificationRead, SuccessResponse
from ..services.aftercare_service import AftercareService
from .dependencies import _authenticate, bearer, get_user_principal


router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

_SSE_POLL_INTERVAL_SECONDS = 2.0
_SSE_PING_INTERVAL_SECONDS = 20.0
_SSE_MAX_SECONDS = 240.0


def get_service(db: Session = Depends(get_db)) -> AftercareService:
    return AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))


async def get_stream_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    """Authenticate SSE caller using a short-lived DB session that closes before streaming."""
    def _auth() -> Principal:
        with SessionLocal() as db:
            principal = _authenticate(credentials, db)
        if principal.kind == "service":
            raise PermissionDenied()
        if principal.kind != "user":
            raise AuthenticationError()
        return principal

    return await run_in_threadpool(_auth)


def _format_sse(event: str, data: object, event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _fetch_stream_batch(
    user_id: int,
    raw_last_id: str | None,
    cursor: tuple[datetime, str] | None,
    *,
    initial: bool,
) -> tuple[int, list[tuple[str, dict]], tuple[datetime, str] | None]:
    with SessionLocal() as db:
        repo = NotificationRepository(db)
        effective_cursor = repo.resolve_stream_cursor(user_id, raw_last_id) if initial else cursor
        unread_count, items, next_cursor = repo.stream_updates(user_id, effective_cursor)
        serialized = [
            (
                f"{item.created_at.isoformat()}|{item.id}",
                NotificationRead.model_validate(item).model_dump(mode="json"),
            )
            for item in items
        ]
        return unread_count, serialized, next_cursor


@router.get("/stream")
async def stream_notifications(
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
    principal: Principal = Depends(get_stream_principal),
):
    raw_last_id = (last_event_id_header or last_event_id_query or "").strip() or None

    async def event_generator():
        started_at = time.monotonic()
        poll_interval = max(0.05, _SSE_POLL_INTERVAL_SECONDS)
        ping_interval = max(0.1, _SSE_PING_INTERVAL_SECONDS)
        max_seconds = max(0.1, _SSE_MAX_SECONDS)
        cursor: tuple[datetime, str] | None = None
        last_unread: int | None = None
        last_ping_at = started_at

        try:
            unread_count, items, cursor = await run_in_threadpool(
                _fetch_stream_batch,
                principal.user_id,
                raw_last_id,
                None,
                initial=True,
            )
            yield _format_sse("unread_count", {"unread_count": unread_count})
            last_unread = unread_count
            for event_id, item_payload in items:
                yield _format_sse("notification", item_payload, event_id=event_id)
                last_ping_at = time.monotonic()

            while (time.monotonic() - started_at) < max_seconds:
                if await request.is_disconnected():
                    break
                remaining = max_seconds - (time.monotonic() - started_at)
                if remaining <= 0:
                    break
                await asyncio.sleep(min(poll_interval, remaining))
                if await request.is_disconnected():
                    break

                unread_count, items, cursor = await run_in_threadpool(
                    _fetch_stream_batch,
                    principal.user_id,
                    None,
                    cursor,
                    initial=False,
                )
                if unread_count != last_unread:
                    yield _format_sse("unread_count", {"unread_count": unread_count})
                    last_unread = unread_count
                for event_id, item_payload in items:
                    yield _format_sse("notification", item_payload, event_id=event_id)
                    last_ping_at = time.monotonic()

                now_mono = time.monotonic()
                if (now_mono - last_ping_at) >= ping_interval:
                    yield _format_sse("ping", {"ts": datetime.now(timezone.utc).isoformat()})
                    last_ping_at = now_mono
        except SQLAlchemyError:
            yield _format_sse(
                "error",
                {"code": "STREAM_UNAVAILABLE", "message": "通知流暂时不可用，请回退轮询"},
            )
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=SuccessResponse[NotificationList], response_model_exclude_none=True)
def list_notifications(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False, principal: Principal = Depends(get_user_principal),
    service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.list_notifications(principal, page, page_size, unread_only))


@router.post("/{notification_id}/read", response_model=SuccessResponse[NotificationRead], response_model_exclude_none=True)
def read_notification(notification_id: str, principal: Principal = Depends(get_user_principal),
                      service: AftercareService = Depends(get_service)):
    return SuccessResponse(data=service.read_notification(notification_id, principal))


@router.post("/read-all", response_model=SuccessResponse[dict])
def read_all(principal: Principal = Depends(get_user_principal), service: AftercareService = Depends(get_service)):
    return SuccessResponse(data={"read_count": service.read_all_notifications(principal)})


@router.get("/channels", response_model=SuccessResponse[list[NotificationChannelRead]])
def channels(_: Principal = Depends(get_user_principal)):
    return SuccessResponse(data=[
        NotificationChannelRead(channel="in_app", label="站内通知", enabled=True, phase="P1"),
        NotificationChannelRead(channel="sms", label="短信", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="wechat", label="微信公众号/小程序", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="email", label="邮件", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="government_message", label="政务消息中心", enabled=False, phase="reserved"),
    ])
