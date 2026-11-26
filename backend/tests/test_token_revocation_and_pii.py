"""Regression tests for immediate JWT revocation (token_version) and LLM PII redaction."""
import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app import llm_client
from app.database import SessionLocal
from app.logging_config import redact_for_llm
from app.main import app
from app.models import UserModel
from app.security import hash_password
from app.services.ai_service import AiService

client = TestClient(app)
TEST_PASSWORD = "Revocation-Test-Password!2026"


def _create_user(role: str) -> tuple[int, str]:
    username = f"rev_{role}_{uuid4().hex[:8]}"
    with SessionLocal.begin() as db:
        user = UserModel(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            display_name=username,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user.id, username


def _login(username: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_logout_immediately_revokes_previous_jwt():
    _, username = _create_user("citizen")
    headers = _login(username)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    res = client.post("/api/v1/auth/logout", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["revoked"] is True

    # Old token must be rejected immediately after logout.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    # Fresh login issues a new token with the bumped token_version and works cleanly.
    fresh_headers = _login(username)
    assert client.get("/api/v1/auth/me", headers=fresh_headers).status_code == 200


def test_admin_password_reset_revokes_existing_user_tokens():
    _, admin_name = _create_user("admin")
    citizen_id, citizen_name = _create_user("citizen")
    admin_headers = _login(admin_name)
    citizen_headers = _login(citizen_name)

    new_password = "NewStrongPassword!2026"
    reset_res = client.patch(
        f"/api/v1/users/{citizen_id}",
        headers=admin_headers,
        json={"password": new_password},
    )
    assert reset_res.status_code == 200

    # Previous token issued before password reset must immediately fail.
    assert client.get("/api/v1/auth/me", headers=citizen_headers).status_code == 401

    # Logging in with the new password succeeds.
    assert client.get("/api/v1/auth/me", headers=_login(citizen_name, new_password)).status_code == 200


def test_admin_role_change_revokes_existing_user_tokens():
    _, admin_name = _create_user("admin")
    user_id, username = _create_user("citizen")
    admin_headers = _login(admin_name)
    old_headers = _login(username)

    patch_res = client.patch(
        f"/api/v1/users/{user_id}",
        headers=admin_headers,
        json={"role": "agent"},
    )
    assert patch_res.status_code == 200
    assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401


def test_redact_for_llm_strips_direct_pii_while_keeping_district_context():
    raw = (
        "市民反映朝阳区清河街道幸福家园3号楼2单元501室漏水，"
        "联系电话13812345678或010-88776655，身份证11010519900101123X，"
        "邮箱test.user@example.com"
    )
    redacted = redact_for_llm(raw)
    assert "朝阳区清河街道幸福家园" in redacted
    assert "13812345678" not in redacted
    assert "010-88776655" not in redacted
    assert "11010519900101123X" not in redacted
    assert "test.user@example.com" not in redacted
    assert "3号楼2单元501室" not in redacted
    assert "[已脱敏手机号]" in redacted
    assert "[已脱敏证件号]" in redacted
    assert "[已脱敏门牌]" in redacted


def test_llm_client_redacts_outgoing_prompt_and_malformed_response_logs():
    fixture_settings = SimpleNamespace(
        ai_api_key="fixture-only",
        ai_base_url="https://model.invalid/v1",
        ai_model="fixture",
        ai_timeout_seconds=1,
        ai_max_tokens=100,
    )
    phone = "13987654321"
    door = "5栋1单元802室"
    secret_marker = "RAW-RESPONSE-SENSITIVE-TEXT"
    captured: dict = {}
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    logger = llm_client.logger
    prev_propagate = logger.propagate
    logger.propagate = False
    logger.addHandler(handler)

    def fake_transport(request, _timeout, _estimated):
        captured.update(json.loads(request.data))
        return json.dumps(
            {"choices": [{"message": {"content": f"not valid json {secret_marker}"}}]}
        ).encode("utf-8")

    ticket = SimpleNamespace(
        ticket_id="SYN-PII-001",
        status="processing",
        request_type="投诉",
        description=f"清河社区{door}供水异常，请联系{phone}",
        location=f"清河社区{door}",
        event="",
        occurred_at_text="",
        priority="normal",
        category=None,
        resolution_summary="",
        resolution_measures="",
        public_reply="",
        department=None,
    )
    service = object.__new__(AiService)
    service.repository = SimpleNamespace(active_departments=lambda: [])
    service._handling_facts_sufficient = lambda _ticket: False

    try:
        with patch.object(llm_client, "get_settings", return_value=fixture_settings), patch.object(
            llm_client, "read_model_response", side_effect=fake_transport
        ):
            result = llm_client.LlmClient().complete("summary", service._llm_context(ticket, "summary"))
    finally:
        logger.removeHandler(handler)
        logger.propagate = prev_propagate

    user_content = captured["messages"][1]["content"]
    assert result.success is False
    assert result.error_code == "json_decode_error"
    assert phone not in user_content
    assert door not in user_content
    assert "清河社区" in user_content
    assert secret_marker not in logs.getvalue()
