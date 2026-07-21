from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.config import get_settings
from app.main import app
from app.models import AuditLogModel, DepartmentModel, UserModel
from app.security import create_access_token, hash_password
from app.time_normalization import normalize_chinese_time


client = TestClient(app)
PASSWORD = "Round4-Test-Only!"


@pytest.fixture(scope="module")
def identities():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        departments = list(db.scalars(select(DepartmentModel).order_by(DepartmentModel.id).limit(2)).all())
        users = {}
        for role, department, active in [
            ("citizen", None, True), ("citizen", None, True), ("agent", None, True),
            ("department_staff", departments[0], True), ("department_staff", departments[1], True),
            ("admin", None, True), ("citizen", None, False),
        ]:
            username = f"{role}_{active}_{suffix}_{len(users)}"
            user = UserModel(
                username=username, password_hash=hash_password(PASSWORD), display_name=username,
                role=role, department_id=department.id if department else None, is_active=active,
            )
            db.add(user)
            db.flush()
            users[username] = {
                "id": user.id, "username": username, "role": role,
                "department_id": user.department_id, "active": active,
            }
        db.commit()
    by_role = {}
    for value in users.values():
        by_role.setdefault((value["role"], value["active"]), []).append(value)
    return {"users": by_role, "departments": departments}


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(user['id'], user['role'])}"}


def ticket_payload():
    return {
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": "道路施工噪声持续到深夜", "location": "幸福路",
        "occurred_at": "昨天晚上", "contact": "13800000000", "source": "pytest",
    }


def test_authentication_matrix(identities):
    agent = identities["users"][("agent", True)][0]
    inactive = identities["users"][("citizen", False)][0]
    ok = client.post("/api/v1/auth/login", json={"username": agent["username"], "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["data"]["access_token"]
    assert client.post("/api/v1/auth/login", json={"username": agent["username"], "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "missing-user", "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": inactive["username"], "password": PASSWORD}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer broken.token"}).status_code == 401
    expired = create_access_token(agent["id"], agent["role"], timedelta(seconds=-1))
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    me = client.get("/api/v1/auth/me", headers=auth(agent))
    assert me.status_code == 200 and me.json()["data"]["role"] == "agent"


def test_complete_workflow_authorization_history_and_audit(identities):
    citizen, other_citizen = identities["users"][("citizen", True)]
    agent = identities["users"][("agent", True)][0]
    staff, other_staff = [identities["users"][("department_staff", True)][i] for i in range(2)]
    admin = identities["users"][("admin", True)][0]
    created = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen))
    assert created.status_code == 201
    ticket = created.json()["data"]["ticket"]
    ticket_id = ticket["ticket_id"]
    assert ticket["status"] == "pending" and ticket["occurred_at_precision"] == "part_of_day"
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(other_citizen)).status_code == 403
    accepted = client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "材料完整，予以受理"}, headers=auth(agent))
    assert accepted.status_code == 200
    contact = client.patch(f"/api/v1/tickets/{ticket_id}/contact", json={"version": 2, "remark": "市民确认新号码", "contact": "13900000000"}, headers=auth(citizen))
    assert contact.status_code == 200
    assigned = client.post(f"/api/v1/tickets/{ticket_id}/assign", json={"version": 3, "remark": "派发综合承办", "department_id": staff["department_id"], "assigned_user_id": staff["id"]}, headers=auth(agent))
    assert assigned.status_code == 200
    mine = client.get("/api/v1/tickets", params={"mine": True}, headers=auth(staff)).json()["data"]
    assert ticket_id in {item["ticket_id"] for item in mine["items"]}
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(other_staff)).status_code == 403
    processing = client.post(f"/api/v1/tickets/{ticket_id}/process", json={"version": 4, "remark": "现场核查"}, headers=auth(staff))
    assert processing.status_code == 200
    noted = client.post(f"/api/v1/tickets/{ticket_id}/note", json={"version": 5, "remark": "已联系施工方并完成首次整改"}, headers=auth(staff))
    assert noted.status_code == 200 and noted.json()["data"]["status"] == "processing"
    # P0-A: submit work order result, then summarize, then agent reviews and resolves.
    detail_before = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(staff)).json()["data"]
    primary = next(item for item in detail_before["work_orders"] if item["task_type"] == "primary")
    assert client.post(f"/api/v1/tickets/{ticket_id}/work-orders/{primary['id']}/submit", json={
        "version": primary["version"], "remark": "处置完成",
        "result_summary": "施工噪声整改完成", "result_measures": "约谈施工单位并调整夜间施工安排",
        "result_outcome": "resolved", "public_content": "现场整改已完成，夜间施工已停止",
        "internal_note": "内部联络记录 123",
    }, headers=auth(staff)).status_code == 200
    detail_after_submit = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(staff)).json()["data"]
    summarized = client.post(f"/api/v1/tickets/{ticket_id}/summary", json={
        "version": detail_after_submit["version"], "remark": "内部复核通过", "resolution_summary": "施工噪声整改完成",
        "resolution_measures": "约谈施工单位并调整夜间施工安排", "resolution_outcome": "resolved",
        "public_reply": "现场整改已完成，夜间施工已停止", "internal_note": "内部联络记录 123",
    }, headers=auth(staff))
    assert summarized.status_code == 200 and summarized.json()["data"]["collaboration_status"] == "awaiting_review"
    resolved = client.post(f"/api/v1/tickets/{ticket_id}/review-resolve", json={
        "version": summarized.json()["data"]["version"], "remark": "坐席审核办结",
        "resolution_summary": "施工噪声整改完成",
        "resolution_measures": "约谈施工单位并调整夜间施工安排", "resolution_outcome": "resolved",
        "public_reply": "现场整改已完成，夜间施工已停止", "internal_note": "内部联络记录 123",
    }, headers=auth(agent))
    assert resolved.status_code == 200
    owner_view = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(citizen))
    assert owner_view.status_code == 200 and owner_view.json()["data"]["status"] == "resolved"
    assert "internal_note" not in owner_view.json()["data"]
    assert "内部联络记录" not in str(owner_view.json()["data"]["history"])
    closed = client.post(f"/api/v1/tickets/{ticket_id}/feedback", json={"version": resolved.json()["data"]["version"], "rating": "satisfied", "comment": "处理及时"}, headers=auth(citizen))
    assert closed.status_code == 200 and closed.json()["data"]["status"] == "closed"
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(admin)).json()["data"]
    assert detail["internal_note"] == "内部联络记录 123"
    assert detail["closure_type"] == "citizen_confirmed"
    assert [x["operation_type"] for x in detail["history"]] == ["create", "accept", "update_contact", "assign", "process", "note", "submit_for_review", "review_resolve", "citizen_feedback"]
    assert detail["feedbacks"][0]["rating"] == "satisfied"
    assert all(x["content"] for x in detail["history"])
    with SessionLocal() as db:
        logs = list(db.scalars(select(AuditLogModel).where(AuditLogModel.resource_id == ticket_id)).all())
        assert {x.action for x in logs} >= {"create_ticket", "accept_ticket", "assign_ticket", "change_ticket_status", "update_ticket_contact", "permission_denied", "submit_ticket_feedback"}
        assert all("password" not in (x.details or "").lower() for x in logs)


