from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..rate_limit import LoginRateLimiter
from ..repositories.identity import AuditRepository, UserRepository
from ..schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    SuccessResponse,
    TokenResponse,
    UserRead,
)
from ..services.auth_service import AuthService
from .dependencies import get_user_principal, require_register_rate_limit


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), AuditRepository(db))


def _login_limiter() -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)


@router.post("/login", response_model=SuccessResponse[TokenResponse])
def login(request: Request, payload: LoginRequest, service: AuthService = Depends(get_auth_service)):
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{payload.username.strip().lower()}"
    limiter = _login_limiter()
    limiter.check(key)
    result = service.login(payload)
    limiter.reset(key)
    return SuccessResponse(data=result)


@router.post(
    "/register",
    response_model=SuccessResponse[RegisterResponse],
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    _: None = Depends(require_register_rate_limit),
    service: AuthService = Depends(get_auth_service),
):
    return SuccessResponse(data=service.register(payload))


@router.post("/change-password", response_model=SuccessResponse[ChangePasswordResponse])
def change_password(
    payload: ChangePasswordRequest,
    principal: Principal = Depends(get_user_principal),
    service: AuthService = Depends(get_auth_service),
):
    return SuccessResponse(data=service.change_password(principal, payload))


@router.get("/me", response_model=SuccessResponse[UserRead])
def me(principal: Principal = Depends(get_user_principal), db: Session = Depends(get_db)):
    user = UserRepository(db).get(principal.user_id)
    return SuccessResponse(data=user)


@router.post("/logout", response_model=SuccessResponse[dict])
def logout(
    principal: Principal = Depends(get_user_principal),
    service: AuthService = Depends(get_auth_service),
):
    return SuccessResponse(data=service.logout(principal))
