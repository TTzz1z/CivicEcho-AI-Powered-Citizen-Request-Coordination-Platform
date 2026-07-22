"""Security closeout: metrics auth, bind-anonymous bounds, prod fail-fast, redaction."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.logging_config import redact
from app.main import app
from app.models import DepartmentModel, UserModel
from app.security import create_access_token, anonymous_creator_key, hash_password
from scripts.demo_reset import assert_safe_to_reset


client = TestClient(app)
PASSWORD = "Security-Closeout-Test!"


@pytest.fixture(scope="module")
def identities():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        departments = list(db.scalars(select(DepartmentModel).order_by(DepartmentModel.id).limit(2)).all())
        users = {}
        for role, department, active in [
            ("citizen", None, True),
            ("citizen", None, True),
            ("agent", None, True),
            ("admin", None, True),
        ]:
            username = f"sec_{role}_{active}_{suffix}_{len(users)}"
            user = UserModel(
                username=username,
                password_hash=hash_password(PASSWORD),
                display_name=username,
                role=role,
                department_id=department.id if department else None,
                is_active=active,
            )
            db.add(user)
            db.flush()
            users[username] = {
                "id": user.id,
                "username": username,
                "role": role,
                "department_id": user.department_id,
                "active": active,
            }
        db.commit()
    by_role = {}
    for value in users.values():
        by_role.setdefault((value["role"], value["active"]), []).append(value)
    return {"users": by_role, "departments": departments}


def _strong_prod_kwargs(**overrides):
    base = {
        "app_env": "production",
        "jwt_secret": "prod-jwt-secret-value-at-least-32-chars!!",
        "service_api_token": "prod-service-token-value-at-least-32!!",
        "database_url": "postgresql+psycopg://tingting:Str0ngDbPassw0rd!@postgres:5432/tingting",
        "cors_origins": "https://example.example",
        "malware_scan_mode": "clamd",
        "malware_scan_url": "clamav:3310",
        "malware_scan_require_clean": True,
        "object_storage_endpoint": "minio:9000",
        "object_storage_access_key": "prod-minio-access-key-ok",
        "object_storage_secret_key": "prod-minio-secret-key-ok",
        "object_storage_bucket": "tingting-attachments",
        "kb_upload_bucket": "tingting-kb",
    }
    base.update(overrides)
    return base


def test_metrics_rejects_anonymous():
    response = client.get("/metrics")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_metrics_rejects_non_admin_user(identities):
    citizen = identities["users"][("citizen", True)][0]
    token = create_access_token(citizen["id"], citizen["role"])
    response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_metrics_allows_admin_jwt(identities):
    admin = identities["users"][("admin", True)][0]
    token = create_access_token(admin["id"], admin["role"])
    response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "tickets_total" in response.json()["data"]


def test_metrics_allows_monitoring_token(monkeypatch):
    token = "monitoring-token-for-pytest-only-32chars"
    monkeypatch.setenv("MONITORING_TOKEN", token)
    get_settings.cache_clear()
    try:
        via_header = client.get("/metrics", headers={"X-Monitoring-Token": token})
        assert via_header.status_code == 200
        via_bearer = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert via_bearer.status_code == 200
        bad = client.get("/metrics", headers={"X-Monitoring-Token": "wrong-token"})
        assert bad.status_code == 401
    finally:
        monkeypatch.delenv("MONITORING_TOKEN", raising=False)
        get_settings.cache_clear()


def test_health_ready_still_anonymous():
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}


def test_bind_anonymous_requires_sender_and_rejects_foreign_web_user(identities):
    citizen, other = identities["users"][("citizen", True)]
    agent = identities["users"][("agent", True)][0]
    headers = {"Authorization": f"Bearer {create_access_token(citizen['id'], citizen['role'])}"}
    missing = client.post("/api/v1/tickets/bind-anonymous", json={}, headers=headers)
    assert missing.status_code == 422
    foreign = client.post(
        "/api/v1/tickets/bind-anonymous",
        json={"sender_id": f"web-user-{other['id']}"},
        headers=headers,
    )
    assert foreign.status_code == 403
    bad_format = client.post(
        "/api/v1/tickets/bind-anonymous",
        json={"sender_id": "not-a-web-sender"},
        headers=headers,
    )
    assert bad_format.status_code == 422
    agent_headers = {"Authorization": f"Bearer {create_access_token(agent['id'], agent['role'])}"}
    assert client.post(
        "/api/v1/tickets/bind-anonymous",
        json={"sender_id": f"web-anon-{uuid4()}"},
        headers=agent_headers,
    ).status_code == 403


def test_bind_anonymous_claims_matching_web_anon_tickets(identities):
    citizen = identities["users"][("citizen", True)][0]
    anon_id = f"web-anon-{uuid4()}"
    created = client.post(
        "/api/v1/tickets",
        json={
            "idempotency_key": str(uuid4()),
            "request_type": "投诉",
            "description": "匿名绑定安全测试",
            "location": "测试路",
            "occurred_at": "昨天晚上",
            "contact": "13800000001",
            "source": "pytest",
            "creator_reference": anon_id,
        },
        headers={"Authorization": f"Bearer {get_settings().service_api_token}"},
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    assert anonymous_creator_key(anon_id)
    headers = {"Authorization": f"Bearer {create_access_token(citizen['id'], citizen['role'])}"}
    bound = client.post("/api/v1/tickets/bind-anonymous", json={"sender_id": anon_id}, headers=headers)
    assert bound.status_code == 200
    assert bound.json()["data"]["bound_count"] >= 1
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=headers).status_code == 200


def test_redact_masks_tokens_phone_id_and_sensitive_keys():
    payload = {
        "api_key": "sk-secret",
        "contact": "13812345678",
        "note": "手机 13912345678 身份证 110101199001011234 Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
        "raw_content": "file body must not leak",
        "safe": "ok",
    }
    redacted = redact(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["contact"] == "[REDACTED]"
    assert redacted["raw_content"] == "[REDACTED]"
    assert redacted["safe"] == "ok"
    assert "[REDACTED_PHONE]" in redacted["note"]
    assert "[REDACTED_ID]" in redacted["note"]
    assert "Bearer [REDACTED]" in redacted["note"]
    assert "13912345678" not in redacted["note"]
    assert "110101199001011234" not in redacted["note"]


def test_production_settings_reject_weak_secrets(monkeypatch):
    monkeypatch.delenv("SEED_PASSWORD", raising=False)
    monkeypatch.delenv("LOCAL_SEED_PASSWORD", raising=False)
    Settings(**_strong_prod_kwargs())
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs(jwt_secret="short"))
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs(cors_origins="*"))
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs(object_storage_access_key="minioadmin", object_storage_secret_key="minioadmin"))
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs(malware_scan_mode="disabled", malware_scan_require_clean=False))
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs(database_url="postgresql+psycopg://tingting:change-me@postgres:5432/tingting"))
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    with pytest.raises(ValidationError):
        Settings(**_strong_prod_kwargs())
    monkeypatch.delenv("SEED_PASSWORD", raising=False)


def test_demo_reset_rejects_short_seed_password(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "short")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tingting_ci:ci-only-postgres-password@localhost:5432/tingting_ci",
    )
    with pytest.raises(SystemExit) as exc:
        assert_safe_to_reset(confirm_reset=True)
    assert exc.value.code == 1
