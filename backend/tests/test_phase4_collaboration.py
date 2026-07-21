from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import DepartmentModel, UserModel
from app.security import create_access_token, hash_password


client = TestClient(app)
PASSWORD = "Phase4-Pytest-Only!"


@pytest.fixture(scope="module")
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        departments = list(db.scalars(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).limit(3)).all())
        assert len(departments) == 3
        result = {}
        definitions = [
            ("citizen", None), ("agent", None), ("admin", None),
            ("staff0", departments[0]), ("staff1", departments[1]), ("staff2", departments[2]),
        ]
        for name, department in definitions:
            role = "department_staff" if name.startswith("staff") else name
            user = UserModel(
                username=f"phase4_{name}_{suffix}", password_hash=hash_password(PASSWORD),
                display_name=f"phase4-{name}", role=role,
                department_id=department.id if department else None, is_active=True,
            )
            db.add(user)
            db.flush()
            result[name] = {"id": user.id, "role": role, "department_id": user.department_id}
        db.commit()
    result["departments"] = departments
    return result


def auth(actor):
    return {"Authorization": f"Bearer {create_access_token(actor['id'], actor['role'])}"}


def create_ticket(actor):
    response = client.post("/api/v1/tickets", json={
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": "跨部门道路积水事项", "location": "幸福路", "source": "phase4-pytest",
    }, headers=auth(actor))
    assert response.status_code == 201
    return response.json()["data"]["ticket"]


def create_order(ticket_id, version, task_type, department_id, actor):
    response = client.post(f"/api/v1/tickets/{ticket_id}/work-orders", json={
        "version": version, "task_type": task_type, "department_id": department_id,
        "instructions": f"{task_type} 部门处置要求",
    }, headers=auth(actor))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def action(ticket_id, order, name, actor, extra=None):
    payload = {"version": order["version"], "remark": f"{name} 操作说明"}
    payload.update(extra or {})
    response = client.post(
        f"/api/v1/tickets/{ticket_id}/work-orders/{order['id']}/{name}",
        json=payload, headers=auth(actor),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def result_payload(label):
    return {
        "result_summary": f"{label}结果摘要", "result_measures": f"{label}处理措施",
        "result_outcome": "resolved", "public_content": f"{label}公开办理结果",
    }


def test_multiple_departments_submit_and_primary_summarizes(actors):
    citizen, agent = actors["citizen"], actors["agent"]
    departments = actors["departments"]
    ticket = create_ticket(citizen)
    ticket_id = ticket["ticket_id"]
    assert client.post(f"/api/v1/tickets/{ticket_id}/supplement-request", json={
        "version": 1, "remark": "材料不完整", "supplement_reason": "请补充现场时间",
    }, headers=auth(agent)).status_code == 200
    assert client.post(f"/api/v1/tickets/{ticket_id}/supplement", json={
        "version": 2, "remark": "完成补充", "supplement_content": "今天上午九点发生",
    }, headers=auth(citizen)).status_code == 200
    assert client.post(f"/api/v1/tickets/{ticket_id}/accept", json={
        "version": 3, "remark": "受理", "priority": "normal",
    }, headers=auth(agent)).status_code == 200
    primary = create_order(ticket_id, 4, "primary", departments[0].id, agent)
    support = create_order(ticket_id, 5, "support", departments[1].id, agent)
    review = create_order(ticket_id, 6, "review", departments[2].id, agent)

    orders = [(primary, actors["staff0"], "主办"), (support, actors["staff1"], "协办"), (review, actors["staff2"], "复核")]
    for order, staff, label in orders:
        started = action(ticket_id, order, "start", staff)
        action(ticket_id, started, "submit", staff, result_payload(label))
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(agent)).json()["data"]
    assert detail["collaboration_status"] == "awaiting_summary"
    assert {item["task_type"] for item in detail["work_orders"]} == {"primary", "support", "review"}
    citizen_view = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(citizen)).json()["data"]
    assert all(not item.get("internal_note") and item["history"] == [] for item in citizen_view["work_orders"])
    summary = client.post(f"/api/v1/tickets/{ticket_id}/summary", json={
        "version": detail["version"], "remark": "主办汇总", "resolution_summary": "协同处置完成",
        "resolution_measures": "综合三个部门办理结果", "resolution_outcome": "resolved",
        "public_reply": "道路积水及相关安全问题已完成协同处置。",
    }, headers=auth(actors["staff0"]))
    assert summary.status_code == 200
    # P0-A: summary moves to awaiting_review; master ticket stays in processing.
    assert summary.json()["data"]["status"] == "processing"
    assert summary.json()["data"]["collaboration_status"] == "awaiting_review"
    # P0-A: agent must review and resolve.
    resolved = client.post(f"/api/v1/tickets/{ticket_id}/review-resolve", json={
        "version": summary.json()["data"]["version"], "remark": "坐席审核办结",
        "resolution_summary": "协同处置完成", "resolution_measures": "综合三个部门办理结果",
        "resolution_outcome": "resolved", "public_reply": "道路积水及相关安全问题已完成协同处置。",
    }, headers=auth(actors["agent"]))
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "resolved"
    assert resolved.json()["data"]["collaboration_status"] == "completed"


def test_return_transfer_and_admin_dispute_coordination(actors):
    agent, admin, departments = actors["agent"], actors["admin"], actors["departments"]
    ticket = create_ticket(actors["citizen"])
    ticket_id = ticket["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={
        "version": 1, "remark": "受理", "priority": "normal",
    }, headers=auth(agent))
    first = create_order(ticket_id, 2, "primary", departments[0].id, agent)
    returned = action(ticket_id, first, "return", actors["staff0"])
    assert returned["status"] == "returned"
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(agent)).json()["data"]
    assert detail["status"] == "accepted" and detail["collaboration_status"] == "awaiting_dispatch"
    primary = create_order(ticket_id, detail["version"], "primary", departments[1].id, agent)
    support = create_order(ticket_id, detail["version"] + 1, "support", departments[1].id, agent)
    successor = action(ticket_id, support, "transfer", actors["staff1"], {
        "target_department_id": departments[2].id,
    })
    assert successor["department_id"] == departments[2].id and successor["source_work_order_id"] == support["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(actors["staff2"])).json()["data"]
    opened = client.post(f"/api/v1/tickets/{ticket_id}/dispute", json={
        "version": detail["version"], "remark": "提出争议", "dispute_reason": "责任边界需要协调",
    }, headers=auth(actors["staff2"]))
    assert opened.status_code == 200 and opened.json()["data"]["collaboration_status"] == "disputed"
    resolved = client.post(f"/api/v1/tickets/{ticket_id}/dispute/resolve", json={
        "version": opened.json()["data"]["version"], "remark": "管理员协调",
        "resolution": "维持当前主办部门，转入协同办理", "primary_work_order_id": primary["id"],
    }, headers=auth(admin))
    assert resolved.status_code == 200
    assert resolved.json()["data"]["collaboration_status"] == "in_progress"
