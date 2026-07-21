"""Prepare a ticket at awaiting_review state for browser verification.

Creates a ticket and walks it through:
citizen submit -> agent accept -> agent assign -> dept process -> dept submit work order -> dept summarize
Stops at awaiting_review so the browser test can verify agent review-resolve UI.

Also creates a second ticket at resolved state with dissatisfied feedback for appeal UI verification.
"""
import json
import sys
import time
import uuid

import requests

BASE = "http://localhost:8001/api/v1"
PASSWORD = "tingting-seed-demo-2026"


def login(username):
    resp = requests.post(f"{BASE}/auth/login", json={"username": username, "password": PASSWORD}, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def setup_awaiting_review():
    """Ticket 1: walk to awaiting_review for agent review-resolve UI test."""
    print("=== Setup Ticket 1: awaiting_review state ===")
    citizen_token = login("citizen_local")
    agent_token = login("agent_local")
    staff_token = login("department_local")

    # 1. Citizen submits
    idem = f"browser-verify-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    resp = requests.post(f"{BASE}/tickets", json={
        "idempotency_key": idem,
        "request_type": "投诉",
        "description": "Browser verify: street light broken on Xingfu Road for 3 nights",
        "location": "Xingfu Road Community",
        "timezone": "Asia/Shanghai",
        "source": "browser-verify",
    }, headers=auth(citizen_token), timeout=30)
    resp.raise_for_status()
    ticket = resp.json()["data"]["ticket"]
    print(f"  ticket_id={ticket['ticket_id']}, version={ticket['version']}")

    # 2. Agent accepts
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/accept", json={
        "version": ticket["version"], "remark": "browser-verify-accept", "priority": "normal",
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    accepted = resp.json()["data"]

    # 3. Agent assigns to general-intake (id=7)
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/assign", json={
        "version": accepted["version"], "remark": "browser-verify-assign", "department_id": 7,
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    assigned = resp.json()["data"]

    # 4. Dept processes
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/process", json={
        "version": assigned["version"], "remark": "browser-verify-process",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    processed = resp.json()["data"]

    # 5. Dept submits work order result
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail = resp.json()["data"]
    primary = next(w for w in detail["work_orders"] if w["task_type"] == "primary")
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/work-orders/{primary['id']}/submit", json={
        "version": primary["version"], "remark": "browser-verify-submit",
        "result_summary": "lamp replaced", "result_measures": "replaced lamp and tested",
        "result_outcome": "resolved", "public_content": "lamp replaced and lighting restored",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()

    # 6. Dept summarizes -> awaiting_review
    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail2 = resp.json()["data"]
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/summary", json={
        "version": detail2["version"], "remark": "browser-verify-summary",
        "resolution_summary": "lamp replaced", "resolution_measures": "replaced lamp and tested",
        "resolution_outcome": "resolved", "public_reply": "lamp replaced and lighting restored",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    summarized = resp.json()["data"]
    print(f"  final status={summarized['status']}, collab={summarized['collaboration_status']}")
    print(f"  TICKET_ID_1={ticket['ticket_id']}")
    return ticket["ticket_id"]


def setup_resolved_dissatisfied():
    """Ticket 2: walk to resolved + dissatisfied feedback for appeal UI test."""
    print("\n=== Setup Ticket 2: resolved + dissatisfied feedback ===")
    citizen_token = login("citizen_local")
    agent_token = login("agent_local")
    staff_token = login("department_local")

    idem = f"browser-appeal-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    resp = requests.post(f"{BASE}/tickets", json={
        "idempotency_key": idem,
        "request_type": "投诉",
        "description": "Browser verify appeal: noise pollution at night",
        "location": "Xingfu Road Community",
        "timezone": "Asia/Shanghai",
        "source": "browser-verify",
    }, headers=auth(citizen_token), timeout=30)
    resp.raise_for_status()
    ticket = resp.json()["data"]["ticket"]
    print(f"  ticket_id={ticket['ticket_id']}")

    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/accept", json={
        "version": ticket["version"], "remark": "appeal-accept", "priority": "normal",
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    accepted = resp.json()["data"]

    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/assign", json={
        "version": accepted["version"], "remark": "appeal-assign", "department_id": 7,
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    assigned = resp.json()["data"]

    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/process", json={
        "version": assigned["version"], "remark": "appeal-process",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()

    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail = resp.json()["data"]
    primary = next(w for w in detail["work_orders"] if w["task_type"] == "primary")
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/work-orders/{primary['id']}/submit", json={
        "version": primary["version"], "remark": "appeal-submit",
        "result_summary": "noise addressed", "result_measures": "spoken to responsible party",
        "result_outcome": "resolved", "public_content": "noise issue resolved",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()

    resp = requests.get(f"{BASE}/tickets/{ticket['ticket_id']}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail2 = resp.json()["data"]
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/summary", json={
        "version": detail2["version"], "remark": "appeal-summary",
        "resolution_summary": "noise addressed", "resolution_measures": "spoken to responsible party",
        "resolution_outcome": "resolved", "public_reply": "noise issue resolved",
    }, headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    summarized = resp.json()["data"]

    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/review-resolve", json={
        "version": summarized["version"], "remark": "appeal-review-resolve",
        "resolution_summary": "noise addressed", "resolution_measures": "spoken to responsible party",
        "resolution_outcome": "resolved", "public_reply": "noise issue resolved",
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    resolved = resp.json()["data"]

    # Citizen dissatisfied feedback
    resp = requests.post(f"{BASE}/tickets/{ticket['ticket_id']}/feedback", json={
        "version": resolved["version"], "rating": "dissatisfied", "comment": "noise came back next night",
    }, headers=auth(citizen_token), timeout=30)
    resp.raise_for_status()
    feedback = resp.json()["data"]
    print(f"  final status={feedback['status']}")
    print(f"  TICKET_ID_2={ticket['ticket_id']}")
    return ticket["ticket_id"]


if __name__ == "__main__":
    t1 = setup_awaiting_review()
    t2 = setup_resolved_dissatisfied()
    print(f"\n=== Setup Complete ===")
    print(f"TICKET_AWAITING_REVIEW={t1}")
    print(f"TICKET_RESOLVED_DISSATISFIED={t2}")
