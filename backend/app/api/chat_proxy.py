"""Rasa chat proxy with Chinese language guard.

Public/visitor chat should prefer Orchestrator. This proxy remains for
Rasa fallback paths — every text bubble is language-checked before return.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..errors import BusinessError
from ..services.language_guard import sanitize_rasa_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

RASA_WEBHOOK_URL = os.getenv("RASA_WEBHOOK_URL", "http://rasa:5005/webhooks/rest/webhook")


class RasaProxyRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=5000)
    metadata: Optional[dict[str, Any]] = None


@router.post("/rasa")
def proxy_rasa_chat(payload: RasaProxyRequest, request: Request) -> list[dict]:
    """Forward to Rasa REST webhook and strip non-Chinese replies."""
    metadata = dict(payload.metadata or {})
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        metadata["request_id"] = request_id
    body = {
        "sender": payload.sender,
        "message": payload.message,
        "metadata": metadata,
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if request_id:
        headers["X-Request-ID"] = request_id

    req = urllib.request.Request(
        RASA_WEBHOOK_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        logger.warning("rasa proxy upstream status=%s body=%s", exc.code, detail)
        raise BusinessError("RASA_ERROR", "对话服务返回异常，请稍后重试。", 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("rasa proxy connect failed: %s", exc)
        raise BusinessError("RASA_UNAVAILABLE", "对话服务暂时不可用，请稍后重试。", 503) from exc

    try:
        messages = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BusinessError("RASA_ERROR", "对话服务返回格式异常。", 502) from exc

    if not isinstance(messages, list):
        messages = []
    return sanitize_rasa_messages(messages, source="rasa_proxy")
