from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import AuditLogModel, DepartmentModel, TicketModel, UserModel
from app.security import create_access_token, hash_password


client = TestClient(app)
PASSWORD = "Phase5-Pytest-Only!"


@pytest.fixture(scope="module")
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        department = db.scalar(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).limit(1))
        assert department
        result = {}
        for name, role, department_id in (
            ("citizen", "citizen", None), ("agent", "agent", None),
            ("admin", "admin", None), ("staff", "department_staff", department.id),
        ):
            user = UserModel(
                username=f"phase5_{name}_{suffix}", password_hash=hash_password(PASSWORD),
                display_name=f"phase5-{name}", role=role, department_id=department_id, is_active=True,
            )
            db.add(user)
            db.flush()
            result[name] = {"id": user.id, "role": role, "department_id": department_id}
        db.commit()
    result["department_id"] = department.id
    return result


def auth(actor):
    return {"Authorization": f"Bearer {create_access_token(actor['id'], actor['role'])}"}


def request(method, path, actor, payload=None):
    response = client.request(method, path, headers=auth(actor), json=payload)
    assert response.status_code < 400, response.text
    return response.json()["data"]


def resolve_ticket(actors, label):
    ticket = request("POST", "/api/v1/tickets", actors["citizen"], {
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": f"{label}阶段五闭环验证事项", "location": "幸福路社区", "source": "phase5-pytest",
    })["ticket"]
    ticket = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/accept", actors["agent"], {
        "version": ticket["version"], "remark": "核实后受理", "priority": "normal",
    })
    ticket = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/assign", actors["agent"], {
        "version": ticket["version"], "remark": "派发责任部门", "department_id": actors["department_id"],
        "assigned_user_id": actors["staff"]["id"],
    })
    ticket = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/process", actors["staff"], {
        "version": ticket["version"], "remark": "开始现场处置",
    })
    # P0-A: submit work order result, then summarize, then agent reviews and resolves.
    detail = request("GET", f"/api/v1/tickets/{ticket['ticket_id']}", actors["staff"])
    primary = next(item for item in detail["work_orders"] if item["task_type"] == "primary")
    request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/work-orders/{primary['id']}/submit", actors["staff"], {
        "version": primary["version"], "remark": "处置完成",
        "result_summary": "事项已经处理", "result_measures": "完成现场处置并复核",
        "result_outcome": "resolved", "public_content": "问题已经处理完成，请确认。",
    })
    # Re-fetch to get the latest ticket version (work order submit bumps ticket.version).
    detail = request("GET", f"/api/v1/tickets/{ticket['ticket_id']}", actors["staff"])
    ticket = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/summary", actors["staff"], {
        "version": detail["version"], "remark": "部门复核通过",
        "resolution_summary": "事项已经处理", "resolution_measures": "完成现场处置并复核",
        "resolution_outcome": "resolved", "public_reply": "问题已经处理完成，请确认。",
    })
    return request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/review-resolve", actors["agent"], {
        "version": ticket["version"], "remark": "坐席审核办结",
        "resolution_summary": "事项已经处理", "resolution_measures": "完成现场处置并复核",
        "resolution_outcome": "resolved", "public_reply": "问题已经处理完成，请确认。",
    })


def test_notifications_and_phone_follow_up_close(actors):
    ticket = resolve_ticket(actors, "通知回访")
    notifications = request("GET", "/api/v1/notifications?page_size=100", actors["citizen"])
    event_types = {item["event_type"] for item in notifications["items"] if item["ticket_id"] == ticket["ticket_id"]}
    assert {
        "ticket_created", "ticket_accepted", "ticket_assigned",
        "processing_completed", "awaiting_confirmation",
    }.issubset(event_types)
    assert notifications["unread_count"] >= 5

    follow_ups = request("GET", "/api/v1/follow-ups?page_size=100", actors["agent"])
    task = next(item for item in follow_ups["items"] if item["ticket_id"] == ticket["ticket_id"])
    assert task["status"] == "pending" and task["handling_round"] == 1
    task = request("POST", f"/api/v1/follow-ups/{task['id']}/phone-record", actors["agent"], {
        "ticket_version": ticket["version"], "contact_result": "no_answer",
        "outcome": "needs_followup", "notes": "首次拨打无人接听，稍后再次联系",
    })
    assert task["status"] == "in_progress" and len(task["records"]) == 1
    task = request("POST", f"/api/v1/follow-ups/{task['id']}/phone-record", actors["agent"], {
        "ticket_version": ticket["version"], "contact_result": "reached", "satisfaction": "satisfied",
        "outcome": "confirmed", "notes": "市民确认处理结果满意，同意办结",
    })
    assert task["status"] == "completed" and len(task["records"]) == 2
    detail = request("GET", f"/api/v1/tickets/{ticket['ticket_id']}", actors["citizen"])
    assert detail["status"] == "closed" and detail["closure_type"] == "phone_confirmed"