def test_citizen_can_view_rasa_ticket_bound_to_stable_sender(identities):
    citizen, other_citizen = identities["users"][("citizen", True)]
    data = ticket_payload() | {"creator_reference": f"web-user-{citizen['id']}"}
    created = client.post(
        "/api/v1/tickets",
        json=data,
        headers={"Authorization": f"Bearer {get_settings().service_api_token}"},
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(citizen)).status_code == 200
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(other_citizen)).status_code == 403
    mine = client.get("/api/v1/tickets", params={"mine": True}, headers=auth(citizen))
    assert ticket_id in {item["ticket_id"] for item in mine.json()["data"]["items"]}


def test_illegal_reject_return_and_version_conflict(identities):
    citizen = identities["users"][("citizen", True)][0]
    agent = identities["users"][("agent", True)][0]
    staff = identities["users"][("department_staff", True)][0]
    admin = identities["users"][("admin", True)][0]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    illegal = client.post(f"/api/v1/tickets/{ticket_id}/resolve", json={
        "version": 1, "remark": "非法跳转", "resolution_summary": "暂无",
        "resolution_measures": "暂无", "resolution_outcome": "unresolved", "public_reply": "无处理结果",
    }, headers=auth(admin))
    assert illegal.status_code == 409 and illegal.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent)).status_code == 200
    stale = client.post(f"/api/v1/tickets/{ticket_id}/assign", json={"version": 1, "remark": "旧版本", "department_id": staff["department_id"]}, headers=auth(agent))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert client.post(f"/api/v1/tickets/{ticket_id}/assign", json={"version": 2, "remark": "派发", "department_id": staff["department_id"]}, headers=auth(agent)).status_code == 200
    assert client.post(f"/api/v1/tickets/{ticket_id}/process", json={"version": 3, "remark": "处理"}, headers=auth(staff)).status_code == 200
    resolve_payload = {
        "version": 4, "remark": "解决", "resolution_summary": "完成处理",
        "resolution_measures": "现场处理", "resolution_outcome": "resolved", "public_reply": "问题已处理",
    }
    # P0-A: department staff cannot /resolve anymore; must submit work order, then summary + review-resolve.
    assert client.post(f"/api/v1/tickets/{ticket_id}/resolve", json=resolve_payload, headers=auth(staff)).status_code == 403
    detail_before = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(staff)).json()["data"]
    primary = next(item for item in detail_before["work_orders"] if item["task_type"] == "primary")
    assert client.post(f"/api/v1/tickets/{ticket_id}/work-orders/{primary['id']}/submit", json={
        "version": primary["version"], "remark": "处置完成",
        "result_summary": "完成处理", "result_measures": "现场处理",
        "result_outcome": "resolved", "public_content": "问题已处理",
    }, headers=auth(staff)).status_code == 200
    detail_after_submit = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(staff)).json()["data"]
    summarized = client.post(f"/api/v1/tickets/{ticket_id}/summary", json=resolve_payload | {"version": detail_after_submit["version"]}, headers=auth(staff))
    assert summarized.status_code == 200 and summarized.json()["data"]["collaboration_status"] == "awaiting_review"
    resolved = client.post(f"/api/v1/tickets/{ticket_id}/review-resolve", json=resolve_payload | {"version": summarized.json()["data"]["version"]}, headers=auth(agent))
    assert resolved.status_code == 200 and resolved.json()["data"]["status"] == "resolved"
    # P0-B: dissatisfied feedback no longer reopens; status stays resolved.
    returned = client.post(f"/api/v1/tickets/{ticket_id}/feedback", json={"version": resolved.json()["data"]["version"], "rating": "dissatisfied", "comment": "现场问题仍然存在"}, headers=auth(citizen))
    assert returned.status_code == 200 and returned.json()["data"]["status"] == "resolved"
    # P0-A: staff still cannot /resolve (and ticket is already resolved).
    assert client.post(f"/api/v1/tickets/{ticket_id}/resolve", json=resolve_payload | {"version": returned.json()["data"]["version"], "public_reply": "已进行第二次处理"}, headers=auth(staff)).status_code == 403
    override = client.post(f"/api/v1/tickets/{ticket_id}/close", json={
        "version": returned.json()["data"]["version"], "remark": "依据回访记录代办结", "override_reason": "已完成处理且电话回访确认",
    }, headers=auth(admin))
    assert override.status_code == 200 and override.json()["data"]["closure_type"] == "admin_override"

    reject_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    rejected = client.post(f"/api/v1/tickets/{reject_id}/reject", json={
        "version": 1, "remark": "坐席审查不予受理", "reason_code": "out_of_scope",
        "rejection_detail": "该事项不属于本平台受理范围", "suggested_channel": "请联系相关市场主体",
        "needs_supplement": False,
    }, headers=auth(agent))
    assert rejected.status_code == 200 and rejected.json()["data"]["status"] == "rejected"


