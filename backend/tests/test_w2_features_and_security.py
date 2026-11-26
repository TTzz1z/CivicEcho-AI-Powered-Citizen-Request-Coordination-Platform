"""Comprehensive tests for W2 features, security hardening, SSE, rate limits, and 0032 DB indexes."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.api import notifications as notifications_api
from app.config import Settings, get_settings
from app.csv_utils import neutralize_csv_cell
from app.database import SessionLocal
from app.logging_config import redact
from app.main import app, create_app
from app.models import (
    AuditLogModel,
    DepartmentModel,
    KbChunkModel,
    KbDocumentModel,
    LoginAttemptModel,
    NotificationModel,
    NotificationOutboxModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderHistoryModel,
    WorkOrderModel,
)
from app.rate_limit import LoginRateLimiter
from app.security import create_access_token, hash_password
from app.services.kb_service import KnowledgeBaseService
from app.worker import max_rate_limit_window_seconds


TEST_PASSWORD = "W2TestPassword!2026"
client = TestClient(app)


def _create_user(
    role: str,
    *,
    department_id: int | None = None,
    password: str = TEST_PASSWORD,
    is_active: bool = True,
) -> tuple[int, str]:
    username = f"w2_{role}_{uuid4().hex[:8]}"
    with SessionLocal.begin() as db:
        user = UserModel(
            username=username,
            password_hash=hash_password(password),
            display_name=f"用户-{username}",
            role=role,
            department_id=department_id,
            is_active=is_active,
            token_version=1,
        )
        db.add(user)
        db.flush()
        return user.id, username


def _create_department(*, is_active: bool = True) -> int:
    suffix = uuid4().hex[:6]
    with SessionLocal.begin() as db:
        dept = DepartmentModel(
            code=f"w2-dept-{suffix}",
            name=f"W2测试部门-{suffix}",
            description="W2 test department",
            is_active=is_active,
        )
        db.add(dept)
        db.flush()
        return dept.id


def _auth_header(user_id: int, role: str, *, token_version: int = 1) -> dict[str, str]:
    token = create_access_token(user_id, role, token_version=token_version)
    return {"Authorization": f"Bearer {token}"}


def _create_ticket(
    *,
    creator_user_id: int | None = None,
    status: str = "accepted",
    description: str = "测试工单内容",
    internal_note: str | None = "内部保密备注",
    public_reply: str | None = "公开答复内容",
) -> str:
    ticket_id = f"QT{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid4().hex[:8].upper()}"
    with SessionLocal.begin() as db:
        ticket = TicketModel(
            ticket_id=ticket_id,
            idempotency_key=f"idem-{uuid4().hex}",
            request_type="投诉",
            description=description,
            location="清河街道测试路",
            status=status,
            priority="normal",
            creator_user_id=creator_user_id,
            internal_note=internal_note,
            public_reply=public_reply,
            resolution_summary="处理概要" if status in {"resolved", "closed"} else "草稿概要",
            resolution_measures="处理措施" if status in {"resolved", "closed"} else "草稿措施",
            resolution_outcome="resolved" if status in {"resolved", "closed"} else None,
            version=1,
        )
        db.add(ticket)
    return ticket_id


def _parse_sse(raw_text: str) -> list[dict[str, str | None]]:
    events: list[dict[str, str | None]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_id = None
        event_name = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        events.append({"id": event_id, "event": event_name, "data": "\n".join(data_lines)})
    return events


# ---------------------------------------------------------------------------
# 1. Auth: change-password & register
# ---------------------------------------------------------------------------

def test_change_password_validation_token_revocation_and_audit(monkeypatch):
    user_id, username = _create_user("citizen")
    old_headers = _auth_header(user_id, "citizen", token_version=1)

    # Unauthenticated -> 401
    unauth = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "NewPassword123"},
    )
    assert unauth.status_code == 401

    # Wrong current password -> MUST return 400 (not 401)
    wrong = client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": "WrongPassword999", "new_password": "NewPassword123"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    # Weak or identical password -> 422
    weak = client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": TEST_PASSWORD, "new_password": "short1"},
    )
    assert weak.status_code == 422

    same = client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD},
    )
    assert same.status_code == 422

    # Production 12-char mixed-class enforcement
    try:
        with monkeypatch.context() as production:
            production.setenv("APP_ENV", "production")
            production.setenv("JWT_SECRET", "prod-jwt-secret-value-at-least-32-chars!!")
            production.setenv("SERVICE_API_TOKEN", "prod-service-token-value-at-least-32!!")
            production.setenv("CORS_ORIGINS", "https://example.example")
            production.setenv("MALWARE_SCAN_MODE", "clamd")
            production.setenv("MALWARE_SCAN_URL", "clamav:3310")
            production.setenv("MALWARE_SCAN_REQUIRE_CLEAN", "true")
            production.setenv("OBJECT_STORAGE_ENDPOINT", "minio:9000")
            production.setenv("OBJECT_STORAGE_ACCESS_KEY", "prod-minio-access-key-ok")
            production.setenv("OBJECT_STORAGE_SECRET_KEY", "prod-minio-secret-key-ok")
            production.setenv("DATABASE_URL", "postgresql+psycopg://tingting:Str0ngDbPassw0rd!@postgres:5432/tingting")
            get_settings.cache_clear()
            prod_headers = _auth_header(user_id, "citizen", token_version=1)
            too_short_prod = client.post(
                "/api/v1/auth/change-password",
                headers=prod_headers,
                json={"current_password": TEST_PASSWORD, "new_password": "Valid8char"},
            )
            assert too_short_prod.status_code == 422
    finally:
        get_settings.cache_clear()

    # Valid change_password
    new_pw = "UpdatedStrongPw99!"
    ok = client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": TEST_PASSWORD, "new_password": new_pw},
    )
    assert ok.status_code == 200
    body = ok.json()["data"]
    assert body["token_version"] == 2
    assert body["user"]["username"] == username
    new_token = body["access_token"]

    # Old token invalidated immediately -> 401
    assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
    # New token works
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200

    # Audit log recorded & logging redaction covers current_password/new_password
    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditLogModel).where(
                AuditLogModel.actor_user_id == user_id,
                AuditLogModel.action == "change_password",
                AuditLogModel.outcome == "success",
            )
        )
        assert audit is not None
    redacted = redact({"current_password": "secret1", "new_password": "secret2"})
    assert redacted == {"current_password": "[REDACTED]", "new_password": "[REDACTED]"}


def test_register_citizen_security_conflict_toggle_and_rate_limit(monkeypatch):
    uname = f"reg_user_{uuid4().hex[:8]}"
    # Sending role="admin" must NEVER elevate privileges
    res = client.post(
        "/api/v1/auth/register",
        json={
            "username": uname,
            "password": "CitizenPass123",
            "role": "admin",
            "department_id": 999,
            "phone": "13800138000",
        },
    )
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["user"]["role"] == "citizen"
    assert data["user"]["department_id"] is None
    assert data["user"]["display_name"] == uname
    assert data["access_token"]

    # Duplicate case-insensitive username -> 409
    dup = client.post(
        "/api/v1/auth/register",
        json={"username": uname.upper(), "password": "CitizenPass123"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "USERNAME_EXISTS"

    # Toggle disabled -> 403
    monkeypatch.setenv("ALLOW_CITIZEN_SELF_REGISTER", "false")
    get_settings.cache_clear()
    try:
        disabled = client.post(
            "/api/v1/auth/register",
            json={"username": f"reg_off_{uuid4().hex[:8]}", "password": "CitizenPass123"},
        )
        assert disabled.status_code == 403
        assert disabled.json()["error"]["code"] == "REGISTRATION_DISABLED"
    finally:
        monkeypatch.delenv("ALLOW_CITIZEN_SELF_REGISTER", raising=False)
        get_settings.cache_clear()

    # Dedicated rate limiter -> 429 + Retry-After
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like("register:%")))
    monkeypatch.setenv("REGISTER_RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("REGISTER_RATE_LIMIT_WINDOW_SECONDS", "120")
    get_settings.cache_clear()
    try:
        for _ in range(2):
            ok_reg = client.post(
                "/api/v1/auth/register",
                json={"username": f"reg_rl_{uuid4().hex[:8]}", "password": "CitizenPass123"},
            )
            assert ok_reg.status_code == 201
        limited = client.post(
            "/api/v1/auth/register",
            json={"username": f"reg_rl_{uuid4().hex[:8]}", "password": "CitizenPass123"},
        )
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "REGISTER_RATE_LIMITED"
        assert int(limited.headers["Retry-After"]) >= 1
    finally:
        monkeypatch.delenv("REGISTER_RATE_LIMIT_ATTEMPTS", raising=False)
        monkeypatch.delenv("REGISTER_RATE_LIMIT_WINDOW_SECONDS", raising=False)
        get_settings.cache_clear()
        with SessionLocal.begin() as db:
            db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like("register:%")))


# ---------------------------------------------------------------------------
# 2. Batch Assign
# ---------------------------------------------------------------------------

def test_batch_assign_partial_outcomes_isolation_and_work_order_creation():
    dept_id = _create_department(is_active=True)
    inactive_dept_id = _create_department(is_active=False)
    agent_id, _ = _create_user("agent")
    citizen_id, _ = _create_user("citizen")
    staff_id, _ = _create_user("department_staff", department_id=dept_id)

    agent_headers = _auth_header(agent_id, "agent")
    citizen_headers = _auth_header(citizen_id, "citizen")
    staff_headers = _auth_header(staff_id, "department_staff")

    # Role gate
    assert client.post(
        "/api/v1/tickets/batch-assign",
        headers=citizen_headers,
        json={"ticket_ids": ["QT2026010100000001"], "department_id": dept_id},
    ).status_code == 403
    assert client.post(
        "/api/v1/tickets/batch-assign",
        headers=staff_headers,
        json={"ticket_ids": ["QT2026010100000001"], "department_id": dept_id},
    ).status_code == 403

    # > 50 tickets -> 422
    assert client.post(
        "/api/v1/tickets/batch-assign",
        headers=agent_headers,
        json={"ticket_ids": [f"QT20260101{i:08d}" for i in range(51)], "department_id": dept_id},
    ).status_code == 422

    # Inactive department -> 409
    assert client.post(
        "/api/v1/tickets/batch-assign",
        headers=agent_headers,
        json={"ticket_ids": ["QT2026010100000001"], "department_id": inactive_dept_id},
    ).status_code == 409

    t_valid = _create_ticket(creator_user_id=citizen_id, status="accepted")
    t_conflict = _create_ticket(creator_user_id=citizen_id, status="accepted")
    t_pending = _create_ticket(creator_user_id=citizen_id, status="pending")
    t_missing = "QT2099123199999999"

    res = client.post(
        "/api/v1/tickets/batch-assign",
        headers=agent_headers,
        json={
            "ticket_ids": [t_valid, t_valid, t_conflict, t_pending, t_missing],
            "department_id": dept_id,
            "assigned_user_id": staff_id,
            "note": "批量派发测试",
            "versions": {t_valid: 1, t_conflict: 99},
        },
    )
    assert res.status_code == 200
    payload = res.json()["data"]
    assert len(payload["succeeded"]) == 1
    assert payload["succeeded"][0]["ticket_id"] == t_valid
    assert payload["succeeded"][0]["status"] == "assigned"
    assert payload["succeeded"][0]["version"] == 2
    assert payload["succeeded"][0]["work_order_no"].startswith(f"{t_valid}-M-")

    failed_by_id = {item["ticket_id"]: item["code"] for item in payload["failed"]}
    assert failed_by_id == {
        t_valid: "DUPLICATE_TICKET_ID",
        t_conflict: "VERSION_CONFLICT",
        t_pending: "INVALID_STATUS_TRANSITION",
        t_missing: "TICKET_NOT_FOUND",
    }

    # Verify DB persistence for t_valid (isolated commit survived t_conflict rollback)
    with SessionLocal() as db:
        ticket_row = db.scalar(select(TicketModel).where(TicketModel.ticket_id == t_valid))
        assert ticket_row is not None and ticket_row.status == "assigned"
        wo = db.scalar(select(WorkOrderModel).where(WorkOrderModel.ticket_id == t_valid))
        assert wo is not None and wo.task_type == "primary" and wo.department_id == dept_id
        wo_hist = db.scalar(select(WorkOrderHistoryModel).where(WorkOrderHistoryModel.work_order_id == wo.id))
        assert wo_hist is not None and wo_hist.action == "create"
        t_hist = db.scalar(
            select(TicketStatusHistoryModel).where(
                TicketStatusHistoryModel.ticket_id == t_valid,
                TicketStatusHistoryModel.operation_type == "assign",
            )
        )
        assert t_hist is not None
        outbox = db.scalar(
            select(NotificationOutboxModel).where(
                NotificationOutboxModel.ticket_id == t_valid,
                NotificationOutboxModel.event_type == "ticket_assigned",
            )
        )
        assert outbox is not None


# ---------------------------------------------------------------------------
# 3. Streaming CSV Exports & Formula Injection Neutralization
# ---------------------------------------------------------------------------

def test_tickets_and_audit_logs_csv_exports_bom_scope_and_formula_neutralization():
    citizen1_id, _ = _create_user("citizen")
    citizen2_id, _ = _create_user("citizen")
    admin_id, _ = _create_user("admin")

    # Formula injection payloads
    assert neutralize_csv_cell("=CMD|' /C calc'!A0") == "'=CMD|' /C calc'!A0"
    assert neutralize_csv_cell("  +SUM(A1:A2)") == "'  +SUM(A1:A2)"
    assert neutralize_csv_cell("-1+1") == "'-1+1"
    assert neutralize_csv_cell("@SUM(1,1)") == "'@SUM(1,1)"
    assert neutralize_csv_cell("\t=1+1") == "'\t=1+1"
    assert neutralize_csv_cell("\r=1+1") == "'\r=1+1"

    t_c1 = _create_ticket(
        creator_user_id=citizen1_id,
        status="processing",
        description="  =HYPERLINK(\"http://evil\",\"click\")",
        internal_note="SECRET-INTERNAL-NOTE-C1",
        public_reply="UNPUBLISHED-PUBLIC-REPLY",
    )
    t_c2 = _create_ticket(
        creator_user_id=citizen2_id,
        status="resolved",
        description="普通市民2工单",
        internal_note="SECRET-INTERNAL-NOTE-C2",
        public_reply="已解决公开答复",
    )

    # Citizen 1 export: only sees own ticket, no internal_note, no unpublished public_reply
    c1_headers = _auth_header(citizen1_id, "citizen")
    res_c1 = client.get(
        "/api/v1/tickets/export",
        headers=c1_headers,
        params={"keyword": t_c1},
    )
    assert res_c1.status_code == 200
    assert res_c1.headers["content-type"].startswith("text/csv")
    assert res_c1.headers["cache-control"] == "no-store"
    assert res_c1.headers["x-content-type-options"] == "nosniff"
    assert "tickets-export-" in res_c1.headers["content-disposition"]
    assert res_c1.content.startswith(b"\xef\xbb\xbf")

    decoded_c1 = res_c1.content.decode("utf-8-sig")
    rows_c1 = list(csv.reader(io.StringIO(decoded_c1)))
    assert len(rows_c1) == 2
    assert rows_c1[1][0] == t_c1
    assert rows_c1[1][5].startswith("'  =HYPERLINK")
    assert "SECRET-INTERNAL-NOTE-C1" not in decoded_c1
    assert "UNPUBLISHED-PUBLIC-REPLY" not in decoded_c1
    assert t_c2 not in decoded_c1

    # Citizen cannot export audit logs
    assert client.get("/api/v1/admin/audit-logs/export", headers=c1_headers).status_code == 403

    # Admin export audit logs with formula payload & filter
    with SessionLocal.begin() as db:
        db.add(AuditLogModel(
            actor_user_id=admin_id,
            actor_type="user",
            action="w2_formula_probe",
            resource_type="ticket",
            resource_id=t_c1,
            outcome="success",
            details="+1+1",
            request_id=f"req-{uuid4().hex[:8]}",
        ))
    admin_headers = _auth_header(admin_id, "admin")
    audit_res = client.get(
        "/api/v1/admin/audit-logs/export",
        headers=admin_headers,
        params={"action": "w2_formula_probe"},
    )
    assert audit_res.status_code == 200
    assert audit_res.content.startswith(b"\xef\xbb\xbf")
    audit_rows = list(csv.reader(io.StringIO(audit_res.content.decode("utf-8-sig"))))
    assert len(audit_rows) == 2
    assert audit_rows[1][1] == "w2_formula_probe"
    assert audit_rows[1][8] == "'+1+1"


# ---------------------------------------------------------------------------
# 4. Notification SSE & CORS
# ---------------------------------------------------------------------------

def test_notification_sse_initial_replay_ping_and_db_error_fallback(monkeypatch):
    user_id, _ = _create_user("citizen")
    headers = _auth_header(user_id, "citizen")

    # Unauthenticated -> 401
    assert client.get("/api/v1/notifications/stream").status_code == 401

    t0 = datetime.now(timezone.utc) - timedelta(seconds=10)
    t1 = t0 + timedelta(seconds=2)
    n1_id = str(uuid4())
    n2_id = str(uuid4())
    with SessionLocal.begin() as db:
        db.add(NotificationModel(
            id=n1_id,
            recipient_user_id=user_id,
            event_type="ticket_accepted",
            channel="in_app",
            title="通知1",
            content="第一条未读通知",
            status="unread",
            delivery_status="delivered",
            event_key=f"sse-1-{n1_id}",
            created_at=t0,
        ))
        db.add(NotificationModel(
            id=n2_id,
            recipient_user_id=user_id,
            event_type="ticket_assigned",
            channel="in_app",
            title="通知2",
            content="第二条未读通知",
            status="unread",
            delivery_status="delivered",
            event_key=f"sse-2-{n2_id}",
            created_at=t1,
        ))

    monkeypatch.setattr(notifications_api, "_SSE_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(notifications_api, "_SSE_PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(notifications_api, "_SSE_MAX_SECONDS", 0.16)

    # Full initial stream -> unread_count + both notifications + ping
    res = client.get("/api/v1/notifications/stream", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(res.text)
    names = [e["event"] for e in events]
    assert names[0] == "unread_count"
    assert json.loads(events[0]["data"])["unread_count"] == 2
    notif_events = [e for e in events if e["event"] == "notification"]
    assert [json.loads(e["data"])["id"] for e in notif_events] == [n1_id, n2_id]
    assert "ping" in names

    # Replay via Last-Event-ID header using first event's id -> only n2_id
    first_event_id = notif_events[0]["id"]
    replay_res = client.get(
        "/api/v1/notifications/stream",
        headers={**headers, "Last-Event-ID": first_event_id},
    )
    assert replay_res.status_code == 200
    replay_notifs = [e for e in _parse_sse(replay_res.text) if e["event"] == "notification"]
    assert [json.loads(e["data"])["id"] for e in replay_notifs] == [n2_id]

    # Replay via query param last_event_id=<bare id> -> only n2_id
    query_replay = client.get(
        "/api/v1/notifications/stream",
        headers=headers,
        params={"last_event_id": n1_id},
    )
    query_notifs = [e for e in _parse_sse(query_replay.text) if e["event"] == "notification"]
    assert [json.loads(e["data"])["id"] for e in query_notifs] == [n2_id]

    # Graceful exit with event: error on SQLAlchemyError
    monkeypatch.setattr(
        notifications_api,
        "_fetch_stream_batch",
        lambda *_a, **_kw: (_ for _ in ()).throw(SQLAlchemyError("db lost")),
    )
    err_res = client.get("/api/v1/notifications/stream", headers=headers)
    assert err_res.status_code == 200
    err_events = _parse_sse(err_res.text)
    assert err_events[0]["event"] == "error"
    assert json.loads(err_events[0]["data"])["code"] == "STREAM_UNAVAILABLE"

    # CORS allows Last-Event-ID
    preflight = client.options(
        "/api/v1/notifications/stream",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Last-Event-ID",
        },
    )
    assert preflight.status_code == 200
    allowed = preflight.headers.get("access-control-allow-headers", "").lower()
    assert "last-event-id" in allowed


# ---------------------------------------------------------------------------
# 5. Production Security Seal, Write Rate Limiters & Worker Cleanup
# ---------------------------------------------------------------------------

def test_production_app_disables_openapi_and_docs():
    prod_settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="prod-jwt-secret-value-at-least-32-chars!!",
        service_api_token="prod-service-token-value-at-least-32!!",
        database_url="postgresql+psycopg://tingting:Str0ngDbPassw0rd!@postgres:5432/tingting",
        cors_origins="https://example.example",
        malware_scan_mode="clamd",
        malware_scan_url="clamav:3310",
        malware_scan_require_clean=True,
        object_storage_endpoint="minio:9000",
        object_storage_access_key="prod-minio-access-key-ok",
        object_storage_secret_key="prod-minio-secret-key-ok",
        object_storage_bucket="tingting-attachments",
        kb_upload_bucket="tingting-kb",
    )
    prod_app = create_app(prod_settings)
    with TestClient(prod_app) as prod_client:
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/redoc").status_code == 404
        assert prod_client.get("/openapi.json").status_code == 404

    # Dev app keeps docs enabled
    assert client.get("/openapi.json").status_code == 200


def test_write_rate_limiters_and_worker_cleanup(monkeypatch):
    citizen_id, _ = _create_user("citizen")
    headers = _auth_header(citizen_id, "citizen")

    # 1. Anonymous/service ticket creation rate limit
    monkeypatch.setenv("ANON_TICKET_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("ANON_TICKET_RATE_LIMIT_WINDOW_SECONDS", "300")
    get_settings.cache_clear()
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like("anon_ticket:%")))
    try:
        svc_headers = {"Authorization": f"Bearer {get_settings().service_api_token}"}
        t_payload = {
            "idempotency_key": str(uuid4()),
            "request_type": "投诉",
            "description": "匿名限流测试诉求",
            "location": "测试路",
            "creator_reference": f"web-anon-{uuid4().hex}",
        }
        assert client.post("/api/v1/tickets", headers=svc_headers, json=t_payload).status_code == 201
        t_payload["idempotency_key"] = str(uuid4())
        limited_t = client.post("/api/v1/tickets", headers=svc_headers, json=t_payload)
        assert limited_t.status_code == 429
        assert "Retry-After" in limited_t.headers
    finally:
        monkeypatch.delenv("ANON_TICKET_RATE_LIMIT_ATTEMPTS", raising=False)
        monkeypatch.delenv("ANON_TICKET_RATE_LIMIT_WINDOW_SECONDS", raising=False)
        get_settings.cache_clear()

    # 2. AI rate limit
    monkeypatch.setenv("AI_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("AI_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like(f"ai:{citizen_id}:%")))
    try:
        assert client.post(
            "/api/v1/ai/pre-review",
            headers=headers,
            json={"description": "小区门口路灯损坏需要修复"},
        ).status_code == 200
        limited_ai = client.post(
            "/api/v1/ai/pre-review",
            headers=headers,
            json={"description": "小区门口路灯损坏需要修复"},
        )
        assert limited_ai.status_code == 429
        assert "Retry-After" in limited_ai.headers
    finally:
        monkeypatch.delenv("AI_RATE_LIMIT_ATTEMPTS", raising=False)
        monkeypatch.delenv("AI_RATE_LIMIT_WINDOW_SECONDS", raising=False)
        get_settings.cache_clear()

    # 3. Export rate limit
    monkeypatch.setenv("EXPORT_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("EXPORT_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like(f"export:{citizen_id}:%")))
    try:
        assert client.get("/api/v1/tickets/export", headers=headers).status_code == 200
        limited_exp = client.get("/api/v1/tickets/export", headers=headers)
        assert limited_exp.status_code == 429
        assert "Retry-After" in limited_exp.headers
    finally:
        monkeypatch.delenv("EXPORT_RATE_LIMIT_ATTEMPTS", raising=False)
        monkeypatch.delenv("EXPORT_RATE_LIMIT_WINDOW_SECONDS", raising=False)
        get_settings.cache_clear()

    # 4. Upload rate limit
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key.like(f"upload:{citizen_id}:%")))
    try:
        tid = _create_ticket(creator_user_id=citizen_id, status="processing")
        up1 = client.post(
            f"/api/v1/tickets/{tid}/attachments",
            headers=headers,
            data={"attachment_type": "citizen_material", "visibility": "public"},
            files={"file": ("test.txt", b"hello-attachment", "text/plain")},
        )
        # Depending on storage availability in test env, may return 201 or 503 after rate check;
        # the second request MUST be blocked with 429 before hitting storage!
        assert up1.status_code in {201, 503}
        up2 = client.post(
            f"/api/v1/tickets/{tid}/attachments",
            headers=headers,
            data={"attachment_type": "citizen_material", "visibility": "public"},
            files={"file": ("test.txt", b"hello-attachment", "text/plain")},
        )
        assert up2.status_code == 429
        assert "Retry-After" in up2.headers
    finally:
        monkeypatch.delenv("UPLOAD_RATE_LIMIT_ATTEMPTS", raising=False)
        monkeypatch.delenv("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", raising=False)
        get_settings.cache_clear()

    # 5. Worker cleanup_expired respects max_rate_limit_window_seconds
    now = datetime.now(timezone.utc)
    recent_key = f"register:keep-{uuid4().hex[:6]}"
    stale_key = f"register:drop-{uuid4().hex[:6]}"
    with SessionLocal.begin() as db:
        db.add(LoginAttemptModel(key=recent_key, attempted_at=now - timedelta(seconds=200)))
        db.add(LoginAttemptModel(key=stale_key, attempted_at=now - timedelta(seconds=900)))
    test_settings = Settings(_env_file=None, register_rate_limit_window_seconds=300)
    max_win = max_rate_limit_window_seconds(test_settings)
    assert max_win == 300
    LoginRateLimiter(5, 60).cleanup_expired(max_window_seconds=max_win)
    with SessionLocal() as db:
        assert db.scalar(select(LoginAttemptModel).where(LoginAttemptModel.key == recent_key)) is not None
        assert db.scalar(select(LoginAttemptModel).where(LoginAttemptModel.key == stale_key)) is None
        db.execute(delete(LoginAttemptModel).where(LoginAttemptModel.key == recent_key))
        db.commit()


# ---------------------------------------------------------------------------
# 6. Alembic 0032 Indexes & KbService._keyword_search() Optimization
# ---------------------------------------------------------------------------

def test_0032_indexes_and_pg_trgm_present():
    expected_indexes = {
        "ix_kb_chunks_embedding_hnsw",
        "ix_kb_chunks_content_trgm",
        "ix_tickets_dept_status_created",
        "ix_tickets_assignee_status_created",
        "ix_tickets_status_updated",
        "ix_tickets_collab_status_created",
        "ix_tickets_status_paused_resolve_due",
        "ix_notifications_recipient_created_id",
    }
    with SessionLocal() as db:
        ext = db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")).scalar()
        assert ext == "pg_trgm"
        rows = db.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        ).scalars().all()
        assert expected_indexes <= set(rows)


def test_kb_keyword_search_recall_batch_isolation_and_candidate_bound(monkeypatch):
    admin_id, _ = _create_user("admin")
    live_batch = f"batch-live-{uuid4().hex[:8]}"
    stale_batch = f"batch-stale-{uuid4().hex[:8]}"
    with SessionLocal.begin() as db:
        doc = KbDocumentModel(
            title="路灯与社保测试文档",
            kb_type="guide",
            visibility="PUBLIC",
            status="PUBLISHED",
            parse_status="done",
            index_status="ready",
            active_index_batch=live_batch,
            uploaded_by_user_id=admin_id,
        )
        db.add(doc)
        db.flush()
        doc_id = doc.id

        # 2-char & 3+-char live chunks
        db.add(KbChunkModel(
            document_id=doc_id,
            chunk_index=0,
            content="市民反映路灯故障损坏需要夜间照明维修。",
            token_count=8,
            char_count=20,
            index_batch_id=live_batch,
        ))
        db.add(KbChunkModel(
            document_id=doc_id,
            chunk_index=1,
            content="办理社保补贴和医疗保险参保手续指南。",
            token_count=8,
            char_count=19,
            index_batch_id=live_batch,
        ))
        # Stale/abandoned batch chunk MUST be ignored
        db.add(KbChunkModel(
            document_id=doc_id,
            chunk_index=2,
            content="旧批次废弃分块路灯维修社保补贴不应被召回。",
            token_count=9,
            char_count=22,
            index_batch_id=stale_batch,
        ))
        # Extra live chunks to test candidate bound
        for idx in range(3, 25):
            db.add(KbChunkModel(
                document_id=doc_id,
                chunk_index=idx,
                content=f"市政照明路灯巡检记录编号 {idx} 路灯维修",
                token_count=6,
                char_count=20,
                index_batch_id=live_batch,
            ))

    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        hits_short = svc._keyword_search("路灯", [doc_id], k=5)
        assert hits_short and len(hits_short) <= 5

        hits_trigram = svc._keyword_search("路灯维修", [doc_id], k=5)
        assert hits_trigram

        hits_social = svc._keyword_search("社保补贴", [doc_id], k=5)
        assert hits_social
        hit_ids = [cid for _, cid in hits_social]
        stale_chunk_id = db.scalar(
            select(KbChunkModel.id).where(
                KbChunkModel.document_id == doc_id,
                KbChunkModel.index_batch_id == stale_batch,
            )
        )
        assert stale_chunk_id not in hit_ids
