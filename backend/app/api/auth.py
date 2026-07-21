from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..repositories.identity import AuditRepository, UserRepository
from ..schemas import LoginRequest, SuccessResponse, TokenResponse, UserRead
from ..services.auth_service import AuthService
from .dependencies import get_user_principal
from ..authorization import Principal
from ..config import get_settings
from ..rate_limit import LoginRateLimiter


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()
login_limiter = LoginRateLimiter(settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), AuditRepository(db))


@router.post("/login", response_model=SuccessResponse[TokenResponse])
def login(request: Request, payload: LoginRequest, service: AuthService = Depends(get_auth_service)):
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{payload.username.strip().lower()}"
    login_limiter.check(key)
    result = service.login(payload)
    login_limiter.reset(key)
    return SuccessResponse(data=result)


@router.get("/me", response_model=SuccessResponse[UserRead])
def me(principal: Principal = Depends(get_user_principal), db: Session = Depends(get_db)):
    user = UserRepository(db).get(principal.user_id)
    return SuccessResponse(data=user)
