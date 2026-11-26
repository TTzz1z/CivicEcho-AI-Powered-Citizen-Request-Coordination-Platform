"""Background worker: SLA due-soon scanning and notification outbox delivery.

Run with: python -m app.worker
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from itertools import islice
from threading import Thread
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from opentelemetry.propagate import extract
from opentelemetry.trace import StatusCode
from .telemetry import tracer

from .config import get_settings
from .database import SessionLocal
from .models import (
    AiUsageLogModel, KbDocumentModel, KbFeedbackModel, KbNoAnswerQuestionModel, ModelCallModel,
    NotificationModel, NotificationOutboxModel, TicketAttachmentModel, TicketModel, UserModel,
)
from .rate_limit import LoginRateLimiter
from .repositories.aftercare import AftercareRepository
from .storage import get_kb_object_storage, get_object_storage

logger = logging.getLogger("worker")
RETENTION_BATCH_SIZE = 500
SLA_EVENT_TYPES = ("ticket_due_soon", "ticket_overdue")
ATTACHMENT_KEY = re.compile(r"tickets/[A-Z0-9]{4,32}/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
KB_KEY = re.compile(r"docs/[0-9]+/[0-9a-f]{32}_[^/]+")


@dataclass(frozen=True)
class WorkerHealth:
    last_scan_at: datetime | None = None
    outbox_pending: int = 0
    outbox_failed: int = 0
    oldest_due_at: datetime | None = None

    def readiness(self, now: datetime, maximum_age: timedelta) -> tuple[int, dict]:
        stale = self.last_scan_at is None or now - self.last_scan_at > maximum_age
        delayed = self.oldest_due_at is not None and now - self.oldest_due_at > maximum_age
        ready = not stale and not delayed
        return (200 if ready else 503), {
            "status": "ok" if ready else "not_ready",
            "last_scan_time": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "outbox_pending": self.outbox_pending,
            "outbox_failed": self.outbox_failed,
            "outbox_oldest_due_at": self.oldest_due_at.isoformat() if self.oldest_due_at else None,
            "scan_stale": stale,
            "outbox_delayed": delayed,
        }


_worker_health = WorkerHealth()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health/live":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/health/ready":
            maximum_age = timedelta(seconds=max(30, 3 * get_settings().worker_scan_interval_seconds))
            status, payload = _worker_health.readiness(datetime.now(timezone.utc), maximum_age)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def _start_health_server(port: int = 8000) -> None:
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)  # noqa: S104
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("worker health server listening on :%d", port)


def _duty_agent_ids(db) -> list[int]:
    """Return the duty agent(s) for unassigned ticket queue notifications.

    P0-G+: instead of broadcasting to ALL agents, notify only the first
    active agent (the "duty agent" in demo). In production this would be
    replaced by a real on-call roster.
    """
    return list(db.scalars(select(UserModel.id).where(
        UserModel.role == "agent", UserModel.is_active.is_(True)
    ).order_by(UserModel.id).limit(1)).all())


def _work_order_assignee_ids(ticket: TicketModel, db) -> list[int]:
    """Return active work order assignees for the ticket (P0-G+)."""
    from .models import WorkOrderModel
    return list(db.scalars(select(WorkOrderModel.assignee_user_id).where(
        WorkOrderModel.ticket_id == ticket.ticket_id,
        WorkOrderModel.assignee_user_id.is_not(None),
        WorkOrderModel.status.notin_(("returned", "transferred", "cancelled")),
    )).all())


def _recipients_for_ticket(event_type: str, ticket: TicketModel, db) -> set[int]:
    """Determine notification recipients using the same logic as AftercareService.

    P0-G+ round-2 narrowing:
    - ticket_due_soon (normal approaching deadline):
      * pending: notify only duty agent (single agent, not all agents)
      * assigned/processing: notify assigned_user + primary dept staff + work order assignees
      * admins are NOT notified for normal due_soon (only for overdue escalation)
      * citizens never receive internal SLA due_soon notifications
    - ticket_overdue (deadline already passed, escalation):
      * notify assigned_user + primary dept staff + all admins (escalation)
    """
    recipients: set[int] = set()
    if event_type == "ticket_due_soon":
        if ticket.status == "pending":
            # Pending: notify only the duty agent (not all agents)
            recipients.update(_duty_agent_ids(db))
        else:
            # assigned/processing: notify assigned_user + primary dept staff + work order assignees
            if ticket.assigned_user_id:
                recipients.add(ticket.assigned_user_id)
            elif ticket.assigned_department_id:
                dept_users = db.scalars(select(UserModel.id).where(
                    UserModel.role == "department_staff",
                    UserModel.department_id == ticket.assigned_department_id,
                    UserModel.is_active.is_(True),
                )).all()
                recipients.update(dept_users)
            # Also notify work order assignees (P0-G+: actual handler)
            recipients.update(_work_order_assignee_ids(ticket, db))
        return recipients
    if event_type == "ticket_overdue":
        # Escalation: notify assigned_user + dept staff + all admins
        if ticket.assigned_user_id:
            recipients.add(ticket.assigned_user_id)
        elif ticket.assigned_department_id:
            dept_users = db.scalars(select(UserModel.id).where(
                UserModel.role == "department_staff",
                UserModel.department_id == ticket.assigned_department_id,
                UserModel.is_active.is_(True),
            )).all()
            recipients.update(dept_users)
        recipients.update(_work_order_assignee_ids(ticket, db))
        admins = db.scalars(select(UserModel.id).where(
            UserModel.role == "admin",
            UserModel.is_active.is_(True),
        )).all()
        recipients.update(admins)
        return recipients
    # Other events: keep existing logic
    if ticket.creator_user_id:
        recipients.add(ticket.creator_user_id)
    if event_type in {"ticket_assigned", "appeal_approved", "appeal_completed"}:
        if ticket.assigned_user_id:
            recipients.add(ticket.assigned_user_id)
        elif ticket.assigned_department_id:
            dept_users = db.scalars(select(UserModel.id).where(
                UserModel.role == "department_staff",
                UserModel.department_id == ticket.assigned_department_id,
                UserModel.is_active.is_(True),
            )).all()
            recipients.update(dept_users)
    if event_type == "appeal_submitted":
        admins = db.scalars(select(UserModel.id).where(
            UserModel.role == "admin",
            UserModel.is_active.is_(True),
        )).all()
        recipients.update(admins)
        recipients.discard(ticket.creator_user_id)
    return recipients


def scan_due_soon(db) -> int:
    """Find tickets approaching their SLA deadline and enqueue outbox notifications.

    P0-G: idempotency key now includes handling_round + threshold_level to
    satisfy the 5-element uniqueness requirement. Resolved/closed/paused
    tickets are excluded by the status filter.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=settings.worker_due_soon_hours)
    tickets = AftercareRepository(db).due_soon_tickets(threshold, now=now)

    created = 0
    threshold_level = "due_soon"
    for ticket in tickets:
        deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
        occurrence = deadline.isoformat() if deadline else str(ticket.version)
        handling_round = ticket.handling_round or 1
        recipients = _recipients_for_ticket("ticket_due_soon", ticket, db)
        for user_id in recipients:
            # P0-G: idempotency key = event_type:ticket_id:r{handling_round}:{threshold_level}:{occurrence}:user_id
            idempotency_key = f"ticket_due_soon:{ticket.ticket_id}:r{handling_round}:{threshold_level}:{occurrence}:{user_id}"
            inserted_id = db.scalar(insert(NotificationOutboxModel).values(
                id=str(uuid4()),
                event_type="ticket_due_soon",
                recipient_user_id=user_id,
                ticket_id=ticket.ticket_id,
                channel="in_app",
                title="工单即将超时",
                content=f"工单 {ticket.ticket_id} 距办理时限不足 {settings.worker_due_soon_hours} 小时，请及时处理。",
                status="pending",
                idempotency_key=idempotency_key,
                next_retry_at=now,
            ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(NotificationOutboxModel.id))
            created += int(inserted_id is not None)
    if created:
        db.commit()
        logger.info("scan_due_soon enqueued %d outbox items", created)
    return created


def scan_overdue(db) -> int:
    """P0-G+: scan overdue tickets and enqueue escalation outbox notifications.

    Overdue tickets are escalated to assigned_user + dept staff + work order
    assignees + ALL admins. Idempotency key uses threshold_level="overdue".
    """
    now = datetime.now(timezone.utc)

    tickets = AftercareRepository(db).overdue_tickets(now=now)

    created = 0
    threshold_level = "overdue"
    for ticket in tickets:
        deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
        occurrence = deadline.isoformat() if deadline else str(ticket.version)
        handling_round = ticket.handling_round or 1
        recipients = _recipients_for_ticket("ticket_overdue", ticket, db)
        for user_id in recipients:
            idempotency_key = f"ticket_overdue:{ticket.ticket_id}:r{handling_round}:{threshold_level}:{occurrence}:{user_id}"
            inserted_id = db.scalar(insert(NotificationOutboxModel).values(
                id=str(uuid4()),
                event_type="ticket_overdue",
                recipient_user_id=user_id,
                ticket_id=ticket.ticket_id,
                channel="in_app",
                title="工单已超时",
                content=f"工单 {ticket.ticket_id} 已超过办理时限，请立即处理或升级。",
                status="pending",
                idempotency_key=idempotency_key,
                next_retry_at=now,
            ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(NotificationOutboxModel.id))
            created += int(inserted_id is not None)
    if created:
        db.commit()
        logger.info("scan_overdue enqueued %d escalation outbox items", created)
    return created


def process_outbox(db) -> int:
    """Deliver pending outbox items as in-app notifications with retry logic.

    P0-G: event_key now matches the idempotency_key format (which includes
    handling_round + threshold_level) so duplicate detection stays consistent
    between outbox and direct emit paths.
    """
    now = datetime.now(timezone.utc)
    items = list(db.scalars(select(NotificationOutboxModel).where(
        NotificationOutboxModel.status == "pending",
        or_(
            NotificationOutboxModel.next_retry_at.is_(None),
            NotificationOutboxModel.next_retry_at <= now,
        ),
    ).order_by(NotificationOutboxModel.created_at, NotificationOutboxModel.id)
        .with_for_update(skip_locked=True).limit(50)).all())

    delivered = 0
    for item in items:
        parent = extract({"traceparent": item.traceparent}) if item.traceparent else None
        with tracer.start_as_current_span("outbox.deliver", context=parent, record_exception=False) as span:
            savepoint = None
            try:
                savepoint = db.begin_nested()
                # P0-G: event_key must match the idempotency_key format used by
                # AftercareService.emit so duplicates are detected across paths.
                event_key = item.idempotency_key
                db.execute(insert(NotificationModel).values(
                    id=str(uuid4()),
                    recipient_user_id=item.recipient_user_id,
                    ticket_id=item.ticket_id,
                    event_type=item.event_type,
                    channel=item.channel,
                    title=item.title,
                    content=item.content,
                    status="unread",
                    delivery_status="delivered",
                    event_key=event_key,
                    metadata_json=json.dumps({"ticket_id": item.ticket_id, "outbox_id": item.id}, ensure_ascii=False),
                ).on_conflict_do_nothing(index_elements=["event_key"]))
                item.status = "sent"
                item.sent_at = now
                db.flush()
                savepoint.commit()
                delivered += 1
            except Exception as exc:  # noqa: BLE001
                span.set_status(StatusCode.ERROR)
                if savepoint is not None:
                    savepoint.rollback()
                item.retry_count += 1
                item.error_message = str(exc)[:500]
                if item.retry_count >= item.max_retries:
                    item.status = "failed"
                    logger.error("outbox %s permanently failed: %s", item.id, exc)
                else:
                    backoff = min(2 ** item.retry_count * 30, 3600)
                    item.next_retry_at = now + timedelta(seconds=backoff)
                    logger.warning("outbox %s retry %d/%d, next in %ds", item.id, item.retry_count, item.max_retries, backoff)
    db.commit()
    if delivered:
        logger.info("process_outbox delivered %d notifications", delivered)
    return delivered


def _delete_retained_batch(db, model, *conditions) -> int:
    batch = (select(model.id).where(*conditions).order_by(model.created_at, model.id)
             .limit(RETENTION_BATCH_SIZE).with_for_update(skip_locked=True))
    return db.execute(delete(model).where(model.id.in_(batch))).rowcount


def cleanup_expired_conversations(db, retention_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    _delete_retained_batch(db, ModelCallModel, ModelCallModel.created_at < cutoff)
    _delete_retained_batch(db, AiUsageLogModel,
        AiUsageLogModel.user_id.is_(None),
        AiUsageLogModel.role == "anonymous",
        AiUsageLogModel.created_at < cutoff,
    )
    _delete_retained_batch(db, KbNoAnswerQuestionModel,
        KbNoAnswerQuestionModel.user_id.is_(None),
        KbNoAnswerQuestionModel.role == "anonymous",
        KbNoAnswerQuestionModel.created_at < cutoff,
    )
    db.commit()


def cleanup_expired_business_data(db, *, outbox_days: int, ai_days: int) -> None:
    now = datetime.now(timezone.utc)
    outbox_cutoff = now - timedelta(days=outbox_days)
    ai_cutoff = now - timedelta(days=ai_days)
    active_ticket = select(TicketModel.id).where(
        TicketModel.ticket_id == NotificationOutboxModel.ticket_id,
        TicketModel.status.in_(("pending", "accepted", "assigned", "processing")),
    ).exists()
    # Active SLA reminders need the key even when delivery permanently failed.
    outbox = _delete_retained_batch(db, NotificationOutboxModel,
        NotificationOutboxModel.status.in_(("sent", "failed")),
        func.coalesce(NotificationOutboxModel.sent_at, NotificationOutboxModel.created_at) < outbox_cutoff,
        or_(NotificationOutboxModel.event_type.notin_(SLA_EVENT_TYPES), ~active_ticket),
    )
    usage = _delete_retained_batch(db, AiUsageLogModel, AiUsageLogModel.created_at < ai_cutoff)
    feedback = _delete_retained_batch(db, KbFeedbackModel, KbFeedbackModel.created_at < ai_cutoff)
    resolved_questions = _delete_retained_batch(db, KbNoAnswerQuestionModel,
        KbNoAnswerQuestionModel.status.in_(("resolved", "wont_fix")),
        func.coalesce(KbNoAnswerQuestionModel.resolved_at, KbNoAnswerQuestionModel.created_at) < ai_cutoff,
    )
    db.commit()
    logger.info("retention removed outbox=%d usage=%d feedback=%d resolved_questions=%d",
                outbox, usage, feedback, resolved_questions)


def reap_old_objects(db, storage, prefix: str, previous_key: str | None, grace_days: int) -> str | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    entries = list(islice(storage.iter_object_entries(prefix, previous_key), RETENTION_BATCH_SIZE))
    key_pattern = ATTACHMENT_KEY if prefix == "tickets/" else KB_KEY
    candidates = {key for key, modified_at in entries
                  if modified_at is not None and modified_at < cutoff and key_pattern.fullmatch(key)}
    if candidates:
        if prefix == "tickets/":
            protected = select(TicketAttachmentModel.object_key).where(
                TicketAttachmentModel.storage_bucket == storage.bucket,
                TicketAttachmentModel.object_key.in_(candidates),
                or_(TicketAttachmentModel.is_deleted.is_(False), TicketAttachmentModel.deleted_at.is_(None),
                    TicketAttachmentModel.deleted_at >= cutoff),
            )
        else:
            protected = select(KbDocumentModel.storage_key).where(KbDocumentModel.storage_key.in_(candidates))
        removable = candidates.difference(db.scalars(protected))
        removed = 0
        failed = 0
        for key in removable:
            try:
                storage.delete(key)
                removed += 1
            except Exception:  # noqa: BLE001
                failed += 1
        logger.info("object retention prefix=%s examined=%d deleted=%d failed=%d", prefix, len(entries), removed, failed)
    return entries[-1][0] if len(entries) == RETENTION_BATCH_SIZE else None


def _collect_health(db) -> WorkerHealth:
    now = datetime.now(timezone.utc)
    pending = NotificationOutboxModel.status == "pending"
    retry_due_at = func.coalesce(NotificationOutboxModel.next_retry_at, NotificationOutboxModel.created_at)
    pending_count, failed_count, oldest_due_at = db.execute(select(
        func.count().filter(pending),
        func.count().filter(NotificationOutboxModel.status == "failed"),
        func.min(retry_due_at).filter(pending, retry_due_at <= now),
    )).one()
    return WorkerHealth(now, pending_count, failed_count, oldest_due_at)


def max_rate_limit_window_seconds(settings) -> int:
    return max(
        settings.login_rate_limit_window_seconds,
        settings.register_rate_limit_window_seconds,
        settings.anon_ticket_rate_limit_window_seconds,
        settings.upload_rate_limit_window_seconds,
        settings.ai_rate_limit_window_seconds,
        settings.export_rate_limit_window_seconds,
    )


def run_worker() -> None:
    settings = get_settings()
    _setup_logging(settings.log_level)
    logger.info("worker starting (interval=%ds, due_soon_hours=%d)", settings.worker_scan_interval_seconds, settings.worker_due_soon_hours)
    _start_health_server(8000)

    limiter = LoginRateLimiter(settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)
    next_cleanup = 0.0
    last_object_keys: dict[str, str | None] = {"tickets/": None, "docs/": None}
    while True:
        try:
            with SessionLocal() as db:
                scan_due_soon(db)
                scan_overdue(db)
                process_outbox(db)
                global _worker_health
                _worker_health = _collect_health(db)
            limiter.cleanup_expired(max_window_seconds=max_rate_limit_window_seconds(get_settings()))
        except Exception:  # noqa: BLE001
            logger.exception("worker cycle failed")
        if time.monotonic() >= next_cleanup:
            next_cleanup = time.monotonic() + 3600
            try:
                with SessionLocal() as db:
                    cleanup_expired_conversations(db, settings.anonymous_retention_days)
                    cleanup_expired_business_data(db, outbox_days=settings.worker_outbox_retention_days,
                                                  ai_days=settings.worker_ai_retention_days)
            except Exception:  # noqa: BLE001
                logger.exception("worker record retention failed")
            for prefix, storage_factory in (("tickets/", get_object_storage), ("docs/", get_kb_object_storage)):
                try:
                    with SessionLocal() as db:
                        last_object_keys[prefix] = reap_old_objects(
                            db, storage_factory(), prefix, last_object_keys[prefix], settings.worker_orphan_grace_days,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("worker object retention failed prefix=%s reason=%s", prefix, type(exc).__name__)
        time.sleep(settings.worker_scan_interval_seconds)


if __name__ == "__main__":
    run_worker()
