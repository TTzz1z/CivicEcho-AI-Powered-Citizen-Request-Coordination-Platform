"""Database-backed login rate limiter shared across workers/containers."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from .database import SessionLocal
from .errors import BusinessError
from .models import LoginAttemptModel


class LoginRateLimiter:
    def __init__(self, attempts: int, window_seconds: int):
        self.attempts = attempts
        self.window_seconds = window_seconds

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
                retry_after = max(1, int(self.window_seconds - (now - oldest).total_seconds())) if oldest else self.window_seconds
                raise BusinessError("LOGIN_RATE_LIMITED", "登录尝试过于频繁，请稍后重试", 429, {"retry_after": retry_after})
            db.add(LoginAttemptModel(key=key, attempted_at=now))
            db.commit()

    def reset(self, key: str) -> None:
        with SessionLocal() as db:
            db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key == key))
            db.commit()

    def cleanup_expired(self) -> int:
        """Remove attempts older than the window. Called by worker periodically."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.window_seconds * 2)
        with SessionLocal() as db:
            result = db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.attempted_at < cutoff))
            db.commit()
            return result.rowcount