def test_inactive_department_and_scoped_lists(identities):
    citizen = identities["users"][("citizen", True)][0]
    agent = identities["users"][("agent", True)][0]
    department = identities["departments"][0]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    with SessionLocal() as db:
        persisted = db.get(DepartmentModel, department.id)
        persisted.is_active = False
        db.commit()
    try:
        response = client.post(f"/api/v1/tickets/{ticket_id}/assign", json={"version": 2, "remark": "派发", "department_id": department.id}, headers=auth(agent))
        assert response.status_code == 409 and response.json()["error"]["code"] == "DEPARTMENT_INACTIVE"
    finally:
        with SessionLocal() as db:
            persisted = db.get(DepartmentModel, department.id)
            persisted.is_active = True
            db.commit()
    departments = client.get("/api/v1/departments", headers=auth(agent))
    assert departments.status_code == 200 and len(departments.json()["data"]) >= 7
    page = client.get("/api/v1/tickets", params={"page": 1, "page_size": 2, "status": "accepted"}, headers=auth(agent)).json()["data"]
    assert len(page["items"]) <= 2 and page["page_size"] == 2


def test_admin_manages_users_and_departments(identities):
    admin = identities["users"][("admin", True)][0]
    agent = identities["users"][("agent", True)][0]
    suffix = uuid4().hex[:8]
    assert client.get("/api/v1/users", headers=auth(agent)).status_code == 403
    department = client.post("/api/v1/departments", json={
        "code": f"round4-{suffix}", "name": f"第四轮测试部门{suffix}", "description": "仅用于自动化测试",
    }, headers=auth(admin))
    assert department.status_code == 201
    department_id = department.json()["data"]["id"]
    username = f"managed_{suffix}"
    user = client.post("/api/v1/users", json={
        "username": username, "password": PASSWORD, "display_name": "受管部门人员",
        "role": "department_staff", "department_id": department_id,
    }, headers=auth(admin))
    assert user.status_code == 201
    user_id = user.json()["data"]["id"]
    assert client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
    disabled = client.patch(f"/api/v1/users/{user_id}", json={"is_active": False}, headers=auth(admin))
    assert disabled.status_code == 200 and disabled.json()["data"]["is_active"] is False
    assert client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).status_code == 401
    stopped = client.patch(f"/api/v1/departments/{department_id}", json={"is_active": False}, headers=auth(admin))
    assert stopped.status_code == 200 and stopped.json()["data"]["is_active"] is False


@pytest.mark.parametrize("text,precision", [
    ("昨天晚上", "part_of_day"), ("三天前", "day"), ("上周一", "day"), ("最近一个月", "range"),
])
def test_time_normalization(text, precision):
    reference = datetime(2026, 3, 1, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = normalize_chinese_time(text, "Asia/Shanghai", reference)
    assert result and result.precision == precision and result.start.utcoffset() == timedelta(hours=8)
    assert result.start < result.end


def test_unparseable_time_is_not_guessed_and_timezone_boundary():
    assert normalize_chinese_time("前些日子", "Asia/Shanghai") is None
    reference = datetime(2026, 1, 1, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = normalize_chinese_time("昨天晚上", "Asia/Shanghai", reference)
    assert result.start.year == 2025 and result.end.year == 2026
