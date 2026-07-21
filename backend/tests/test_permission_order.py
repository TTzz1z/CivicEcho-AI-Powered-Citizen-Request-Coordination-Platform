"""P0-R4 regression: permission check MUST come before version check.

Before this fix, `_transition` (and `submit_feedback`/`update_contact`/`pause_sla`/`resume_sla`/`remind`)
checked `ticket.version != version` first, returning `VERSION_CONFLICT` (409).
A caller without the required role could therefore enumerate the current
version of any ticket by observing the difference between `VERSION_CONFLICT`
and `PERMISSION_DENIED`.

After the fix, an unauthorized caller MUST receive `403 PERMISSION_DENIED`
regardless of whether the version matches or not.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import DepartmentModel, UserModel
from app.security import create_access_token, hash_password

client = TestClient(app)
PASSWORD = "PermOrder-Test-Only!"


@pytest.fixture(scope="module")
def identities():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        departments = list(db.scalars(select(DepartmentModel).order_by(DepartmentModel.id).limit(2)).all())
        users = {}
        for role, department in [
            ("citizen", None), ("citizen", None), ("agent", None),
            ("department_staff", departments[0]), ("department_staff", departments[1]),
            ("admin", None),
        ]:
            username = f"po_{role}_{suffix}_{len(users)}"
            user = UserModel(
                username=username, password_hash=hash_password(PASSWORD), display_name=username,
                role=role, department_id=department.id if department else None, is_active=True,
            )
            db.add(user)
            db.flush()
            users[username] = {
                "id": user.id, "username": username, "role": role,
                "department_id": user.department_id,
            }
        db.commit()
    by_role = {}
    for value in users.values():
        by_role.setdefault(value["role"], []).append(value)
    return {"users": by_role, "departments": departments}


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(user['id'], user['role'])}"}


def ticket_payload():
    return {
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": "权限顺序回归测试", "location": "测试路",
        "occurred_at": "昨天晚上", "contact": "13800000000", "source": "pytest",
    }


def test_transition_permission_before_version_citizen_cannot_accept(identities):
    """citizen has no accept permission. Both stale and correct version must return 403."""
    citizen, _ = identities["users"]["citizen"]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    # Stale version (e.g. 999) — must still be 403, NOT 409 VERSION_CONFLICT.
    stale = client.post(f"/api/v1/tickets/{ticket_id}/accept",
                        json={"version": 999, "remark": "x"}, headers=auth(citizen))
    assert stale.status_code == 403, f"expected 403, got {stale.status_code}: {stale.text}"
    assert stale.json()["error"]["code"] == "PERMISSION_DENIED"
    # Correct version (1) — must also be 403.
    correct = client.post(f"/api/v1/tickets/{ticket_id}/accept",
                          json={"version": 1, "remark": "x"}, headers=auth(citizen))
    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "PERMISSION_DENIED"


def test_transition_permission_before_version_dept_cannot_accept(identities):
    """department_staff has no accept permission. Same invariant as above."""
    citizen = identities["users"]["citizen"][0]
    staff = identities["users"]["department_staff"][0]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    stale = client.post(f"/api/v1/tickets/{ticket_id}/accept",
                        json={"version": 999, "remark": "x"}, headers=auth(staff))
    assert stale.status_code == 403
    assert stale.json()["error"]["code"] == "PERMISSION_DENIED"
    correct = client.post(f"/api/v1/tickets/{ticket_id}/accept",
                          json={"version": 1, "remark": "x"}, headers=auth(staff))
    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "PERMISSION_DENIED"


def test_transition_permission_before_version_other_department_cannot_process(identities):
    """department_staff from another department must get 403 on process regardless of version."""
    citizen = identities["users"]["citizen"][0]
    agent = identities["users"]["agent"][0]
    staff_a, staff_b = identities["users"]["department_staff"]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    client.post(f"/api/v1/tickets/{ticket_id}/assign",
                json={"version": 2, "remark": "派发 A", "department_id": staff_a["department_id"]},
                headers=auth(agent))
    # staff_b (different department) tries process with stale version
    stale = client.post(f"/api/v1/tickets/{ticket_id}/process",
                        json={"version": 999, "remark": "x"}, headers=auth(staff_b))
    assert stale.status_code == 403
    assert stale.json()["error"]["code"] == "PERMISSION_DENIED"
    # and with correct version (3)
    correct = client.post(f"/api/v1/tickets/{ticket_id}/process",
                          json={"version": 3, "remark": "x"}, headers=auth(staff_b))
    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "PERMISSION_DENIED"


def test_authorized_caller_still_gets_version_conflict_on_stale_version(identities):
    """Authorized caller with stale version must still get 409 VERSION_CONFLICT."""
    citizen = identities["users"]["citizen"][0]
    agent = identities["users"]["agent"][0]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    # agent is authorized to assign; stale version 1 must return 409 (current is 2)
    stale = client.post(f"/api/v1/tickets/{ticket_id}/assign",
                        json={"version": 1, "remark": "x", "department_id": identities["departments"][0].id},
                        headers=auth(agent))
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_feedback_permission_before_version(identities):
    """citizen can only feedback own tickets; other citizens get 403 regardless of version."""
    citizen, other_citizen = identities["users"]["citizen"]
    agent = identities["users"]["agent"][0]
    staff = identities["users"]["department_staff"][0]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    client.post(f"/api/v1/tickets/{ticket_id}/assign",
                json={"version": 2, "remark": "派发", "department_id": staff["department_id"]},
                headers=auth(agent))
    client.post(f"/api/v1/tickets/{ticket_id}/process", json={"version": 3, "remark": "处理"}, headers=auth(staff))
    # other_citizen tries feedback with stale and correct version
    stale = client.post(f"/api/v1/tickets/{ticket_id}/feedback",
                        json={"version": 999, "rating": "satisfied", "comment": "x"},
                        headers=auth(other_citizen))
    assert stale.status_code == 403
    assert stale.json()["error"]["code"] == "PERMISSION_DENIED"
    correct = client.post(f"/api/v1/tickets/{ticket_id}/feedback",
                          json={"version": 4, "rating": "satisfied", "comment": "x"},
                          headers=auth(other_citizen))
    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "PERMISSION_DENIED"


def test_pause_resume_sla_permission_before_version(identities):
    """department_staff from another dept cannot pause/resume SLA regardless of version."""
    citizen = identities["users"]["citizen"][0]
    agent = identities["users"]["agent"][0]
    staff_a, staff_b = identities["users"]["department_staff"]
    ticket_id = client.post("/api/v1/tickets", json=ticket_payload(), headers=auth(citizen)).json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", json={"version": 1, "remark": "受理"}, headers=auth(agent))
    client.post(f"/api/v1/tickets/{ticket_id}/assign",
                json={"version": 2, "remark": "派发 A", "department_id": staff_a["department_id"]},
                headers=auth(agent))
    # staff_b tries pause with stale version
    stale = client.post(f"/api/v1/tickets/{ticket_id}/sla/pause",
                        json={"version": 999, "remark": "x", "reason": "test"}, headers=auth(staff_b))
    assert stale.status_code == 403
    # and with correct version
    correct = client.post(f"/api/v1/tickets/{ticket_id}/sla/pause",
                          json={"version": 3, "remark": "x", "reason": "test"}, headers=auth(staff_b))
    assert correct.status_code == 403
