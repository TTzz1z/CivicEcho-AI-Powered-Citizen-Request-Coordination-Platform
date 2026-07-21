import hmac

from fastapi import Depends
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


def get_user_principal(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.kind != "user":
        raise AuthenticationError()
    return principal
