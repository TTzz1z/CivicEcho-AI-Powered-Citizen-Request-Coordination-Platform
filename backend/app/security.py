import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pwdlib import PasswordHash

from .config import get_settings
from .errors import AuthenticationError


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hash.verify(password, encoded)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: int, role: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iss": "tingting-backend",
        "aud": "tingting-web",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + (expires_delta or timedelta(minutes=settings.jwt_access_token_minutes))).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(settings.jwt_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_unb64(header_part))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise ValueError
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(get_settings().jwt_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_part)):
            raise ValueError
        payload = json.loads(_unb64(payload_part))
        if payload.get("iss") != "tingting-backend" or payload.get("aud") != "tingting-web":
            raise ValueError
        if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise AuthenticationError("登录凭据已过期，请重新登录")
        int(payload["sub"])
        int(payload["iat"])
        if not payload.get("jti"):
            raise ValueError
        return payload
    except AuthenticationError:
        raise
    except Exception as exc:
        raise AuthenticationError() from exc


def anonymous_creator_key(reference: str | None) -> str | None:
    if not reference:
        return None
    return hashlib.sha256(reference.encode("utf-8")).hexdigest()
