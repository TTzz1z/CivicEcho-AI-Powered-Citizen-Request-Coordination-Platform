import urllib.error
import urllib.request
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app import model_governance as gov
from app.database import SessionLocal
from app.models import AiUsageBudgetModel, UserModel
from app.telemetry import latency_metrics, stage


def test_user_budget_applies_to_shared_reservations():
    with SessionLocal.begin() as db:
        user = UserModel(username=uuid4().hex, password_hash="test", display_name="test", role="citizen")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(AiUsageBudgetModel(user_id=user_id, daily_llm_call_limit=1, daily_token_limit=10))
    token = gov.model_caller.set(f"user:{user_id}")
    try:
        gov.reserve_model_call(4)
        with pytest.raises(gov.ModelCallDenied, match="budget_exceeded"):
            gov.reserve_model_call(1)
    finally:
        gov.model_caller.reset(token)
        with SessionLocal.begin() as db:
            db.execute(delete(UserModel).where(UserModel.id == user_id))


def test_retry_only_transient_and_circuit_opens(monkeypatch):
    monkeypatch.setattr(gov, "reserve_model_call", lambda tokens: None)
    monkeypatch.setattr(gov.time, "sleep", lambda seconds: None)
    gov._circuits.clear()
    attempts = []
    def fail(request, timeout):
        attempts.append(timeout)
        raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, None)
    monkeypatch.setattr(gov.urllib.request, "urlopen", fail)
    request = urllib.request.Request("https://example.invalid/chat", data=b'{"model":"test-v1"}')
    with pytest.raises(urllib.error.HTTPError):
        gov.read_model_response(request, 10, 1)
    with pytest.raises(urllib.error.HTTPError):
        gov.read_model_response(request, 10, 1)
    with pytest.raises(gov.ModelCallDenied, match="circuit_open"):
        gov.read_model_response(request, 10, 1)
    assert len(attempts) == 3
    gov._circuits.clear()


def test_stage_latency_reports_percentiles():
    name = f"test.{uuid4().hex}"
    for _ in range(5):
        with stage(name):
            pass
    metrics = latency_metrics()[name]
    assert metrics["sample_count"] == 5
    assert 0 <= metrics["p50_ms"] <= metrics["p95_ms"]
