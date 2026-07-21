"""Complete appeal review via API so we can verify handling_round=2 in browser."""
import requests

BASE = "http://localhost:8001/api/v1"
PASSWORD = "tingting-seed-demo-2026"


def login(username):
    resp = requests.post(f"{BASE}/auth/login", json={"username": username, "password": PASSWORD}, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    ticket_id = "QT2026072100000602"
    admin_token = login("admin_local")

    # List appeals for this ticket
    resp = requests.get(f"{BASE}/appeals?ticket_id={ticket_id}", headers=auth(admin_token), timeout=30)
    resp.raise_for_status()
    appeals_data = resp.json()["data"]
    appeals = appeals_data.get("items") or appeals_data
    print(f"Found {len(appeals)} appeals for {ticket_id}")
    for a in appeals:
        print(f"  appeal_id={a['id']}, appeal_no={a['appeal_no']}, status={a['status']}")

    if not appeals:
        print("No appeals found - citizen may not have submitted one. Creating via citizen...")
        citizen_token = login("citizen_local")
        resp = requests.post(f"{BASE}/tickets/{ticket_id}/appeals", json={
            "reason": "噪声问题反复出现，需要夜间复查",
            "desired_resolution": "请安排夜间复查并反馈结果",
        }, headers=auth(citizen_token), timeout=30)
        resp.raise_for_status()
        appeal = resp.json()["data"]
        print(f"  Created appeal: {appeal['appeal_no']}, status={appeal['status']}")
    else:
        # Take the first submitted appeal
        appeal = next((a for a in appeals if a["status"] == "submitted"), appeals[0])
        print(f"  Using appeal: {appeal['appeal_no']}, status={appeal['status']}")

    if appeal["status"] != "submitted":
        print(f"Appeal already reviewed (status={appeal['status']}). Skipping review.")
    else:
        # Admin reviews and approves
        resp = requests.post(f"{BASE}/appeals/{appeal['id']}/review", json={
            "decision": "approved",
            "review_comment": "同意重新办理，需夜间复查",
            "reprocess_instructions": "请安排夜间巡查并反馈结果",
        }, headers=auth(admin_token), timeout=30)
        resp.raise_for_status()
        reviewed = resp.json()["data"]
        print(f"After review: appeal_status={reviewed['status']}")

    # Verify ticket state
    staff_token = login("department_local")
    resp = requests.get(f"{BASE}/tickets/{ticket_id}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail = resp.json()["data"]
    print(f"\nFinal ticket state:")
    print(f"  ticket_id={detail['ticket_id']}")
    print(f"  status={detail['status']}")
    print(f"  handling_round={detail['handling_round']}")
    print(f"  collaboration_status={detail['collaboration_status']}")
    print(f"  version={detail['version']}")


if __name__ == "__main__":
    main()
