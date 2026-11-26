from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest
from sqlalchemy import select
from app import worker
from app.database import engine
from sqlalchemy.orm import Session
from app.models import AiUsageLogModel, DepartmentModel, KbDocumentModel, KbNoAnswerQuestionModel, NotificationOutboxModel, TicketModel, UserModel
from app.repositories.aftercare import AftercareRepository
from app.worker import WorkerHealth, cleanup_expired_business_data, cleanup_expired_conversations, reap_old_objects, scan_due_soon, scan_overdue


def test_cleanup_expired_anonymous_records():
    marker = uuid4().hex
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    recent = now - timedelta(days=1)
    with engine.connect() as connection, Session(bind=connection) as db:
        for role, created in [("anonymous", old), ("citizen", old), ("anonymous", recent)]:
            db.add(AiUsageLogModel(request_id=marker, role=role, model_name="test", model_tier="rules", created_at=created))
            db.add(KbNoAnswerQuestionModel(query_text=marker, role=role, created_at=created))
        db.commit()
        cleanup_expired_conversations(db, 30)
        assert len(list(db.scalars(select(AiUsageLogModel).where(AiUsageLogModel.request_id == marker)))) == 2
        assert len(list(db.scalars(select(KbNoAnswerQuestionModel).where(KbNoAnswerQuestionModel.query_text == marker)))) == 2
        db.commit()


def test_worker_scans_only_the_active_sla_deadline():
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    soon = now + timedelta(hours=1)
    later = now + timedelta(days=2)
    marker = uuid4().hex[:8].upper()
    with engine.connect() as connection, connection.begin(), Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        def ticket(label, status, accept_due_at, resolve_due_at, sla_paused_at=None):
            return TicketModel(ticket_id=f"QT{marker}{label}", idempotency_key=uuid4().hex, request_type="投诉",
                               description="测试工单", location="测试道路", status=status,
                               accept_due_at=accept_due_at, resolve_due_at=resolve_due_at, sla_paused_at=sla_paused_at)

        overdue_pending = ticket("A", "pending", past, later)
        soon_processing = ticket("B", "processing", past, soon)
        wrong_pending = ticket("C", "pending", later, past)
        wrong_processing = ticket("D", "processing", past, later)
        paused = ticket("E", "processing", past, past, past)
        closed = ticket("F", "closed", past, past)
        department = DepartmentModel(code=f"sla_dept_{marker}", name=f"SLA test department {marker}")
        db.add(department)
        db.flush()
        staff = UserModel(username=f"sla_staff_{marker}", password_hash="unused", display_name="SLA test staff",
                          role="department_staff", department_id=department.id)
        soon_processing.assignee = staff
        soon_processing.department = department
        db.add_all([overdue_pending, soon_processing, wrong_pending, wrong_processing, paused, closed])
        db.add(UserModel(username=f"sla_admin_{marker}", password_hash="unused", display_name="SLA test", role="admin"))
        db.flush()
        repo = AftercareRepository(db)
        assert {row.ticket_id for row in repo.due_soon_tickets(soon, now=now) if marker in row.ticket_id} == {soon_processing.ticket_id}
        assert {row.ticket_id for row in repo.overdue_tickets(now=now) if marker in row.ticket_id} == {overdue_pending.ticket_id}
        scan_due_soon(db)
        scan_overdue(db)
        rows = db.execute(select(NotificationOutboxModel.ticket_id, NotificationOutboxModel.event_type)
                          .where(NotificationOutboxModel.ticket_id.like(f"QT{marker}%"))).all()
        assert set(rows) == {(overdue_pending.ticket_id, "ticket_overdue"), (soon_processing.ticket_id, "ticket_due_soon")}
        connection.rollback()


