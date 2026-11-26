"""Opt-in integration test; DATABASE_URL must point to an isolated migrated DB."""
import hashlib
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import model_governance
from app.database import SessionLocal
from app.llm_client import get_llm_client
from app.main import app
from app.models import AiUsageLogModel, ModelCallModel, UserModel
from app.security import create_access_token


@pytest.mark.skipif(os.getenv("RUN_ISOLATED_MODEL_TEST") != "1", reason="requires an isolated migrated PostgreSQL database")
def test_authenticated_routes_reserve_separate_user_budgets(monkeypatch):
    monkeypatch.setattr(model_governance, "CALLS_PER_MINUTE", 1)
    llm = get_llm_client()
    monkeypatch.setattr(llm, "api_key", "provider-stub")
    calls = []

    class StubResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            content = json.dumps({"identified_type": "投诉", "normalized_description": "路灯损坏"}, ensure_ascii=False)
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def stub_provider(*args, **kwargs):
        calls.append(1)
        return StubResponse()

    monkeypatch.setattr(model_governance.urllib.request, "urlopen", stub_provider)
    ids = []
    actors = []
    try:
        with SessionLocal.begin() as db:
            for _ in range(2):
                user = UserModel(username=f"test-{uuid4().hex}", password_hash="test", display_name="测试", role="citizen", is_active=True)
                db.add(user)
                db.flush()
                ids.append(user.id)
        actors = [hashlib.sha256(f"user:{uid}".encode()).hexdigest() for uid in ids]
        client = TestClient(app)
        def post(user_id):
            token = create_access_token(user_id, "citizen")
            return client.post("/api/v1/ai/pre-review", headers={"Authorization": f"Bearer {token}"}, json={"description": "社区路灯损坏需要维修"})
        assert post(ids[0]).status_code == 200
        assert post(ids[0]).status_code == 200  # rate-limited model degrades to rules
        assert post(ids[1]).status_code == 200
        assert len(calls) == 2
        with SessionLocal() as db:
            rows = db.execute(select(ModelCallModel.actor).where(ModelCallModel.actor.in_(actors))).scalars().all()
            assert sorted(rows) == sorted(actors)
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(AiUsageLogModel).where(AiUsageLogModel.user_id.in_(ids)))
            db.execute(delete(ModelCallModel).where(ModelCallModel.actor.in_(actors)))
            db.execute(delete(UserModel).where(UserModel.id.in_(ids)))
