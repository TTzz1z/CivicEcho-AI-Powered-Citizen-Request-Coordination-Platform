"""Acceptance Main Flow: Cross-role complete loop test.

Validates the full ticket lifecycle:
1. Citizen submits ticket
2. Agent accepts
3. Agent assigns
4. Dept processes + submits work order (P0-A) + summarizes
5. Agent review-resolves
6. Citizen feedback (dissatisfied -> stays resolved, P0-B)
7. Citizen submits appeal
8. Admin approves appeal
9. Ticket returns to processing (round 2)
10. P0-A: Dept cannot self-resolve
"""

import json
import os
import sys
import time
import uuid

import requests

BASE = os.environ.get("ACCEPTANCE_BASE_URL", "http://localhost:8001/api/v1")
PASSWORD = os.environ.get("SEED_PASSWORD", "tingting-seed-demo-2026")

PASS = 0
FAIL = 0


def check(step: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        print(f"[PASS] {step}")
        PASS += 1
    else:
        print(f"[FAIL] {step} {detail}")
        FAIL += 1


def login(username: str) -> str:
    resp = requests.post(
        f"{BASE}/auth/login",
        json={"username": username, "password": PASSWORD},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    print("=== Acceptance Main Flow: Cross-role Complete Loop ===")

    # 1. Citizen submits ticket
    print("\n--- Step 1: Citizen submits ticket ---")
    citizen_token = login("citizen_local")
    idem_key = f"accept-main-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    create_body = {
        "idempotency_key": idem_key,
        "request_type": "投诉",
        "description": "Acceptance test: street light broken for 3 nights on Xingfu Road",
        "location": "Xingfu Road Community",
        "timezone": "Asia/Shanghai",
        "source": "acceptance-test",
    }
    resp = requests.post(
        f"{BASE}/tickets", json=create_body, headers=auth(citizen_token), timeout=30
    )
    resp.raise_for_status()
    ticket = resp.json()["data"]["ticket"]
    check("1. Citizen submit ticket", bool(ticket.get("ticket_id", "").startswith("QT")), f"ticket_id={ticket.get('ticket_id')}")
    check("1a. status=pending", ticket.get("status") == "pending", f"status={ticket.get('status')}")
    print(f"    ticket_id={ticket['ticket_id']}, version={ticket['version']}")

    # 2. Agent accepts
    print("\n--- Step 2: Agent accepts ---")
    agent_token = login("agent_local")
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/accept",
        json={"version": ticket["version"], "remark": "acceptance-accept", "priority": "normal"},
        headers=auth(agent_token),
        timeout=30,
    )
    resp.raise_for_status()
    accepted = resp.json()["data"]
    check("2. Agent accept", accepted["status"] == "accepted", f"status={accepted['status']}")

    # 3. Agent assigns
    print("\n--- Step 3: Agent assigns ---")
    resp = requests.get(f"{BASE}/departments", headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    departments = resp.json()["data"]
    # department_local belongs to "综合受理" (general-intake, id=7)
    dept_id = None
    for d in departments:
        if d.get("name") == "综合受理" or d.get("code") == "general-intake":
            dept_id = d["id"]
            break
    if not dept_id:
        dept_id = departments[0]["id"]
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/assign",
        json={"version": accepted["version"], "remark": "acceptance-assign", "department_id": dept_id},
        headers=auth(agent_token),
        timeout=30,
    )
    resp.raise_for_status()
    assigned = resp.json()["data"]
    check("3. Agent assign", assigned["status"] == "assigned", f"status={assigned['status']}")

    # 4. Dept processes and submits (P0-A)
    print("\n--- Step 4: Dept processes and submits (P0-A) ---")
    staff_token = login("department_local")
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/process",
        json={"version": assigned["version"], "remark": "acceptance-process"},
        headers=auth(staff_token),
        timeout=30,
    )
    resp.raise_for_status()
    processed = resp.json()["data"]
    check("4. Dept process", processed["status"] == "processing", f"status={processed['status']}")

    # P0-A: Dept submits work order result
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail1 = resp.json()["data"]
    primary = next((w for w in detail1["work_orders"] if w["task_type"] == "primary"), None)
    submit_body = {
        "version": primary["version"],
        "remark": "acceptance-submit",
        "result_summary": "light fixed",
        "result_measures": "replaced lamp and tested",
        "result_outcome": "resolved",
        "public_content": "lamp replaced and lighting restored",
    }
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/work-orders/{primary['id']}/submit",
        json=submit_body,
        headers=auth(staff_token),
        timeout=30,
    )
    resp.raise_for_status()
    submitted = resp.json()["data"]
    check("4a. Dept submit work order", submitted.get("status") == "submitted", f"wo_status={submitted.get('status')}")

    # P0-A: Dept summarizes
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail2 = resp.json()["data"]
    summary_body = {
        "version": detail2["version"],
        "remark": "acceptance-summary",
        "resolution_summary": "light fixed",
        "resolution_measures": "replaced lamp and tested",
        "resolution_outcome": "resolved",
        "public_reply": "lamp replaced and lighting restored",
    }
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/summary",
        json=summary_body,
        headers=auth(staff_token),
        timeout=30,
    )
    resp.raise_for_status()
    summarized = resp.json()["data"]
    check("4b. Dept summarize", summarized.get("collaboration_status") == "awaiting_review", f"collab={summarized.get('collaboration_status')}")
    check("4c. Main ticket stays processing", summarized["status"] == "processing", f"status={summarized['status']}")

    # 5. Agent review-resolve
    print("\n--- Step 5: Agent review-resolve ---")
    resolve_body = {
        "version": summarized["version"],
        "remark": "acceptance-review-resolve",
        "resolution_summary": "light fixed",
        "resolution_measures": "replaced lamp and tested",
        "resolution_outcome": "resolved",
        "public_reply": "lamp replaced and lighting restored",
    }
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/review-resolve",
        json=resolve_body,
        headers=auth(agent_token),
        timeout=30,
    )
    resp.raise_for_status()
    resolved = resp.json()["data"]
    check("5. Agent review-resolve", resolved["status"] == "resolved", f"status={resolved['status']}")
    check("5a. collab=completed", resolved.get("collaboration_status") == "completed", f"collab={resolved.get('collaboration_status')}")

    # 6. Citizen feedback (dissatisfied, stays resolved - P0-B)
    print("\n--- Step 6: Citizen feedback (dissatisfied) ---")
    feedback_body = {"version": resolved["version"], "rating": "dissatisfied", "comment": "too slow"}
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/feedback",
        json=feedback_body,
        headers=auth(citizen_token),
        timeout=30,
    )
    resp.raise_for_status()
    feedback = resp.json()["data"]
    check("6. Citizen dissatisfied feedback", feedback["status"] == "resolved", f"status={feedback['status']}")
    # Fetch ticket detail to get feedbacks list (TicketRead doesn't include feedbacks)
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(citizen_token), timeout=30)
    resp.raise_for_status()
    detail_fb = resp.json()["data"]
    last_fb = detail_fb["feedbacks"][-1] if detail_fb.get("feedbacks") else {}
    check("6a. result=dissatisfied_recorded", last_fb.get("result") == "dissatisfied_recorded", f"result={last_fb.get('result')}")

    # 7. Citizen submits appeal
    print("\n--- Step 7: Citizen submits appeal ---")
    appeal_body = {
        "reason": "light broke again next day",
        "desired_resolution": "please check circuit thoroughly",
    }
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/appeals",
        json=appeal_body,
        headers=auth(citizen_token),
        timeout=30,
    )
    resp.raise_for_status()
    appeal = resp.json()["data"]
    expected_prefix = f"{ticket['ticket_id']}-SS-"
    check("7. Citizen appeal", str(appeal.get("appeal_no", "")).startswith(expected_prefix), f"appeal_no={appeal.get('appeal_no')}")

    # 8. Admin approves appeal
    print("\n--- Step 8: Admin approves appeal ---")
    admin_token = login("admin_local")
    review_body = {
        "decision": "approved",
        "review_comment": "approved for reprocess",
        "reprocess_instructions": "check circuit and report",
    }
    resp = requests.post(
        f"{BASE}/appeals/{appeal['id']}/review",
        json=review_body,
        headers=auth(admin_token),
        timeout=30,
    )
    resp.raise_for_status()
    reviewed = resp.json()["data"]
    check("8. Admin approve appeal", reviewed["status"] == "reprocessing", f"appeal_status={reviewed['status']}")

    # 9. Ticket back to processing
    print("\n--- Step 9: Ticket back to processing ---")
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail3 = resp.json()["data"]
    check("9. status=processing", detail3["status"] == "processing", f"status={detail3['status']}")
    check("9a. handling_round=2", detail3.get("handling_round") == 2, f"round={detail3.get('handling_round')}")
    check("9b. collab=in_progress", detail3.get("collaboration_status") == "in_progress", f"collab={detail3.get('collaboration_status')}")

    # 10. P0-A: Dept cannot self-resolve
    print("\n--- Step 10: P0-A verify dept cannot self-resolve ---")
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail4 = resp.json()["data"]
    primary2 = next((w for w in detail4["work_orders"] if w["task_type"] == "primary"), None)
    check("10. work order reset to processing", primary2["status"] == "processing", f"wo_status={primary2['status']}")

    # Dept attempts to self-resolve (should be denied by P0-A)
    resolve_attempt_body = {
        "version": detail4["version"],
        "remark": "try self resolve",
        "resolution_summary": "attempt",
        "resolution_measures": "attempt",
        "resolution_outcome": "resolved",
        "public_reply": "attempt",
    }
    resp = requests.post(
        f"{BASE}/tickets/{ticket['ticket_id']}/resolve",
        json=resolve_attempt_body,
        headers=auth(staff_token),
        timeout=30,
    )
    if resp.status_code < 400:
        check("10a. Dept resolve denied", False, f"dept could resolve! status={resp.status_code}")
    else:
        err_code = ""
        try:
            err_body = resp.json()
            err_code = err_body.get("error", {}).get("code", "") if isinstance(err_body.get("error"), dict) else ""
        except Exception:
            pass
        check("10a. Dept resolve denied", err_code in ("PERMISSION_DENIED", "INVALID_STATUS_TRANSITION") or resp.status_code in (403, 409, 422), f"errCode={err_code}, http={resp.status_code}")

    print("\n=== Acceptance Main Flow Result ===")
    print(f"PASS: {PASS}")
    print(f"FAIL: {FAIL}")
    if FAIL == 0:
        print("\nAll acceptance points passed!")
        return 0
    print(f"\n{FAIL} acceptance points failed!")
    return 1


if __name__ == "__main__":
    sys.exit(main())
