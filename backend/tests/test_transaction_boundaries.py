"""Failure-injection tests for core business transaction boundaries.

Guarantees:
- audit / status-history failure rolls back ticket or work-order state
- notification delivery failure does not undo a committed business txn
- outbox delivery can retry after a transient failure
- create remains idempotent under the new commit=False path
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.authorization import Principal
from app.database import SessionLocal
from app.models import (
    AppealModel,
    AuditLogModel,
    DepartmentModel,
    NotificationModel,
    NotificationOutboxModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderModel,
)
from app.repositories.aftercare import AftercareRepository, NotificationRepository
from app.repositories.ai import AiRepository
from app.repositories.identity import AuditRepository, CategoryRepository, DepartmentRepository, UserRepository
from app.repositories.postgres import PostgreSQLTicketRepository
from app.repositories.work_orders import WorkOrderRepository
from app.schemas import TicketCreate, TicketResolve
from app.security import hash_password
from app.services.aftercare_service import AftercareService
from app.services.ai_service import AiService
from app.services.ticket_service import TicketService
from app.services.work_order_service import WorkOrderService
from app.worker import process_outbox
from app.config import get_settings
from app.models import AiSuggestionModel


PASSWORD = "TxnBoundary-Pytest-Only!"


def _principal(user: UserModel) -> Principal:
    return Principal(
        kind="user",
        user_id=user.id,
        username=user.username,
        role=user.role,
        department_id=user.department_id,
    )


@pytest.fixture
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        department = db.scalar(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).order_by(DepartmentModel.id))
        assert department is not None
        users = {}
        for role, dept in [
            ("citizen", None),
            ("agent", None),
            ("admin", None),
            ("department_staff", department),
        ]:
            user = UserModel(
                username=f"txn_{role}_{suffix}",
                password_hash=hash_password(PASSWORD),
                display_name=f"txn-{role}",
                role=role,
                department_id=dept.id if dept else None,
                is_active=True,
            )
            db.add(user)
            db.flush()
            users[role] = user.id
        db.commit()
        dept_id = department.id
    return {"users": users, "department_id": dept_id}


def _load_user(db, user_id: int) -> UserModel:
    return db.get(UserModel, user_id)


def _services(db):
    tickets = PostgreSQLTicketRepository(db)
    departments = DepartmentRepository(db)
    users = UserRepository(db)
    audit = AuditRepository(db)
    categories = CategoryRepository(db)
    work_orders = WorkOrderRepository(db)
    aftercare = AftercareService(AftercareRepository(db), NotificationRepository(db), audit)
    ticket_service = TicketService(tickets, departments, audit, users, categories, work_orders, aftercare)
    work_order_service = WorkOrderService(work_orders, departments, users, audit)
    return ticket_service, work_order_service, aftercare, audit


def _create_ticket(service: TicketService, citizen: UserModel) -> TicketModel:
    result = service.create(
        TicketCreate(
            idempotency_key=str(uuid4()),
            request_type="投诉",
            description="事务边界验证工单",
            location="测试路",
            source="txn-pytest",
        ),
        _principal(citizen),
    )
    return result.ticket


def test_audit_failure_rolls_back_accept(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        service, _, _, audit = _services(db)
        ticket = _create_ticket(service, citizen)
        ticket_id = ticket.ticket_id
        version = ticket.version

        original = audit.log

        def boom(*args, **kwargs):
            if kwargs.get("commit") is False or (len(args) > 1 and args[1] == "accept_ticket"):
                # Fail only the success audit path used inside the business txn.
                action = args[1] if len(args) > 1 else kwargs.get("action")
                if action == "accept_ticket":
                    raise RuntimeError("injected audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(audit, "log", boom)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            service.accept(ticket_id, version, "受理", _principal(agent))

        db.expire_all()
        persisted = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
        assert persisted is not None
        assert persisted.status == "pending"
        assert persisted.version == version
        history = list(db.scalars(
            select(TicketStatusHistoryModel).where(
                TicketStatusHistoryModel.ticket_id == ticket_id,
                TicketStatusHistoryModel.operation_type == "accept",
            )
        ).all())
        assert history == []
        audits = list(db.scalars(
            select(AuditLogModel).where(
                AuditLogModel.resource_id == ticket_id,
                AuditLogModel.action == "accept_ticket",
            )
        ).all())
        assert audits == []


def test_status_history_failure_rolls_back_process(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        staff = _load_user(db, actors["users"]["department_staff"])
        service, _, _, _ = _services(db)
        ticket = _create_ticket(service, citizen)
        accepted = service.accept(ticket.ticket_id, ticket.version, "受理", _principal(agent))
        assigned = service.assign(
            accepted.ticket_id, accepted.version, "派发", actors["department_id"], staff.id, _principal(agent),
        )
        before = db.scalar(select(TicketModel).where(TicketModel.ticket_id == assigned.ticket_id))
        assert before.status == "assigned"
        version = before.version

        original_add = db.add

        def add_fail(obj):
            if isinstance(obj, TicketStatusHistoryModel) and obj.operation_type == "process":
                raise RuntimeError("injected history failure")
            return original_add(obj)

        monkeypatch.setattr(db, "add", add_fail)
        with pytest.raises(RuntimeError, match="injected history failure"):
            service.process(assigned.ticket_id, version, "开始办理", _principal(staff))

        db.expire_all()
        persisted = db.scalar(select(TicketModel).where(TicketModel.ticket_id == assigned.ticket_id))
        assert persisted.status == "assigned"
        assert persisted.version == version


def test_notification_failure_keeps_business_commit(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        service, _, aftercare, _ = _services(db)
        ticket = _create_ticket(service, citizen)

        def boom(*_args, **_kwargs):
            raise RuntimeError("injected notification failure")

        monkeypatch.setattr(aftercare, "emit", boom)
        accepted = service.accept(ticket.ticket_id, ticket.version, "受理", _principal(agent))
        assert accepted.status == "accepted"

        db.expire_all()
        persisted = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket.ticket_id))
        assert persisted.status == "accepted"
        assert db.scalar(select(AuditLogModel.id).where(
            AuditLogModel.resource_id == ticket.ticket_id,
            AuditLogModel.action == "accept_ticket",
        ))
        assert db.scalar(select(TicketStatusHistoryModel.id).where(
            TicketStatusHistoryModel.ticket_id == ticket.ticket_id,
            TicketStatusHistoryModel.operation_type == "accept",
        ))


def test_outbox_delivery_failure_keeps_item_retryable(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        ticket = TicketModel(
            ticket_id=f"QT{datetime.now().strftime('%Y%m%d')}{uuid4().hex[:8].upper()}",
            status="pending",
            version=1,
            request_type="求助",
            description="outbox retry",
            location="测试",
            source="txn-pytest",
            idempotency_key=str(uuid4()),
            creator_user_id=citizen.id,
            accept_due_at=datetime.now(timezone.utc) + timedelta(hours=1),
            resolve_due_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
        db.add(ticket)
        db.flush()
        outbox = NotificationOutboxModel(
            id=str(uuid4()),
            event_type="ticket_due_soon",
            recipient_user_id=citizen.id,
            ticket_id=ticket.ticket_id,
            channel="in_app",
            title="工单即将超时",
            content=f"工单 {ticket.ticket_id} 距办理时限不足 4 小时",
            status="pending",
            idempotency_key=f"ticket_due_soon:{ticket.ticket_id}:r1:due_soon:test:{citizen.id}",
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            max_retries=3,
        )
        db.add(outbox)
        # Isolate this item from the shared demo DB outbox backlog.
        db.execute(
            NotificationOutboxModel.__table__.update()
            .where(
                NotificationOutboxModel.status == "pending",
                NotificationOutboxModel.id != outbox.id,
            )
            .values(next_retry_at=datetime.now(timezone.utc) + timedelta(days=30))
        )
        db.commit()
        outbox_id = outbox.id
        ticket_id = ticket.ticket_id

        calls = {"n": 0}
        original_add = db.add

        def flaky_add(obj):
            if isinstance(obj, NotificationModel) and obj.ticket_id == ticket_id:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("injected outbox delivery failure")
            return original_add(obj)

        monkeypatch.setattr(db, "add", flaky_add)
        process_outbox(db)
        assert calls["n"] == 1
        db.expire_all()
        item = db.get(NotificationOutboxModel, outbox_id)
        assert item is not None
        assert item.status == "pending"
        assert item.retry_count == 1
        assert item.next_retry_at is not None
        assert db.scalar(select(TicketModel.status).where(TicketModel.ticket_id == ticket_id)) == "pending"

        # Business ticket untouched; second delivery succeeds.
        monkeypatch.setattr(db, "add", original_add)
        item.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        process_outbox(db)
        db.expire_all()
        item = db.get(NotificationOutboxModel, outbox_id)
        assert item.status == "sent"
        assert db.scalar(select(NotificationModel.id).where(
            NotificationModel.event_key == item.idempotency_key
        ))


def test_create_ticket_idempotent_under_unified_commit(actors):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        service, _, _, _ = _services(db)
        key = str(uuid4())
        payload = TicketCreate(
            idempotency_key=key,
            request_type="投诉",
            description="幂等创建",
            location="测试路",
            source="txn-pytest",
        )
        first = service.create(payload, _principal(citizen))
        second = service.create(payload, _principal(citizen))
        assert first.replayed is False
        assert second.replayed is True
        assert first.ticket.ticket_id == second.ticket.ticket_id
        from sqlalchemy import func
        total = db.scalar(select(func.count()).select_from(TicketModel).where(TicketModel.idempotency_key == key))
        assert total == 1
        audits = list(db.scalars(
            select(AuditLogModel).where(
                AuditLogModel.action == "create_ticket",
                AuditLogModel.resource_id == first.ticket.ticket_id,
            )
        ).all())
        assert len(audits) == 1


def test_work_order_submit_audit_failure_rolls_back(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        staff = _load_user(db, actors["users"]["department_staff"])
        ticket_service, work_orders, _, audit = _services(db)
        ticket = _create_ticket(ticket_service, citizen)
        accepted = ticket_service.accept(ticket.ticket_id, ticket.version, "受理", _principal(agent))
        order = work_orders.create(
            accepted.ticket_id, accepted.version, "primary", actors["department_id"],
            staff.id, "主办任务", _principal(agent),
        )
        started = work_orders.start(order.id, order.version, "开始", _principal(staff))
        version = started.version

        original = audit.log

        def boom(*args, **kwargs):
            action = args[1] if len(args) > 1 else kwargs.get("action")
            if action == "submit_work_order_result":
                raise RuntimeError("injected wo audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(audit, "log", boom)
        with pytest.raises(RuntimeError, match="injected wo audit failure"):
            work_orders.submit(
                started.id, version, "提交结果", "摘要", "措施", "resolved", "公开答复", None, _principal(staff),
            )

        db.expire_all()
        persisted = db.get(WorkOrderModel, started.id)
        assert persisted.status == "processing"
        assert persisted.version == version


def test_review_resolve_and_appeal_audit_same_transaction(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        staff = _load_user(db, actors["users"]["department_staff"])
        admin = _load_user(db, actors["users"]["admin"])
        ticket_service, work_orders, aftercare, audit = _services(db)
        ticket = _create_ticket(ticket_service, citizen)
        accepted = ticket_service.accept(ticket.ticket_id, ticket.version, "受理", _principal(agent))
        order = work_orders.create(
            accepted.ticket_id, accepted.version, "primary", actors["department_id"],
            staff.id, "主办任务", _principal(agent),
        )
        started = work_orders.start(order.id, order.version, "开始", _principal(staff))
        submitted = work_orders.submit(
            started.id, started.version, "提交", "摘要", "措施", "resolved", "公开答复", None, _principal(staff),
        )
        del submitted
        # Refresh ticket version after submit
        current = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket.ticket_id))
        summarized = work_orders.summarize(
            current.ticket_id,
            TicketResolve(
                version=current.version,
                remark="汇总",
                resolution_summary="摘要",
                resolution_measures="措施",
                resolution_outcome="resolved",
                public_reply="公开答复",
                internal_note=None,
            ),
            _principal(staff),
        )
        assert summarized.collaboration_status == "awaiting_review"

        original = audit.log

        def boom_review(*args, **kwargs):
            action = args[1] if len(args) > 1 else kwargs.get("action")
            if action == "review_and_resolve":
                raise RuntimeError("injected review audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(audit, "log", boom_review)
        with pytest.raises(RuntimeError, match="injected review audit failure"):
            work_orders.review_and_resolve(
                summarized.ticket_id,
                TicketResolve(
                    version=summarized.version,
                    remark="审核通过",
                    resolution_summary="摘要",
                    resolution_measures="措施",
                    resolution_outcome="resolved",
                    public_reply="公开答复",
                    internal_note=None,
                ),
                _principal(agent),
            )
        db.expire_all()
        current = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket.ticket_id))
        assert current.status == "processing"
        assert current.collaboration_status == "awaiting_review"

        monkeypatch.setattr(audit, "log", original)
        resolved = work_orders.review_and_resolve(
            current.ticket_id,
            TicketResolve(
                version=current.version,
                remark="审核通过",
                resolution_summary="摘要",
                resolution_measures="措施",
                resolution_outcome="resolved",
                public_reply="公开答复",
                internal_note=None,
            ),
            _principal(agent),
        )
        assert resolved.status == "resolved"

        def boom_appeal(*args, **kwargs):
            action = args[1] if len(args) > 1 else kwargs.get("action")
            if action == "submit_appeal":
                raise RuntimeError("injected appeal audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(audit, "log", boom_appeal)
        before_version = resolved.version
        with pytest.raises(RuntimeError, match="injected appeal audit failure"):
            aftercare.create_appeal(resolved.ticket_id, "结果不服", "希望重办", _principal(citizen))
        db.expire_all()
        current = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket.ticket_id))
        assert current.version == before_version
        assert current.appeal_count == 0
        assert db.scalar(select(AppealModel.id).where(AppealModel.ticket_id == ticket.ticket_id)) is None


def test_ai_review_audit_failure_rolls_back_decision(actors, monkeypatch):
    with SessionLocal() as db:
        citizen = _load_user(db, actors["users"]["citizen"])
        agent = _load_user(db, actors["users"]["agent"])
        ticket_service, _, _, audit = _services(db)
        ticket = _create_ticket(ticket_service, citizen)
        suggestion = AiSuggestionModel(
            id=str(uuid4()),
            ticket_id=ticket.ticket_id,
            suggestion_type="completeness",
            status="completed",
            risk_level="none",
            confidence=80,
            provider="rules",
            model_name="rules",
            input_fingerprint=uuid4().hex,
            result_json='{"ok": true}',
            explanation="test",
            generated_by_user_id=agent.id,
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

        ai = AiService(AiRepository(db), audit, get_settings())
        original = audit.log

        def boom(*args, **kwargs):
            action = args[1] if len(args) > 1 else kwargs.get("action")
            if action and action.startswith("review_ai_suggestion"):
                raise RuntimeError("injected ai audit failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(audit, "log", boom)
        with pytest.raises(RuntimeError, match="injected ai audit failure"):
            ai.review(suggestion_id, "helpful", "ok", _principal(agent))

        db.expire_all()
        persisted = db.get(AiSuggestionModel, suggestion_id)
        assert persisted.review_decision is None
        assert persisted.reviewed_at is None
