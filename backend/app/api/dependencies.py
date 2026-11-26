import hmac

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..errors import AuthenticationError, BusinessError, PermissionDenied
from ..model_governance import model_caller
from ..rate_limit import RateLimiter
from ..repositories.identity import UserRepository
from ..security import decode_access_token


bearer = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    principal = await run_in_threadpool(_authenticate, credentials, db)
    if principal.kind == "user":
        model_caller.set(f"user:{principal.user_id}")
    return principal


def _authenticate(credentials: HTTPAuthorizationCredentials | None, db: Session) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    token = credentials.credentials
    if hmac.compare_digest(token, get_settings().service_api_token):
        return Principal(kind="service", username="service-client", role="service")
    payload = decode_access_token(token)
    user = UserRepository(db).get(int(payload["sub"]))
    if not user or not user.is_active:
        raise AuthenticationError()
    token_ver = int(payload.get("ver", 1))
    current_ver = int(getattr(user, "token_version", 1) or 1)
    if token_ver != current_ver or (payload.get("role") and payload.get("role") != user.role):
        raise AuthenticationError("登录凭据已失效，请重新登录")
    return Principal("user", user.id, user.username, user.role, user.department_id)


async def get_optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    """Allow anonymous visitors; validate token when present."""
    if not credentials or credentials.scheme.lower() != "bearer":
        return Principal(kind="anonymous", username="visitor", role="anonymous")
    try:
        return await get_current_principal(credentials, db)
    except AuthenticationError:
        # Invalid/expired token → treat as visitor rather than hard-fail chat
        return Principal(kind="anonymous", username="visitor", role="anonymous")


def get_user_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.kind == "service":
        raise PermissionDenied()
    if principal.kind != "user":
        raise AuthenticationError()
    return principal


def require_metrics_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> None:
    """Block anonymous access to operational /metrics.

    Accepts MONITORING_TOKEN (Bearer or X-Monitoring-Token) or an admin JWT.
    Health checks must continue to use /health/* — never /metrics.
    """
    settings = get_settings()
    monitoring = (settings.monitoring_token or "").strip()
    header_token = (request.headers.get("x-monitoring-token") or "").strip()
    if monitoring:
        if header_token and hmac.compare_digest(header_token, monitoring):
            return
        if (
            credentials
            and credentials.scheme.lower() == "bearer"
            and hmac.compare_digest(credentials.credentials, monitoring)
        ):
            return
    if credentials and credentials.scheme.lower() == "bearer":
        try:
            principal = _authenticate(credentials, db)
            if principal.kind == "user" and principal.role == "admin":
                return
        except AuthenticationError:
            pass
    raise AuthenticationError("metrics 需要监控令牌或管理员认证")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_register_rate_limit(request: Request) -> None:
    settings = get_settings()
    if not settings.allow_citizen_self_register:
        raise BusinessError("REGISTRATION_DISABLED", "当前暂未开放市民自助注册", 403)
    RateLimiter(
        settings.register_rate_limit_attempts,
        settings.register_rate_limit_window_seconds,
        error_code="REGISTER_RATE_LIMITED",
        message="注册请求过于频繁，请稍后重试",
    ).check(f"register:{_client_ip(request)}")


def require_anon_ticket_rate_limit(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> None:
    if principal.kind not in {"service", "anonymous"}:
        return
    settings = get_settings()
    RateLimiter(
        settings.anon_ticket_rate_limit_attempts,
        settings.anon_ticket_rate_limit_window_seconds,
        error_code="TICKET_RATE_LIMITED",
        message="提交工单过于频繁，请稍后重试",
    ).check(f"anon_ticket:{_client_ip(request)}")


def require_upload_rate_limit(
    request: Request,
    principal: Principal = Depends(get_user_principal),
) -> None:
    settings = get_settings()
    RateLimiter(
        settings.upload_rate_limit_attempts,
        settings.upload_rate_limit_window_seconds,
        error_code="UPLOAD_RATE_LIMITED",
        message="文件上传过于频繁，请稍后重试",
    ).check(f"upload:{principal.user_id}:{_client_ip(request)}")


def require_ai_rate_limit(
    request: Request,
    principal: Principal = Depends(get_user_principal),
) -> None:
    settings = get_settings()
    RateLimiter(
        settings.ai_rate_limit_attempts,
        settings.ai_rate_limit_window_seconds,
        error_code="AI_RATE_LIMITED",
        message="AI 请求过于频繁，请稍后重试",
    ).check(f"ai:{principal.user_id}:{_client_ip(request)}")


def require_export_rate_limit(
    request: Request,
    principal: Principal = Depends(get_user_principal),
) -> None:
    settings = get_settings()
    RateLimiter(
        settings.export_rate_limit_attempts,
        settings.export_rate_limit_window_seconds,
        error_code="EXPORT_RATE_LIMITED",
        message="导出请求过于频繁，请稍后重试",
    ).check(f"export:{principal.user_id}:{_client_ip(request)}")
