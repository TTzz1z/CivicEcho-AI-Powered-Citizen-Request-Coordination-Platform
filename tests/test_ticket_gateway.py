import unittest
from unittest.mock import AsyncMock, patch

import httpx

from actions.ticket_gateway import (
    HttpTicketGateway, TicketBusinessError, TicketConnectionError,
    TicketNotFoundError, TicketTimeoutError,
)


def response(status, body):
    return httpx.Response(
        status, json=body, request=httpx.Request("GET", "http://backend/test")
    )


class HttpTicketGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def test_fastapi_success_response(self):
        body = {
            "success": True,
            "data": {"ticket": {"ticket_id": "QT2026071300000001", "status": "待受理"}, "idempotent_replay": False},
        }
        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=response(201, body))):
            ticket = await HttpTicketGateway("http://backend:8000").create_ticket({})
        self.assertEqual("QT2026071300000001", ticket["ticket_id"])

    async def test_not_found_and_business_error(self):
        not_found = response(404, {"success": False, "error": {"message": "未找到"}})
        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=not_found)):
            with self.assertRaises(TicketNotFoundError):
                await HttpTicketGateway("http://backend:8000").get_ticket("missing")

        invalid = response(422, {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "参数错误"}})
        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=invalid)):
            with self.assertRaises(TicketBusinessError):
                await HttpTicketGateway("http://backend:8000").create_ticket({})

    async def test_connection_failure_and_timeout(self):
        request = httpx.Request("GET", "http://backend/test")
        with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=httpx.ConnectError("down", request=request))):
            with self.assertRaises(TicketConnectionError):
                await HttpTicketGateway("http://backend:8000").get_ticket("ticket")
        with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=httpx.ReadTimeout("slow", request=request))):
            with self.assertRaises(TicketTimeoutError):
                await HttpTicketGateway("http://backend:8000").get_ticket("ticket")


if __name__ == "__main__":
    unittest.main()