def test_appeal_review_reprocess_result_and_limit(actors):
    ticket = resolve_ticket(actors, "申诉重办")
    appeal = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/appeals", actors["citizen"], {
        "reason": "首次处理未覆盖夜间噪声反复出现的问题", "desired_resolution": "请在夜间再次现场核查",
    })
    assert appeal["status"] == "submitted" and appeal["sequence"] == 1
    denied = client.post(f"/api/v1/appeals/{appeal['id']}/review", headers=auth(actors["agent"]), json={
        "decision": "approved", "review_comment": "同意重新核查", "reprocess_instructions": "安排夜间复查",
    })
    assert denied.status_code == 403
    appeal = request("POST", f"/api/v1/appeals/{appeal['id']}/review", actors["admin"], {
        "decision": "approved", "review_comment": "申诉事实清楚，同意重新办理",
        "reprocess_instructions": "安排夜间复查并公开复查结果",
    })
    assert appeal["status"] == "reprocessing"
    tasks_after_review = request("GET", "/api/v1/follow-ups?page_size=100", actors["agent"])["items"]
    previous_task = next(item for item in tasks_after_review if item["ticket_id"] == ticket["ticket_id"])
    assert previous_task["status"] == "cancelled"
    detail = request("GET", f"/api/v1/tickets/{ticket['ticket_id']}", actors["staff"])
    assert detail["status"] == "processing" and detail["handling_round"] == 2
    # P0-A: appeal reprocess also uses submit + summary + review-resolve (staff cannot self-resolve).
    primary = next(item for item in detail["work_orders"] if item["task_type"] == "primary")
    request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/work-orders/{primary['id']}/submit", actors["staff"], {
        "version": primary["version"], "remark": "处置完成",
        "result_summary": "夜间复查完成", "result_measures": "夜间驻点核查并完成整改",
        "result_outcome": "resolved", "public_content": "已完成夜间复查，问题已整改。",
    })
    detail = request("GET", f"/api/v1/tickets/{ticket['ticket_id']}", actors["staff"])
    detail = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/summary", actors["staff"], {
        "version": detail["version"], "remark": "重新办理复核通过",
        "resolution_summary": "夜间复查完成", "resolution_measures": "夜间驻点核查并完成整改",
        "resolution_outcome": "resolved", "public_reply": "已完成夜间复查，问题已整改。",
    })
    detail = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/review-resolve", actors["agent"], {
        "version": detail["version"], "remark": "坐席审核办结",
        "resolution_summary": "夜间复查完成", "resolution_measures": "夜间驻点核查并完成整改",
        "resolution_outcome": "resolved", "public_reply": "已完成夜间复查，问题已整改。",
    })
    appeals = request("GET", "/api/v1/appeals?page_size=100", actors["citizen"])
    completed = next(item for item in appeals["items"] if item["id"] == appeal["id"])
    assert completed["status"] == "completed" and "夜间复查" in completed["result_summary"]

    second = request("POST", f"/api/v1/tickets/{ticket['ticket_id']}/appeals", actors["citizen"], {
        "reason": "第二次申诉用于验证次数上限和审核终态规则", "desired_resolution": "请给出书面审核结论",
    })
    request("POST", f"/api/v1/appeals/{second['id']}/review", actors["admin"], {
        "decision": "rejected", "review_comment": "现有重新办理证据充分，维持处理结果",
    })
    limited = client.post(f"/api/v1/tickets/{ticket['ticket_id']}/appeals", headers=auth(actors["citizen"]), json={
        "reason": "第三次申诉应当被申诉次数业务规则明确阻止", "desired_resolution": "继续申诉",
    })
    assert limited.status_code == 409
    assert limited.json()["error"]["code"] == "APPEAL_LIMIT_REACHED"

    follow_up_denied = client.get("/api/v1/follow-ups", headers=auth(actors["staff"]))
    assert follow_up_denied.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TicketModel).where(
            (TicketModel.handling_round.is_(None)) | (TicketModel.appeal_count.is_(None))
        )) == 0
        actions = set(db.scalars(select(AuditLogModel.action).where(
            AuditLogModel.resource_id.in_((appeal["id"], second["id"])),
        )).all())
        assert {"submit_appeal", "review_appeal", "complete_appeal"}.issubset(actions)
