import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
SENSITIVE_KEYS = {
    "password",
    "current_password",
    "new_password",
    "token",
    "access_token",
    "authorization",
    "cookie",
    "id_card",
    "id_number",
    "api_key",
    "secret",
    "secret_key",
    "phone",
    "contact",
    "mobile",
    "file_content",
    "file_body",
    "raw_content",
    "sender_id",
}

_ID_CARD_RE = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}\d{2}\d{2}\d{3}[0-9Xx](?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_DOOR_UNIT_RE = re.compile(r"(?:\d{1,3}\s*(?:号楼|栋|幢)\s*)?(?:\d{1,2}\s*单元\s*)?\d{1,4}\s*(?:室|户|房)")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-+=/]+")
_API_KEY_ASSIGN_RE = re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*\S+")


def redact_for_llm(value: str) -> str:
    """Strip direct personal identifiers before sending ticket/chat text to external LLMs."""
    if not isinstance(value, str) or not value:
        return value
    text = _ID_CARD_RE.sub("[已脱敏证件号]", value)
    text = _PHONE_RE.sub("[已脱敏手机号]", text)
    text = _LANDLINE_RE.sub("[已脱敏电话]", text)
    text = _EMAIL_RE.sub("[已脱敏邮箱]", text)
    text = _DOOR_UNIT_RE.sub("[已脱敏门牌]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _API_KEY_ASSIGN_RE.sub(r"\1=[REDACTED]", text)
    return text


def redact(value):
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = _ID_CARD_RE.sub("[REDACTED_ID]", value)
        text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
        text = _BEARER_RE.sub(r"\1[REDACTED]", text)
        text = _API_KEY_ASSIGN_RE.sub(r"\1=[REDACTED]", text)
        return text
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
