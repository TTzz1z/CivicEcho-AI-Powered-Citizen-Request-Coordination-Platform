"""Reproducible five-service Round-4 integration smoke test (stdlib only)."""
import json
import os
import re
import urllib.error
import urllib.request
import uuid


BACKEND = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001")
RASA = os.getenv("RASA_PUBLIC_URL", "http://localhost:5005")
PASSWORD = os.environ["LOCAL_SEED_PASSWORD"]


def request(method, url, body=None, token=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.code} {exc.read().decode('utf-8')}") from exc


def login(username):
    return request("POST", f"{BACKEND}/api/v1/auth/login", {"username": username, "password": PASSWORD})["data"]["access_token"]


def post(path, body, token):
    return request("POST", f"{BACKEND}{path}", body, token)["data"]


def main():
    sender = f"round4-ci-{uuid.uuid4().hex}"
    request("POST", f"{RASA}/webhooks/rest/webhook", {"sender": sender, "message": "幸福路的垃圾三天没人清理，我要投诉"})
    confirmation = request("POST", f"{RASA}/webhooks/rest/webhook", {"sender": sender, "message": "确认"})
    text = " ".join(item.get("text", "") for item in confirmation)
    match = re.search(r"QT\d{16}", text)
    if not match:
        raise RuntimeError(f"Rasa did not create a ticket: {text}")
    ticket_id = match.group(0)

    agent = login("agent_local")
    staff = login("department_local")
    admin = login("admin_local")
    department_id = request("GET", f"{BACKEND}/api/v1/auth/me", token=staff)["data"]["department_id"]
    assert post(f"/api/v1/tickets/{ticket_id}/accept", {"version": 1, "remark": "CI受理"}, agent)["status"] == "accepted"
    assert post(f"/api/v1/tickets/{ticket_id}/assign", {"version": 2, "remark": "CI派发", "department_id": department_id}, agent)["status"] == "assigned"
    assert post(f"/api/v1/tickets/{ticket_id}/process", {"version": 3, "remark": "CI处理"}, staff)["status"] == "processing"
    assert post(f"/api/v1/tickets/{ticket_id}/resolve", {"version": 4, "remark": "CI解决"}, staff)["status"] == "resolved"
    query = request("POST", f"{RASA}/webhooks/rest/webhook", {"sender": sender, "message": f"查询工单{ticket_id}"})
    if ticket_id not in " ".join(item.get("text", "") for item in query):
        raise RuntimeError("Rasa query did not return the updated ticket")
    assert post(f"/api/v1/tickets/{ticket_id}/close", {"version": 5, "remark": "CI办结"}, admin)["status"] == "closed"
    print(json.dumps({"ticket_id": ticket_id, "workflow": "closed", "chat_query": True}))


if __name__ == "__main__":
    main()
