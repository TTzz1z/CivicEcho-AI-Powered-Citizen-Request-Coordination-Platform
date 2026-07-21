"""Ticket business gateway used by Rasa actions.

HTTP mode is the production default. Memory mode is an explicit local/test
fallback and intentionally has process-local persistence only.
"""

import os
import logging
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional

import httpx

from actions.ticket_store import ticket_store


logger = logging.getLogger(__name__)
request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: Optional[str]) -> None:
    request_id_context.set(value if value and len(value) <= 64 else "-")


class TicketGatewayError(Exception):
    pass


class TicketConnectionError(TicketGatewayError):
    pass


class TicketTimeoutError(TicketGatewayError):
    pass


class TicketBusinessError(TicketGatewayError):
    def __init__(self, message: str, code: str = "BUSINESS_ERROR"):
        super().__init__(message)
        self.code = code


class TicketNotFoundError(TicketGatewayError):
    pass


class HttpTicketGateway:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0, service_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.service_token = service_token or os.getenv("TICKET_SERVICE_TOKEN", "")

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}))
        request_id = request_id_context.get()
        if request_id != "-":
            headers["X-Request-ID"] = request_id
        if self.service_token:
            headers["Authorization"] = f"Bearer {self.service_token}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            logger.warning("action_backend_call request_id=%s method=%s path=%s result=timeout duration_ms=%.2f", request_id, method, path, (time.perf_counter()-started)*1000)
            raise TicketTimeoutError("ticket backend timed out") from exc
        except httpx.RequestError as exc:
            logger.warning("action_backend_call request_id=%s method=%s path=%s result=connection_error duration_ms=%.2f", request_id, method, path, (time.perf_counter()-started)*1000)
            raise TicketConnectionError("ticket backend connection failed") from exc
        logger.info("action_backend_call request_id=%s method=%s path=%s status=%s duration_ms=%.2f", request_id, method, path, response.status_code, (time.perf_counter()-started)*1000)

        try:
            body = response.json()
        except ValueError as exc:
            raise TicketGatewayError("ticket backend returned invalid JSON") from exc
        if response.status_code == 404:
            raise TicketNotFoundError(body.get("error", {}).get("message", "ticket not found"))
        if response.is_error or not body.get("success"):
            error = body.get("error", {})
            raise TicketBusinessError(
                error.get("message", "工单服务拒绝了请求"),
                error.get("code", "BUSINESS_ERROR"),
            )
        return body["data"]

    async def create_ticket(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await self._request("POST", "/api/v1/tickets", json=payload)
        return result["ticket"]

    async def get_ticket(self, ticket_id: str, creator_reference: Optional[str] = None) -> Dict[str, Any]:
        headers = {"X-Creator-Reference": creator_reference} if creator_reference else {}
        return await self._request("GET", f"/api/v1/tickets/{ticket_id}", headers=headers)


class MemoryTicketGateway:
    """Adapter for the preserved Round-2 process-local mock."""

    def __init__(self):
        self._idempotency: Dict[str, str] = {}

    async def create_ticket(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = payload["idempotency_key"]
        existing_id = self._idempotency.get(key)
        if existing_id:
            existing = ticket_store.get_ticket(existing_id)
            if existing:
                return existing
        ticket = ticket_store.create_ticket(
            request_type=payload["request_type"],
            description=payload["description"],
            location=payload["location"],
            event=payload.get("event"),
            time=payload.get("occurred_at"),
            target=payload.get("target"),
            contact=payload.get("contact"),
        )
        self._idempotency[key] = ticket["ticket_id"]
        return ticket

    async def get_ticket(self, ticket_id: str, creator_reference: Optional[str] = None) -> Dict[str, Any]:
        ticket = ticket_store.get_ticket(ticket_id)
        if not ticket:
            raise TicketNotFoundError(ticket_id)
        return ticket

    def clear(self) -> None:
        self._idempotency.clear()


_memory_gateway = MemoryTicketGateway()


def get_ticket_gateway():
    mode = os.getenv("TICKET_BACKEND_MODE", "http").lower()
    if mode == "memory":
        return _memory_gateway
    if mode != "http":
        raise RuntimeError("TICKET_BACKEND_MODE must be 'http' or 'memory'")
    return HttpTicketGateway(
        os.getenv("TICKET_SERVICE_URL", "http://backend:8000"),
        float(os.getenv("TICKET_SERVICE_TIMEOUT_SECONDS", "5")),
        os.getenv("TICKET_SERVICE_TOKEN", ""),
    )
