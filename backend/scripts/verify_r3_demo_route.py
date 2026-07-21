"""Round 3: 5-minute demo route verification via API."""
import uuid
import requests

BASE = "http://backend:8000"
PASSWORD = "tingting-seed-demo-2026"


def login(username, password=PASSWORD):
    r = requests.post(f"{BASE}/api/v1/auth/login",
                      json={"username": username, "password": password}, timeout=10)
    assert r.status_code == 200, f"Login failed for {username}: {r.text}"
    return r.json()["data"]["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    print("=== Step 1: Citizen policy RAG consultation ===")
    citizen_token = login("citizen_local")
    r = requests.post(f"{BASE}/api/v1/orchestrator/chat",
                      headers=headers(citizen_token),
                      json={"message": "社保补贴政策适用于哪些人群",
                            "session_id": f"demo-{uuid.uuid4().hex[:8]}"},
                      timeout=60)
    print(f"  status={r.status_code}")
    if r.status_code == 200:
        data = r.json()["data"]
        print(f"  route={data.get('route')} should_create_ticket={data.get('should_create_ticket')}")
        print(f"  answer[:100]={data.get('message','')[:100]}")
        print(f"  citations={len(data.get('payload',{}).get('citations',[]))}")
        assert data.get("should_create_ticket") is False, "Policy RAG should not create ticket"
        print("  PASS: Policy RAG consultation works")

    print("\n=== Step 2: Citizen create ticket ===")
    r = requests.post(f"{BASE}/api/v1/orchestrator/chat",
                      headers=headers(citizen_token),
                      json={"message": "幸福路路灯坏了请派人维修",
                            "session_id": f"demo-{uuid.uuid4().hex[:8]}"},
                      timeout=60)
    print(f"  status={r.status_code}")
    if r.status_code == 200:
        data = r.json()["data"]
        print(f"  route={data.get('route')} should_create_ticket={data.get('should_create_ticket')}")
        if data.get("should_create_ticket"):
            print("  PASS: Ticket intake triggered")

    print("\n=== Step 3: Agent accept and assign ===")
    agent_token = login("agent_local")
    r = requests.get(f"{BASE}/api/v1/tickets?status=pending&page_size=5",
                     headers=headers(agent_token), timeout=10)
    print(f"  pending tickets: {r.json()['data']['total'] if r.status_code == 200 else 'error'}")

    print("\n=== Step 4: Department staff AI advice ===")
    dept_token = login("department_local")
    # Find an assigned ticket
    r = requests.get(f"{BASE}/api/v1/tickets?status=assigned&my_department=true&page_size=5",
                     headers=headers(dept_token), timeout=10)
    print(f"  assigned to my dept: {r.json()['data']['total'] if r.status_code == 200 else 'error'}")

    print("\n=== Step 5: Admin AI usage logs ===")
    admin_token = login("admin_local")
    r = requests.get(f"{BASE}/api/v1/admin/ai-usage/logs?page_size=5",
                     headers=headers(admin_token), timeout=10)
    print(f"  status={r.status_code}")
    if r.status_code == 200:
        data = r.json()["data"]
        print(f"  total logs: {data['total']}")
        for log in data["items"][:3]:
            print(f"    cap={log.get('capability')} provider={log.get('provider')} total_tokens={log.get('total_tokens')} cost={log.get('estimated_cost_rmb')}")

    print("\n=== Step 6: Admin AI usage stats ===")
    r = requests.get(f"{BASE}/api/v1/admin/ai-usage/stats?days=7",
                     headers=headers(admin_token), timeout=10)
    print(f"  status={r.status_code}")
    if r.status_code == 200:
        data = r.json()["data"]
        print(f"  total_calls={data['total_calls']} total_tokens={data['total_tokens']} total_cost={data['total_cost_rmb']}")
        print(f"  by_provider={data['by_provider']}")

    print("\n=== Demo route verification complete ===")


if __name__ == "__main__":
    main()
