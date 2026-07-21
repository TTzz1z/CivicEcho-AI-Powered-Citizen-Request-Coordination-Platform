from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AuditLogModel, DepartmentModel, TicketModel, UserModel
from app.security import create_access_token, hash_password


client = TestClient(app)
PASSWORD = "Phase6-Pytest-Only!"


@pytest.fixture(scope="module")
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        department = db.scalar(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).limit(1))
        result = {}
        for name, role, department_id in (
            ("citizen", "citizen", None), ("agent", "agent", None),
            ("staff", "department_staff", department.id), ("admin", "admin", None),
        ):
            user = UserModel(username=f"phase6_{name}_{suffix}", password_hash=hash_password(PASSWORD),
                             display_name=f"phase6-{name}", role=role, department_id=department_id, is_active=True)
            db.add(user)
            db.flush()
            result[name] = {"id": user.id, "role": role}
        db.commit()
    return result


def headers(actor):
    return {"Authorization": f"Bearer {create_access_token(actor['id'], actor['role'])}"}


def test_ai_is_advisory_idempotent_and_audited(actors):
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": "幸福路社区燃气泄漏并且有人受伤，请立即处理",
        "location": "幸福路社区 8 号楼", "source": "phase6-test",
    })
    assert created.status_code == 201, created.text
    ticket = created.json()["data"]["ticket"]
    before_status, before_version = ticket["status"], ticket["version"]
    payload = {"suggestion_types": ["assignment", "similarity", "summary", "completeness", "document_draft", "risk"]}
    response = client.post(f"/api/v1/ai/tickets/{ticket['ticket_id']}/analyze", headers=headers(actors["agent"]), json=payload)
    assert response.status_code == 200, response.text
    suggestions = response.json()["data"]
    assert {item["suggestion_type"] for item in suggestions} == set(payload["suggestion_types"])
    risk = next(item for item in suggestions if item["suggestion_type"] == "risk")
    assert risk["risk_level"] == "urgent" and risk["advisory_only"] is True
    draft = next(item for item in suggestions if item["suggestion_type"] == "document_draft")
    assert draft["result"]["requires_fact_check"] is True

    repeated = client.post(f"/api/v1/ai/tickets/{ticket['ticket_id']}/analyze", headers=headers(actors["agent"]), json=payload)
    assert [item["id"] for item in repeated.json()["data"]] == [item["id"] for item in suggestions]
    detail = client.get(f"/api/v1/tickets/{ticket['ticket_id']}", headers=headers(actors["agent"])).json()["data"]
    assert (detail["status"], detail["version"]) == (before_status, before_version)

    reviewed = client.post(f"/api/v1/ai/suggestions/{risk['id']}/review", headers=headers(actors["agent"]),
                           json={"decision": "helpful", "comment": "已转人工核实"})
    assert reviewed.status_code == 200 and reviewed.json()["data"]["review_decision"] == "helpful"
    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditLogModel.action).where(
            AuditLogModel.resource_id.in_([item["id"] for item in suggestions])
        )).all())
        assert {"generate_ai_suggestion", "review_ai_suggestion"}.issubset(actions)


def test_role_boundaries_hotspots_and_safe_integration_fallback(actors):
    with SessionLocal() as db:
        ticket_id = db.scalar(select(TicketModel.ticket_id).where(TicketModel.source == "phase6-test"))
    denied = client.post(f"/api/v1/ai/tickets/{ticket_id}/analyze", headers=headers(actors["citizen"]),
                         json={"suggestion_types": ["assignment"]})
    assert denied.status_code == 403
    assert client.get("/api/v1/ai/hotspots", headers=headers(actors["citizen"])).status_code == 403
    assert client.get("/api/v1/ai/hotspots", headers=headers(actors["staff"])).status_code == 200
    statuses = client.get("/api/v1/integrations/status", headers=headers(actors["admin"]))
    assert statuses.status_code == 200
    assert {item["integration_type"] for item in statuses.json()["data"]} == {
        "oidc", "directory", "work_order", "sms", "map", "division", "logging", "monitoring"
    }
    assert client.get("/api/v1/integrations/status", headers=headers(actors["agent"])).status_code == 403
    sync = client.post(f"/api/v1/integrations/tickets/{ticket_id}/sync", headers=headers(actors["agent"]), json={"force": False})
    assert sync.status_code == 409 and sync.json()["error"]["code"] == "WORK_ORDER_PLATFORM_NOT_CONFIGURED"
    sms = client.post("/api/v1/integrations/sms/send", headers=headers(actors["admin"]), json={
        "phone": "13800000000", "template_code": "ticket_update", "parameters": {"ticket_id": ticket_id},
    })
    assert sms.status_code == 409 and sms.json()["error"]["code"] == "SMS_NOT_CONFIGURED"
    probe = client.post("/api/v1/integrations/logging/probe", headers=headers(actors["admin"]))
    assert probe.status_code == 409 and probe.json()["error"]["code"] == "LOGGING_NOT_CONFIGURED"
