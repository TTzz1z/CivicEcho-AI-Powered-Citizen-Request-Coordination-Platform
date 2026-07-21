from ..authorization import Principal
from ..config import get_settings
from ..errors import AuthenticationError
from ..repositories.identity import AuditRepository, UserRepository
from ..schemas import LoginRequest, TokenResponse
from ..security import create_access_token, verify_password


class AuthService:
    def __init__(self, users: UserRepository, audit: AuditRepository):
        self.users = users
        self.audit = audit

    def login(self, payload: LoginRequest) -> TokenResponse:
        user = self.users.get_by_username(payload.username.strip())
        if not user or not verify_password(payload.password, user.password_hash):
            self.audit.log(None, "login", "denied", details={"username": payload.username.strip()})
            raise AuthenticationError("用户名或密码错误")
        principal = Principal("user", user.id, user.username, user.role, user.department_id)
        if not user.is_active:
            self.audit.log(principal, "login", "denied", details={"reason": "inactive"})
            raise AuthenticationError("用户名或密码错误")
        self.audit.log(principal, "login")
        settings = get_settings()
        return TokenResponse(
            access_token=create_access_token(user.id, user.role),
            expires_in=settings.jwt_access_token_minutes * 60,
        )
