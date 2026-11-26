from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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


def test_pending_primary_submission_review_and_closed_guards(actors):
    citizen, agent, staff, admin = (actors[name] for name in ("citizen", "agent", "staff0", "admin"))
    ticket_id = create_ticket(citizen)["ticket_id"]
    path = f"/api/v1/tickets/{ticket_id}"
    accepted = client.post(f"{path}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    primary = create_order(ticket_id, accepted.json()["data"]["version"], "primary", staff["department_id"], agent)
    submitted = action(ticket_id, primary, "submit", staff, result_payload("本部门") | {"internal_note": "内部草稿备注"})
    assert submitted["accepted_at"] and submitted["submitted_at"]
    assert {item["action"] for item in submitted["history"]} == {"create", "start", "submit_result"}

    detail = client.get(path, headers=auth(agent)).json()["data"]
    draft = {
        "remark": "内部汇总", "resolution_summary": "内部汇总摘要", "resolution_measures": "内部汇总措施",
        "resolution_outcome": "resolved", "public_reply": "等待复核的答复", "internal_note": "内部答复备注",
    }
    summary = client.post(f"{path}/summary", json=draft | {"version": detail["version"]}, headers=auth(staff))
    assert summary.status_code == 200, summary.text
    current = summary.json()["data"]
    assert (current["status"], current["collaboration_status"]) == ("processing", "awaiting_review")
    agent_view = client.get(path, headers=auth(agent)).json()["data"]
    assert agent_view["review_draft"]["public_reply"] == draft["public_reply"]
    citizen_view = client.get(path, headers=auth(citizen)).json()["data"]
    assert "review_draft" not in citizen_view and "public_reply" not in citizen_view
    assert any(item["content"] == "主办部门已提交答复，等待坐席审核" for item in citizen_view["history"])
    orders_view = client.get(f"{path}/work-orders", headers=auth(citizen)).json()["data"]
    assert all("internal_note" not in row and "public_content" not in row and not row["history"] for row in orders_view)

    def in_queue(actor, queue):
        response = client.get("/api/v1/tickets", params={"work_queue": queue, "keyword": ticket_id}, headers=auth(actor))
        assert response.status_code == 200, response.text
        return any(item["ticket_id"] == ticket_id for item in response.json()["data"]["items"])

    assert in_queue(agent, "awaiting_review")
    returned = client.post(f"{path}/return-to-department", json={
        "version": current["version"], "remark": "退回补充", "return_reason": "补充现场记录",
    }, headers=auth(agent))
    assert returned.status_code == 200, returned.text
    assert not in_queue(agent, "awaiting_review") and in_queue(staff, "returned")
    detail = client.get(path, headers=auth(staff)).json()["data"]
    assert "review_draft" not in detail
    action(ticket_id, detail["work_orders"][0], "submit", staff, result_payload("补充后"))
    assert not in_queue(staff, "returned")
    detail = client.get(path, headers=auth(staff)).json()["data"]
    summary = client.post(f"{path}/summary", json=draft | {"version": detail["version"]}, headers=auth(staff))
    assert summary.status_code == 200, summary.text
    resolved = client.post(f"{path}/review-resolve", json=draft | {
        "version": summary.json()["data"]["version"], "public_reply": "已审核的最终答复",
    }, headers=auth(agent))
    assert resolved.status_code == 200, resolved.text
    current = resolved.json()["data"]
    assert client.get(path, headers=auth(citizen)).json()["data"]["public_reply"] == "已审核的最终答复"
    restarted = client.post(f"{path}/process", json={"version": current["version"], "remark": "重新办理"}, headers=auth(admin))
    assert restarted.status_code == 409 and restarted.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    closed = client.post(f"{path}/close", json={
        "version": current["version"], "remark": "代为办结", "override_reason": "电话回访确认",
    }, headers=auth(admin))
    assert closed.status_code == 200, closed.text
    disputed = client.post(f"{path}/dispute", json={
        "version": closed.json()["data"]["version"], "remark": "归属争议", "dispute_reason": "申请协调责任",
    }, headers=auth(admin))
    assert disputed.status_code == 409 and disputed.json()["error"]["code"] == "WORK_ORDER_NOT_ALLOWED"


def test_concurrent_master_and_primary_start_use_one_lock_order(actors):
    citizen, agent, staff = (actors[name] for name in ("citizen", "agent", "staff0"))
    ticket_id = create_ticket(citizen)["ticket_id"]
    path = f"/api/v1/tickets/{ticket_id}"
    accepted = client.post(f"{path}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    primary = create_order(ticket_id, accepted.json()["data"]["version"], "primary", staff["department_id"], agent)
    assigned = client.get(path, headers=auth(staff)).json()["data"]
    barrier = Barrier(2, timeout=10)

    def start(action_path, version):
        barrier.wait()
        return client.post(action_path, json={"version": version, "remark": "开始办理"}, headers=auth(staff))

    with ThreadPoolExecutor(max_workers=2) as executor:
        master = executor.submit(start, f"{path}/process", assigned["version"])
        work_order = executor.submit(start, f"{path}/work-orders/{primary['id']}/start", primary["version"])
        responses = [request.result(timeout=15) for request in (master, work_order)]
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = client.get(path, headers=auth(staff)).json()["data"]
    assert final["status"] == final["work_orders"][0]["status"] == "processing"
    assert final["version"] == assigned["version"] + 1
