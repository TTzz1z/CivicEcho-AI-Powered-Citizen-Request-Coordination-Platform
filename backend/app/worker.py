"""Background worker: SLA due-soon scanning and notification outbox delivery.

Run with: python -m app.worker
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from uuid import uuid4

from sqlalchemy import func, or_, select

from .config import get_settings
from .database import SessionLocal
from .models import NotificationModel, NotificationOutboxModel, TicketModel, UserModel
from .rate_limit import LoginRateLimiter

logger = logging.getLogger("worker")
_last_scan_time: str | None = None
_outbox_pending: int = 0
_outbox_failed: int = 0


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
            import json as _json
            payload = _json.dumps({
                "status": "ok",
                "last_scan_time": _last_scan_time,
                "outbox_pending": _outbox_pending,
                "outbox_failed": _outbox_failed,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
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
    threshold = datetime.now(timezone.utc) + timedelta(hours=settings.worker_due_soon_hours)
    now = datetime.now(timezone.utc)

    tickets = list(db.scalars(select(TicketModel).where(
        TicketModel.status.in_(("pending", "accepted", "assigned", "processing")),
        TicketModel.sla_paused_at.is_(None),
        or_(
            TicketModel.accept_due_at.between(now, threshold),
            TicketModel.resolve_due_at.between(now, threshold),
        ),
    )).all())

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
            existing = db.scalar(select(NotificationOutboxModel.id).where(
                NotificationOutboxModel.idempotency_key == idempotency_key
            ))
            if existing:
                continue
            db.add(NotificationOutboxModel(
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
            ))
            created += 1
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

    tickets = list(db.scalars(select(TicketModel).where(
        TicketModel.status.in_(("pending", "accepted", "assigned", "processing")),
        TicketModel.sla_paused_at.is_(None),
        or_(
            (TicketModel.accept_due_at.is_not(None)) & (TicketModel.accept_due_at < now),
            (TicketModel.resolve_due_at.is_not(None)) & (TicketModel.resolve_due_at < now),
        ),
    )).all())

    created = 0
    threshold_level = "overdue"
    for ticket in tickets:
        deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
        occurrence = deadline.isoformat() if deadline else str(ticket.version)
        handling_round = ticket.handling_round or 1
        recipients = _recipients_for_ticket("ticket_overdue", ticket, db)
        for user_id in recipients:
            idempotency_key = f"ticket_overdue:{ticket.ticket_id}:r{handling_round}:{threshold_level}:{occurrence}:{user_id}"
            existing = db.scalar(select(NotificationOutboxModel.id).where(
                NotificationOutboxModel.idempotency_key == idempotency_key
            ))
            if existing:
                continue
            db.add(NotificationOutboxModel(
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
            ))
            created += 1
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
    ).limit(50)).all())

    delivered = 0
    for item in items:
        try:
            # P0-G: event_key must match the idempotency_key format used by
            # AftercareService.emit so duplicates are detected across paths.
            event_key = item.idempotency_key
            existing_notification = db.scalar(select(NotificationModel.id).where(
                NotificationModel.event_key == event_key
            ))
            if not existing_notification:
                db.add(NotificationModel(
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
                ))
            item.status = "sent"
            item.sent_at = now
            delivered += 1
        except Exception as exc:  # noqa: BLE001
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


def run_worker() -> None:
    settings = get_settings()
    _setup_logging(settings.log_level)
    logger.info("worker starting (interval=%ds, due_soon_hours=%d)", settings.worker_scan_interval_seconds, settings.worker_due_soon_hours)
    _start_health_server(8000)

    while True:
        try:
            with SessionLocal() as db:
                scan_due_soon(db)
                scan_overdue(db)
                process_outbox(db)
            # Periodic cleanup of expired login attempts
            limiter = LoginRateLimiter(settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)
            limiter.cleanup_expired()
            # Update health status
            from datetime import datetime as _dt, timezone as _tz
            global _last_scan_time, _outbox_pending, _outbox_failed
            _last_scan_time = _dt.now(_tz.utc).isoformat()
            with SessionLocal() as db:
                _outbox_pending = int(db.scalar(select(func.count(NotificationOutboxModel.id)).where(NotificationOutboxModel.status == "pending")) or 0)
                _outbox_failed = int(db.scalar(select(func.count(NotificationOutboxModel.id)).where(NotificationOutboxModel.status == "failed")) or 0)
        except Exception:  # noqa: BLE001
            logger.exception("worker cycle failed")
        time.sleep(settings.worker_scan_interval_seconds)


if __name__ == "__main__":
    run_worker()
