"""Database-backed rate limiters shared across workers/containers."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from .database import SessionLocal
from .errors import BusinessError
from .models import LoginAttemptModel


class RateLimiter:
    def __init__(
        self,
        attempts: int,
        window_seconds: int,
        *,
        error_code: str = "RATE_LIMITED",
        message: str = "请求过于频繁，请稍后重试",
    ):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.error_code = error_code
        self.message = message

    def check(self, key: str) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=self.window_seconds)
        with SessionLocal() as db:
            count = db.scalar(
                select(func.count(LoginAttemptModel.id)).where(
                    LoginAttemptModel.key == key,
                    LoginAttemptModel.attempted_at >= window_start,
                )
            ) or 0
            if count >= self.attempts:
                oldest = db.scalar(
                    select(LoginAttemptModel.attempted_at).where(
                        LoginAttemptModel.key == key,
                        LoginAttemptModel.attempted_at >= window_start,
                    ).order_by(LoginAttemptModel.attempted_at).limit(1)
                )
                if oldest is not None and oldest.tzinfo is None:
                    oldest = oldest.replace(tzinfo=timezone.utc)
                retry_after = (
                    max(1, int(self.window_seconds - (now - oldest).total_seconds()))
                    if oldest
                    else self.window_seconds
                )
                raise BusinessError(
                    self.error_code,
                    self.message,
                    429,
                    {"retry_after": retry_after},
                )
            db.add(LoginAttemptModel(key=key, attempted_at=now))
            db.commit()

    def reset(self, key: str) -> None:
        with SessionLocal() as db:
            db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key == key))
            db.commit()

    def cleanup_expired(self, *, max_window_seconds: int | None = None) -> int:
        """Remove attempts older than the longest configured window. Called by worker periodically."""
        effective_window = max(self.window_seconds, max_window_seconds or 0)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=effective_window * 2)
        with SessionLocal() as db:
            result = db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.attempted_at < cutoff))
            db.commit()
            return result.rowcount


class LoginRateLimiter(RateLimiter):
    def __init__(self, attempts: int, window_seconds: int):
        super().__init__(
            attempts,
            window_seconds,
            error_code="LOGIN_RATE_LIMITED",
            message="登录尝试过于频繁，请稍后重试",
        )
