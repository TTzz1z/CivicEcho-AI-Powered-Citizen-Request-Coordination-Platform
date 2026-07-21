"""Execute return-to-department on QT2026072100000601 so dept can re-submit."""
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
    ticket_id = "QT2026072100000601"
    agent_token = login("agent_local")
    staff_token = login("department_local")

    # Get current state
    resp = requests.get(f"{BASE}/tickets/{ticket_id}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail = resp.json()["data"]
    print(f"Before return: status={detail['status']}, collab={detail['collaboration_status']}, version={detail['version']}")

    # Agent returns to department
    resp = requests.post(f"{BASE}/tickets/{ticket_id}/return-to-department", json={
        "version": detail["version"],
        "remark": "退回补充现场照片",
        "return_reason": "需要补充现场照片和维修单据，请部门重新提交完整材料",
    }, headers=auth(agent_token), timeout=30)
    resp.raise_for_status()
    returned = resp.json()["data"]
    print(f"After return: status={returned['status']}, collab={returned['collaboration_status']}, version={returned['version']}")

    # Verify dept can see return_reason on work order
    resp = requests.get(f"{BASE}/tickets/{ticket_id}", headers=auth(staff_token), timeout=30)
    resp.raise_for_status()
    detail_after = resp.json()["data"]
    primary = next(w for w in detail_after["work_orders"] if w["task_type"] == "primary")
    print(f"Work order status={primary['status']}, return_reason={primary.get('return_reason')}")


if __name__ == "__main__":
    main()
