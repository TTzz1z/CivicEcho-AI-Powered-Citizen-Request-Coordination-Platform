import hmac

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..errors import AuthenticationError
from ..repositories.identity import UserRepository
from ..security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    token = credentials.credentials
    if hmac.compare_digest(token, get_settings().service_api_token):
        return Principal(kind="service", username="rasa-action", role="service")
    payload = decode_access_token(token)
    user = UserRepository(db).get(int(payload["sub"]))
    if not user or not user.is_active:
        raise AuthenticationError()
    return Principal("user", user.id, user.username, user.role, user.department_id)


def get_optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    """Allow anonymous visitors; validate token when present."""
    if not credentials or credentials.scheme.lower() != "bearer":
        return Principal(kind="anonymous", username="visitor", role="anonymous")
    try:
        return get_current_principal(credentials, db)
    except AuthenticationError:
        # Invalid/expired token → treat as visitor rather than hard-fail chat
        return Principal(kind="anonymous", username="visitor", role="anonymous")


def get_user_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
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
            principal = get_current_principal(credentials, db)
            if principal.kind == "user" and principal.role == "admin":
                return
        except AuthenticationError:
            pass
    raise AuthenticationError("metrics 需要监控令牌或管理员认证")
