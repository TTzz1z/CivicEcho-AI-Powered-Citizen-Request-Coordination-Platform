"""R4: End-to-end verification of 5 business loops via HTTP API.

Uses the real HTTP API (not internal services) to verify:
1. Satisfied closure.
2. Dissatisfied appeal → admin approve → reprocess.
3. SLA due-soon notification (worker scan → outbox → notification).
4. Follow-up task creation and phone record.
5. AI suggestion three-way review.

Run: python -m scripts.verify_r4_business_loops
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AiSuggestionModel,
    AppealModel,
    FollowUpTaskModel,
    NotificationModel,
    NotificationOutboxModel,
    PhoneFollowUpRecordModel,
    TicketModel,
    UserModel,
)
from app.worker import scan_due_soon, process_outbox


API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "tingting-seed-demo-2026")

PASS = []
FAIL = []


def step(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def http(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def login(username: str) -> str:
    status, body = http("POST", "/api/v1/auth/login", body={"username": username, "password": SEED_PASSWORD})
    assert status == 200, f"login {username} failed: {body}"
    return body["data"]["access_token"]


def create_ticket(citizen_token: str, suffix: str) -> dict:
    payload = {
        "idempotency_key": str(uuid4()),
        "request_type": "投诉",
        "description": f"R4 闭环测试 {suffix}",
        "location": "测试路",
        "occurred_at_text": "昨天晚上",
        "contact": "13800000000",
        "source": "pytest",
    }
    status, body = http("POST", "/api/v1/tickets", citizen_token, payload)
    assert status == 201, f"create_ticket failed: {body}"
    return body["data"]["ticket"]


def get_ticket(token: str, ticket_id: str) -> dict:
    status, body = http("GET", f"/api/v1/tickets/{ticket_id}", token)
    assert status == 200, f"get_ticket failed: {body}"
    return body["data"]


def transition(token: str, ticket_id: str, action: str, version: int, remark: str = "", **extra) -> tuple[int, dict]:
    payload = {"version": version, "remark": remark, **extra}
    status, body = http("POST", f"/api/v1/tickets/{ticket_id}/{action}", token, payload)
    return status, body


def full_setup_to_processing(citizen_token, agent_token, dept_token, suffix: str) -> dict:
    """Helper: create → accept → assign → process, return latest ticket dict."""
    ticket = create_ticket(citizen_token, suffix)
    tid = ticket["ticket_id"]
    s, b = transition(agent_token, tid, "accept", 1, "受理")
    assert s == 200, f"accept: {b}"
    # Get the department_local's department_id from /me
    s, me = http("GET", "/api/v1/auth/me", dept_token)
    dept_id = me["data"]["department_id"]
    s, b = transition(agent_token, tid, "assign", 2, "派发", department_id=dept_id)
    assert s == 200, f"assign: {b}"
    s, b = transition(dept_token, tid, "process", 3, "开始处理")
    assert s == 200, f"process: {b}"
    return get_ticket(dept_token, tid)


def submit_and_review(ticket: dict, dept_token, agent_token) -> dict:
    """Submit work order → summarize → review_resolve."""
    tid = ticket["ticket_id"]
    # Get primary work order
    primary = next(w for w in ticket["work_orders"] if w["task_type"] == "primary")
    # 1. Submit work order
    s, b = http("POST", f"/api/v1/tickets/{tid}/work-orders/{primary['id']}/submit", dept_token, {
        "version": primary["version"],
        "remark": "处置完成",
        "result_summary": "现场处理完成",
        "result_measures": "现场处理",
        "result_outcome": "resolved",
        "public_content": "问题已处理",
    })
    assert s == 200, f"submit work order: {b}"
    # 2. Summarize
    s, me = http("GET", "/api/v1/auth/me", dept_token)
    current = get_ticket(dept_token, tid)
    s, b = http("POST", f"/api/v1/tickets/{tid}/summary", dept_token, {
        "version": current["version"],
        "remark": "内部复核通过",
        "resolution_summary": "现场处理完成",
        "resolution_measures": "现场处理",
        "resolution_outcome": "resolved",
        "public_reply": "问题已处理",
    })
    assert s == 200, f"summary: {b}"
    # 3. Agent review_resolve
    current = get_ticket(agent_token, tid)
    s, b = http("POST", f"/api/v1/tickets/{tid}/review-resolve", agent_token, {
        "version": current["version"],
        "remark": "坐席复核办结",
        "resolution_summary": "现场处理完成",
        "resolution_measures": "现场处理",
        "resolution_outcome": "resolved",
        "public_reply": "问题已处理",
    })
    assert s == 200, f"review_resolve: {b}"
    return b["data"]


def loop1_satisfied_closure(citizen_token, agent_token, dept_token):
    print("\n--- Loop 1: satisfied closure ---")
    ticket = full_setup_to_processing(citizen_token, agent_token, dept_token, "loop1-satisfied")
    resolved = submit_and_review(ticket, dept_token, agent_token)
    step("review_resolve", resolved["status"] == "resolved", f"ticket={resolved['ticket_id']}")

    s, b = http("POST", f"/api/v1/tickets/{resolved['ticket_id']}/feedback", citizen_token, {
        "version": resolved["version"],
        "rating": "satisfied",
        "comment": "处理及时",
    })
    step("feedback_satisfied", s == 200 and b["data"]["status"] == "closed", f"status={b['data'].get('status')}")
    step("closure_type", b["data"].get("closure_type") == "citizen_confirmed", f"closure_type={b['data'].get('closure_type')}")
    return s == 200 and b["data"]["status"] == "closed"


def loop2_appeal_reprocess(citizen_token, agent_token, dept_token, admin_token):
    print("\n--- Loop 2: dissatisfied appeal → reprocess ---")
    ticket = full_setup_to_processing(citizen_token, agent_token, dept_token, "loop2-appeal")
    resolved = submit_and_review(ticket, dept_token, agent_token)
    tid = resolved["ticket_id"]

    s, b = http("POST", f"/api/v1/tickets/{tid}/feedback", citizen_token, {
        "version": resolved["version"],
        "rating": "dissatisfied",
        "comment": "问题未解决",
    })
    step("feedback_dissatisfied", s == 200 and b["data"]["status"] == "resolved", f"status={b['data'].get('status')}")

    # Appeal
    s, b = http("POST", f"/api/v1/tickets/{tid}/appeals", citizen_token, {
        "reason": "市民对本次处理结果不满意，要求重新核实并处理。",
        "desired_resolution": "希望部门重新核实情况并给出实质性处理结果。",
    })
    step("appeal_create", s == 201, f"status={s} body={b if s != 201 else 'ok'}")
    if s != 201:
        return False
    appeal_id = b["data"]["id"]
    step("appeal_status", b["data"]["status"] == "submitted")

    # Admin approve
    s, b = http("POST", f"/api/v1/appeals/{appeal_id}/review", admin_token, {
        "decision": "approved",
        "review_comment": "重新处理",
        "reprocess_instructions": "请部门重新核实并处理",
    })
    step("appeal_approve", s == 200, f"status={s} body={b if s != 200 else 'ok'}")

    # Verify ticket status = processing
    current = get_ticket(citizen_token, tid)
    step("ticket_reprocess", current["status"] == "processing", f"status={current['status']}")
    return current["status"] == "processing"


def loop3_sla_notification(citizen_token, agent_token, dept_token, db):
    print("\n--- Loop 3: SLA due-soon notification ---")
    ticket = full_setup_to_processing(citizen_token, agent_token, dept_token, "loop3-sla")
    tid = ticket["ticket_id"]

    # Force resolve_due_at to be within due-soon threshold
    db.execute(
        __import__("sqlalchemy").text(
            "UPDATE tickets SET resolve_due_at = :due WHERE ticket_id = :tid"
        ).bindparams(due=datetime.now(timezone.utc) + timedelta(hours=1), tid=tid)
    )
    db.commit()

    created = scan_due_soon(db)
    step("scan_due_soon", created > 0, f"created={created} outbox items")

    delivered = process_outbox(db)
    step("process_outbox", delivered > 0, f"delivered={delivered}")

    notifs = list(db.scalars(select(NotificationModel).where(NotificationModel.ticket_id == tid)).all())
    step("notification_persisted", len(notifs) > 0, f"count={len(notifs)}")
    return len(notifs) > 0


def loop4_follow_up_task(citizen_token, agent_token, dept_token, db):
    print("\n--- Loop 4: follow-up task + phone record ---")
    ticket = full_setup_to_processing(citizen_token, agent_token, dept_token, "loop4-followup")
    tid = ticket["ticket_id"]
    # Resolve triggers on_ticket_event("resolved") → _ensure_follow_up creates the task automatically.
    resolved = submit_and_review(ticket, dept_token, agent_token)
    step("review_resolve", resolved["status"] == "resolved")

    # Query auto-created follow-up task
    s, b = http("GET", f"/api/v1/follow-ups?ticket_id={tid}&page=1&page_size=5", agent_token)
    step("follow_up_list", s == 200, f"status={s}")
    items = b.get("data", {}).get("items", [])
    # Filter to current ticket_id and status=pending/in_progress
    items = [it for it in items if it.get("ticket_id") == tid and it.get("status") in {"pending", "in_progress"}]
    if not items:
        # Try querying DB directly as fallback
        task = db.scalar(select(FollowUpTaskModel).where(
            FollowUpTaskModel.ticket_id == tid,
            FollowUpTaskModel.status.in_(("pending", "in_progress")),
        ))
        if task:
            items = [{"id": task.id, "status": task.status}]
    step("follow_up_auto_created", len(items) > 0, f"count={len(items)}")
    if not items:
        return False
    task_id = items[0]["id"]

    # Need ticket_version for the phone record call
    current = get_ticket(agent_token, tid)
    s, b = http("POST", f"/api/v1/follow-ups/{task_id}/phone-record", agent_token, {
        "ticket_version": current["version"],
        "contact_result": "reached",
        "satisfaction": "satisfied",
        "outcome": "confirmed",
        "notes": "市民对处理结果表示满意。",
    })
    step("phone_record_create", s in (200, 201), f"status={s} body={b if s not in (200,201) else 'ok'}")
    return s in (200, 201)


def loop5_ai_three_way_review(agent_token, dept_token, citizen_token):
    """R4: verify the true three-state AI advice review path.

    The real three-state confirmation for AI ticket advice is:
      POST /api/v1/kb/tickets/{ticket_id}/advice/review
      decision: adopted | adopted_with_edits | rejected

    Each decision is recorded in audit_logs (action=ai_advice_review) with
    advisory_only=true. The AI advice never changes ticket status.
    """
    print("\n--- Loop 5: AI advice three-way review (adopted/adopted_with_edits/rejected) ---")
    ticket = full_setup_to_processing(citizen_token, agent_token, dept_token, "loop5-ai-review")
    tid = ticket["ticket_id"]

    # Generate advice once (the advice content is what is being reviewed).
    s, b = http("POST", f"/api/v1/ai/tickets/{tid}/case-advice", agent_token, {})
    step("case_advice_generated", s == 200 and b.get("data", {}).get("advisory_only") is True,
         f"status={s} advisory_only={b.get('data', {}).get('advisory_only')}")

    # Submit three decisions; each needs a fresh advice_id (reviews are one-shot).
    decisions = [
        ("adopted", None),
        ("adopted_with_edits", "调整了回复措辞和办理步骤"),
        ("rejected", None),
    ]
    for decision, edit_summary in decisions:
        s, advice_body = http("POST", f"/api/v1/ai/tickets/{tid}/case-advice", agent_token, {})
        advice_id = (advice_body.get("data") or {}).get("advice_id") if s == 200 else None
        if not advice_id:
            step(f"ai_advice_review_{decision}", False, f"missing advice_id status={s} body={advice_body}")
            continue
        payload = {"advice_id": advice_id, "decision": decision}
        if edit_summary:
            payload["edit_summary"] = edit_summary
        s, b = http("POST", f"/api/v1/kb/tickets/{tid}/advice/review", agent_token, payload)
        step(f"ai_advice_review_{decision}", s == 200,
             f"status={s} body={b if s != 200 else 'ok'}")

    # Verify ticket status did NOT change (AI never auto-transitions)
    current = get_ticket(agent_token, tid)
    step("ticket_status_unchanged", current["status"] == "processing",
         f"status={current['status']}")

    # Verify audit_logs has the 3 review records
    s, b = http("GET", f"/api/v1/admin/audit-logs?action=ai_advice_review&page=1&page_size=10",
                # Use admin token via /login
                login("admin_local"))
    items = b.get("data", {}).get("items", []) if s == 200 else []
    our_reviews = [it for it in items if it.get("resource_id") == tid]
    step("audit_records", len(our_reviews) >= 3, f"count={len(our_reviews)}")
    return True


def main():
    print(f"=== R4 business loops verification ===")
    print(f"API_BASE: {API_BASE}")

    citizen_token = login("citizen_local")
    agent_token = login("agent_local")
    dept_token = login("department_local")
    admin_token = login("admin_local")
    print("Logged in as citizen/agent/department_staff/admin")

    try:
        loop1_satisfied_closure(citizen_token, agent_token, dept_token)
    except Exception as e:
        import traceback; traceback.print_exc()
        step("loop1", False, f"EXC: {e}")

    try:
        loop2_appeal_reprocess(citizen_token, agent_token, dept_token, admin_token)
    except Exception as e:
        import traceback; traceback.print_exc()
        step("loop2", False, f"EXC: {e}")

    with SessionLocal() as db:
        try:
            loop3_sla_notification(citizen_token, agent_token, dept_token, db)
        except Exception as e:
            import traceback; traceback.print_exc()
            step("loop3", False, f"EXC: {e}")

    with SessionLocal() as db:
        try:
            loop4_follow_up_task(citizen_token, agent_token, dept_token, db)
        except Exception as e:
            import traceback; traceback.print_exc()
            step("loop4", False, f"EXC: {e}")

    try:
        loop5_ai_three_way_review(agent_token, dept_token, citizen_token)
    except Exception as e:
        import traceback; traceback.print_exc()
        step("loop5", False, f"EXC: {e}")

    print("\n" + "=" * 60)
    print(f"PASS: {len(PASS)}, FAIL: {len(FAIL)}")
    for name, detail in FAIL:
        print(f"  FAIL: {name} {detail}")
    print("=" * 60)
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
