"""Real PostgreSQL/API smoke test for phase-4 cross-department collaboration."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid


BASE = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001/api/v1")
PASSWORD = os.environ["LOCAL_SEED_PASSWORD"]


def request(method, path, body=None, token=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8", "X-Request-ID": uuid.uuid4().hex}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["data"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode('utf-8')}") from exc


def login(username):
    return request("POST", "/auth/login", {"username": username, "password": PASSWORD})["access_token"]


def detail(ticket_id, token):
    return request("GET", f"/tickets/{ticket_id}", token=token)


def create_staff(admin, department_id, suffix):
    username = f"phase4_{department_id}_{suffix}"
    request("POST", "/users", {
        "username": username, "password": PASSWORD, "display_name": f"阶段四责任人{department_id}",
        "role": "department_staff", "department_id": department_id, "is_active": True,
    }, admin)
    return login(username)


def main():
    suffix = uuid.uuid4().hex[:8]
    citizen, agent, admin = login("citizen_local"), login("agent_local"), login("admin_local")
    departments = request("GET", "/departments", token=admin)[:4]
    if len(departments) < 4:
        raise RuntimeError("phase-4 test needs four active departments")
    staff = {item["id"]: create_staff(admin, item["id"], suffix) for item in departments}

    created = request("POST", "/tickets", {
        "idempotency_key": f"phase4-{uuid.uuid4()}", "request_type": "投诉",
        "description": "道路积水同时涉及排水、交通疏导和安全复核", "location": "幸福路与民生路交叉口",
        "source": "phase4-integration",
    }, citizen)["ticket"]
    ticket_id = created["ticket_id"]

    request("POST", f"/tickets/{ticket_id}/supplement-request", {
        "version": 1, "remark": "需要定位积水范围", "supplement_reason": "请补充现场照片和最近一次发生时间",
    }, agent)
    request("POST", f"/tickets/{ticket_id}/supplement", {
        "version": 2, "remark": "已补充现场信息", "supplement_content": "积水约三十米，今天上午再次发生",
    }, citizen)
    request("POST", f"/tickets/{ticket_id}/accept", {"version": 3, "remark": "材料完整，正式受理", "priority": "urgent"}, agent)

    primary = request("POST", f"/tickets/{ticket_id}/work-orders", {
        "version": 4, "task_type": "primary", "department_id": departments[0]["id"],
        "instructions": "牵头查明积水原因并组织处置",
    }, agent)
    returned = request("POST", f"/tickets/{ticket_id}/work-orders/{primary['id']}/return", {
        "version": primary["version"], "remark": "现场属于道路施工排水责任，请重新派发",
    }, staff[departments[0]["id"]])
    assert returned["status"] == "returned"

    primary = request("POST", f"/tickets/{ticket_id}/work-orders", {
        "version": 6, "task_type": "primary", "department_id": departments[1]["id"],
        "instructions": "牵头排查施工排水并形成统一答复",
    }, agent)
    support = request("POST", f"/tickets/{ticket_id}/work-orders", {
        "version": 7, "task_type": "support", "department_id": departments[2]["id"],
        "instructions": "负责现场交通疏导并反馈措施",
    }, agent)
    review = request("POST", f"/tickets/{ticket_id}/work-orders", {
        "version": 8, "task_type": "review", "department_id": departments[0]["id"],
        "instructions": "复核现场安全隐患是否消除",
    }, agent)

    request("POST", f"/tickets/{ticket_id}/dispute", {
        "version": 9, "remark": "部门对牵头关系有异议", "dispute_reason": "施工与道路养护责任边界需要管理员确认",
    }, staff[departments[2]["id"]])
    request("POST", f"/tickets/{ticket_id}/dispute/resolve", {
        "version": 10, "remark": "依据权责清单协调", "resolution": "施工主管部门继续主办，交通和城管协同",
        "primary_work_order_id": primary["id"],
    }, admin)

    primary = request("POST", f"/tickets/{ticket_id}/work-orders/{primary['id']}/start", {
        "version": primary["version"] + 2, "remark": "主办部门开始现场核查",
    }, staff[departments[1]["id"]])
    primary = request("POST", f"/tickets/{ticket_id}/work-orders/{primary['id']}/submit", {
        "version": primary["version"], "remark": "主办处置完成", "result_summary": "完成排水设施清理",
        "result_measures": "疏通雨水口并督促施工单位设置导流设施", "result_outcome": "resolved",
        "public_content": "主办部门已完成排水疏通和施工整改。",
    }, staff[departments[1]["id"]])

    successor = request("POST", f"/tickets/{ticket_id}/work-orders/{support['id']}/transfer", {
        "version": support["version"], "remark": "需由属地部门实施临时交通组织",
        "target_department_id": departments[3]["id"],
    }, staff[departments[2]["id"]])
    successor = request("POST", f"/tickets/{ticket_id}/work-orders/{successor['id']}/start", {
        "version": successor["version"], "remark": "接收转派并开始疏导",
    }, staff[departments[3]["id"]])
    request("POST", f"/tickets/{ticket_id}/work-orders/{successor['id']}/submit", {
        "version": successor["version"], "remark": "协办结果提交", "result_summary": "完成临时交通疏导",
        "result_measures": "设置警示锥并安排高峰值守", "result_outcome": "resolved",
        "public_content": "属地部门已完成现场交通疏导。",
    }, staff[departments[3]["id"]])

    review = request("POST", f"/tickets/{ticket_id}/work-orders/{review['id']}/start", {
        "version": review["version"], "remark": "开始安全复核",
    }, staff[departments[0]["id"]])
    request("POST", f"/tickets/{ticket_id}/work-orders/{review['id']}/submit", {
        "version": review["version"], "remark": "复核通过", "result_summary": "现场隐患已消除",
        "result_measures": "复查积水深度、警示设施和通行条件", "result_outcome": "resolved",
        "public_content": "复核确认现场已恢复安全通行。",
    }, staff[departments[0]["id"]])

    ready = detail(ticket_id, agent)
    assert ready["collaboration_status"] == "awaiting_summary" and len(ready["work_orders"]) == 5
    resolved = request("POST", f"/tickets/{ticket_id}/summary", {
        "version": ready["version"], "remark": "汇总三部门办理结果", "resolution_summary": "积水和通行隐患已处置",
        "resolution_measures": "完成排水疏通、施工整改、交通疏导和安全复核", "resolution_outcome": "resolved",
        "public_reply": "您反映的道路积水事项已由主办部门牵头、多部门协同完成处置，现场已恢复安全通行。",
    }, staff[departments[1]["id"]])
    assert resolved["status"] == "resolved" and resolved["collaboration_status"] == "completed"
    print(json.dumps({
        "ticket_id": ticket_id, "work_orders": len(ready["work_orders"]),
        "supplement": True, "department_return": True, "transfer": True,
        "dispute_coordination": True, "final_status": resolved["status"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
