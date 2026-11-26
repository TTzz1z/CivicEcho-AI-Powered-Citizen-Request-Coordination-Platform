from sqlalchemy.exc import IntegrityError

from ..authorization import Principal
from ..config import get_settings
from ..errors import AuthenticationError, BusinessError
from ..models import UserModel
from ..repositories.identity import AuditRepository, UserRepository
from ..schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserRead,
)
from ..security import create_access_token, hash_password, verify_password


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
            access_token=create_access_token(user.id, user.role, token_version=user.token_version or 1),
            expires_in=settings.jwt_access_token_minutes * 60,
        )

    def logout(self, principal: Principal) -> dict:
        user = self.users.get(principal.user_id) if principal.user_id is not None else None
        if user:
            user.token_version = int(getattr(user, "token_version", 1) or 1) + 1
            self.users.save(user)
            self.audit.log(principal, "logout", resource_type="user", resource_id=str(user.id))
        return {"revoked": True}

    def change_password(self, principal: Principal, payload: ChangePasswordRequest) -> ChangePasswordResponse:
        user = self.users.get(principal.user_id) if principal.user_id is not None else None
        if not user or not user.is_active:
            raise AuthenticationError()
        if not verify_password(payload.current_password, user.password_hash):
            self.audit.log(
                principal,
                "change_password",
                "denied",
                resource_type="user",
                resource_id=str(user.id),
                details={"reason": "invalid_current_password"},
            )
            raise BusinessError("INVALID_CURRENT_PASSWORD", "当前密码不正确", 400)
        if payload.new_password == payload.current_password:
            raise BusinessError("PASSWORD_UNCHANGED", "新密码不能与当前密码相同", 422)
        user.password_hash = hash_password(payload.new_password)
        user.token_version = int(getattr(user, "token_version", 1) or 1) + 1
        self.users.save(user)
        self.audit.log(principal, "change_password", "success", resource_type="user", resource_id=str(user.id))
        settings = get_settings()
        token = create_access_token(user.id, user.role, token_version=user.token_version)
        return ChangePasswordResponse(
            access_token=token,
            expires_in=settings.jwt_access_token_minutes * 60,
            token_version=user.token_version,
            user=UserRead.model_validate(user),
        )

    def register(self, payload: RegisterRequest) -> RegisterResponse:
        settings = get_settings()
        if not settings.allow_citizen_self_register:
            raise BusinessError("REGISTRATION_DISABLED", "当前暂未开放市民自助注册", 403)
        if self.users.get_by_username_ci(payload.username):
            self.audit.log(
                None,
                "register",
                "denied",
                details={"username": payload.username, "reason": "username_exists"},
            )
            raise BusinessError("USERNAME_EXISTS", "用户名已存在", 409)
        user = UserModel(
            username=payload.username,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name or payload.username,
            role="citizen",
            department_id=None,
            is_active=True,
            token_version=1,
        )
        try:
            user = self.users.add(user)
        except IntegrityError:
            self.users.rollback()
            raise BusinessError("USERNAME_EXISTS", "用户名已存在", 409) from None
        principal = Principal("user", user.id, user.username, user.role, user.department_id)
        self.audit.log(
            principal,
            "register",
            "success",
            resource_type="user",
            resource_id=str(user.id),
            details={"role": "citizen"},
        )
        token = create_access_token(user.id, user.role, token_version=user.token_version or 1)
        return RegisterResponse(
            access_token=token,
            expires_in=settings.jwt_access_token_minutes * 60,
            user=UserRead.model_validate(user),
        )
