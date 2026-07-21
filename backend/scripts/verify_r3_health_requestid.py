"""Round 3: Health check + request_id propagation verification."""
import requests

BASE = "http://backend:8000"


def main():
    # Health checks
    r = requests.get(f"{BASE}/health/ready", timeout=5)
    print(f"health/ready: {r.status_code} {r.text[:100]}")
    r = requests.get(f"{BASE}/health/live", timeout=5)
    print(f"health/live: {r.status_code} {r.text[:100]}")

    # request_id propagation
    r = requests.post(f"{BASE}/api/v1/auth/login",
                      json={"username": "citizen_local", "password": "tingting-seed-demo-2026"},
                      timeout=5)
    rid = r.headers.get("X-Request-Id", "missing")
    print(f"login X-Request-Id: {rid}")
    token = r.json()["data"]["access_token"]

    # Authenticated request with custom request_id
    custom_rid = "r3-test-12345"
    r = requests.get(f"{BASE}/api/v1/auth/me",
                     headers={"Authorization": f"Bearer {token}", "X-Request-Id": custom_rid},
                     timeout=5)
    print(f"auth/me with custom X-Request-Id: status={r.status_code}, response header X-Request-Id={r.headers.get('X-Request-Id', 'missing')}")

    # Structured logging check (look for request_id in response)
    r = requests.get(f"{BASE}/api/v1/tickets?page_size=1",
                     headers={"Authorization": f"Bearer {token}"},
                     timeout=5)
    print(f"tickets list: status={r.status_code}, X-Request-Id={r.headers.get('X-Request-Id', 'missing')}")


if __name__ == "__main__":
    main()