def test_worker_readiness_requires_first_and_recent_success():
    now = datetime.now(timezone.utc)
    maximum_age = timedelta(minutes=3)
    assert WorkerHealth().readiness(now, maximum_age)[0] == 503
    assert WorkerHealth(now).readiness(now, maximum_age)[0] == 200
    assert WorkerHealth(now - timedelta(minutes=4)).readiness(now, maximum_age)[1]["scan_stale"] is True
    delayed = WorkerHealth(last_scan_at=now, outbox_pending=80, oldest_due_at=now - timedelta(minutes=4))
    status, payload = delayed.readiness(now, maximum_age)
    assert status == 503 and payload["outbox_delayed"] is True and payload["outbox_pending"] == 80


def test_worker_http_liveness_and_readiness_are_independent(monkeypatch):
    monkeypatch.setattr(worker, "_worker_health", WorkerHealth())
    with HTTPServer(("127.0.0.1", 0), worker._HealthHandler) as server:
        worker_thread = Thread(target=server.serve_forever, daemon=True)
        worker_thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(f"{base_url}/health/live", timeout=2) as response:
                assert response.status == 200
            with pytest.raises(HTTPError) as not_ready:
                urlopen(f"{base_url}/health/ready", timeout=2)
            with not_ready.value as response:
                assert response.status == 503
            monkeypatch.setattr(worker, "_worker_health", WorkerHealth(datetime.now(timezone.utc)))
            with urlopen(f"{base_url}/health/ready", timeout=2) as response:
                assert response.status == 200
        finally:
            server.shutdown()
            worker_thread.join(timeout=2)


def test_business_retention_preserves_pending_deliveries_and_open_questions():
    now = datetime.now(timezone.utc)
    marker = uuid4().hex
    old = now - timedelta(days=200)
    with engine.connect() as connection, connection.begin(), Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        user = UserModel(username=f"retention_{marker}", password_hash="unused", display_name="Retention test", role="citizen")
        db.add(user)
        db.flush()
        for status, created_at in (("sent", old), ("failed", old), ("pending", old), ("sent", now)):
            db.add(NotificationOutboxModel(id=str(uuid4()), idempotency_key=f"{marker}:{status}:{created_at}",
                                          event_type="ticket_created", recipient_user_id=user.id,
                                          title="Retention test", content="Retention test", status=status, created_at=created_at))
        for status in ("open", "resolved"):
            db.add(KbNoAnswerQuestionModel(query_text=marker, role="citizen", user_id=user.id, status=status, created_at=old))
        db.add(AiUsageLogModel(request_id=marker, user_id=user.id, role="citizen", model_name="test", model_tier="rules", created_at=old))
        db.flush()
        cleanup_expired_business_data(db, outbox_days=90, ai_days=180)
        assert set(db.scalars(select(NotificationOutboxModel.status).where(NotificationOutboxModel.recipient_user_id == user.id))) == {"pending", "sent"}
        assert db.scalars(select(KbNoAnswerQuestionModel.status).where(KbNoAnswerQuestionModel.query_text == marker)).all() == ["open"]
        assert db.scalar(select(AiUsageLogModel.id).where(AiUsageLogModel.request_id == marker)) is None
        connection.rollback()


def test_orphan_cleanup_keeps_referenced_recent_and_unknown_objects():
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    marker = uuid4().hex
    referenced = f"docs/1/{marker}_linked.pdf"
    orphan = f"docs/2/{marker}_old.pdf"
    recent = f"docs/3/{marker}_recent.pdf"
    unknown = "docs/manual-object.pdf"
    with engine.connect() as connection, connection.begin(), Session(bind=connection) as db:
        db.add(KbDocumentModel(title="Linked entry", storage_key=referenced))
        db.flush()
        delete_object = Mock()
        storage = SimpleNamespace(iter_object_entries=Mock(return_value=iter([
            (referenced, old), (orphan, old), (recent, now), (unknown, old),
        ])), delete=delete_object)
        assert reap_old_objects(db, storage, "docs/", None, grace_days=7) is None
        delete_object.assert_called_once_with(orphan)
        db.rollback()
