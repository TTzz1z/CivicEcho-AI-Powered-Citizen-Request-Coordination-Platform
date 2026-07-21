from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_principal, get_user_principal
from app.api.tickets import get_service
from app.authorization import Principal
from app.main import app
from app.repositories.memory import InMemoryTicketRepository
from app.services.ticket_service import TicketService


AGENT = Principal("user", 10, "agent-test", "agent", None)


def payload(key=None):
    return {
        "idempotency_key": key or str(uuid4()),
        "request_type": "投诉",
        "description": "道路施工噪声持续到深夜",
        "location": "小区东门",
        "occurred_at": "昨天晚上",
        "source": "test",
    }


@pytest.fixture
def client():
    repository = InMemoryTicketRepository()
    service = TicketService(repository)
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: AGENT
    app.dependency_overrides[get_user_principal] = lambda: AGENT
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_get_accept_and_history(client):
    created = client.post("/api/v1/tickets", json=payload())
    assert created.status_code == 201
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}")
    assert detail.status_code == 200
    updated = client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "坐席受理"})
    assert updated.json()["data"]["status"] == "accepted"
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()["data"]
    assert [item["current_status"] for item in detail["history"]] == ["pending", "accepted"]


def test_missing_ticket_and_validation_use_error_envelope(client):
    missing = client.get("/api/v1/tickets/QT2099010100000001")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TICKET_NOT_FOUND"
    invalid = client.post("/api/v1/tickets", json={"request_type": "其他"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_idempotency_returns_same_ticket(client):
    key = str(uuid4())
    first = client.post("/api/v1/tickets", json=payload(key)).json()["data"]
    second = client.post("/api/v1/tickets", json=payload(key)).json()["data"]
    assert first["ticket"]["ticket_id"] == second["ticket"]["ticket_id"]
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True


def test_concurrent_creates_have_unique_ids(client):
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/tickets", json=payload()), range(40)))
    assert all(response.status_code == 201 for response in responses)
    ids = [response.json()["data"]["ticket"]["ticket_id"] for response in responses]
    assert len(ids) == len(set(ids)) == 40


def test_ticket_list_is_paginated(client):
    for _ in range(3):
        client.post("/api/v1/tickets", json=payload())
    result = client.get("/api/v1/tickets", params={"page": 1, "page_size": 2}).json()["data"]
    assert len(result["items"]) == 2
    assert result["total"] == 3
    assert result["page"] == 1
