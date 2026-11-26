"""Test fixtures: keep unit tests hermetic and deterministic.

Unit tests must never call the real LLM. We force rule-based AI regardless of
the container environment so assertions on rule output stay stable.
"""
import os

import pytest

# Override any container-provided key before app modules read settings.
os.environ["AI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "rules"

from app.config import get_settings  # noqa: E402
import app.llm_client as llm_client  # noqa: E402

get_settings.cache_clear()
llm_client._client = None


@pytest.fixture
def persisted_kb_admin():
    """An actual audit actor, independent of demo seed IDs."""
    from uuid import uuid4
    from sqlalchemy import delete
    from app.authorization import Principal
    from app.database import SessionLocal
    from app.models import AuditLogModel, UserModel

    username = f"kb_test_admin_{uuid4().hex}"
    with SessionLocal.begin() as db:
        user = UserModel(username=username, password_hash="unused", display_name="KB test admin", role="admin")
        db.add(user)
        db.flush()
        actor_id = user.id
    try:
        yield Principal("user", actor_id, username, "admin", None)
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(AuditLogModel).where(AuditLogModel.actor_user_id == actor_id))
            db.execute(delete(UserModel).where(UserModel.id == actor_id))
