"""SQL verification for P0-G+ notification scope narrowing.

Verifies:
1. Notifications generated per pending ticket (should be 1: duty agent only).
2. Notifications generated per processing ticket (assigned_user + dept staff + work order assignees; NOT all agents).
3. Admin notifications for normal due_soon (should be 0).
4. Idempotency: rerunning scan_due_soon should not create duplicates.

Runs in the backend container so it has DB access. Usage:
    docker compose exec backend python scripts/verify_notification_scope.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    NotificationModel,
    NotificationOutboxModel,
    TicketModel,
    UserModel,
    WorkOrderModel,
)
from app.worker import (  # noqa: E402
    _recipients_for_ticket,
    scan_due_soon,
    scan_overdue,
)


def _format_recipients(recipient_ids: set[int], db) -> dict[int, str]:
    if not recipient_ids:
        return {}
    rows = db.scalars(select(UserModel).where(UserModel.id.in_(recipient_ids))).all()
    return {r.id: f"{r.role}:{r.display_name}" for r in rows}


def main() -> None:
    print("=" * 80)
    print("P0-G+ notification scope verification")
    print("=" * 80)
    with SessionLocal() as db:
        # 1. Inspect each open ticket's due_soon recipients (without writing).
        pending_tickets = list(db.scalars(select(TicketModel).where(
            TicketModel.status == "pending"
        ).limit(5)).all())
        print(f"\n[1] Pending tickets due_soon recipient preview (top 5):")
        for t in pending_tickets:
            recipients = _recipients_for_ticket("ticket_due_soon", t, db)
            labels = _format_recipients(recipients, db)
            print(f"  - {t.ticket_id} status={t.status} assigned_user_id={t.assigned_user_id} "
                  f"assigned_dept={t.assigned_department_id}")
            print(f"    recipients({len(recipients)}): {labels}")

        processing_tickets = list(db.scalars(select(TicketModel).where(
            TicketModel.status == "processing"
        ).limit(5)).all())
        print(f"\n[2] Processing tickets due_soon recipient preview (top 5):")
        for t in processing_tickets:
            recipients = _recipients_for_ticket("ticket_due_soon", t, db)
            labels = _format_recipients(recipients, db)
            print(f"  - {t.ticket_id} status={t.status} assigned_user_id={t.assigned_user_id} "
                  f"assigned_dept={t.assigned_department_id}")
            work_order_assignees = db.scalars(select(WorkOrderModel.assignee_user_id).where(
                WorkOrderModel.ticket_id == t.ticket_id,
                WorkOrderModel.assignee_user_id.is_not(None),
                WorkOrderModel.status.notin_(("returned", "transferred", "cancelled")),
            )).all()
            print(f"    work_order_assignees={list(work_order_assignees)}")
            print(f"    recipients({len(recipients)}): {labels}")

        # 3. Count admins in due_soon recipient sets across all pending+processing tickets.
        admin_ids = set(db.scalars(select(UserModel.id).where(
            UserModel.role == "admin", UserModel.is_active.is_(True)
        )).all())
        print(f"\n[3] Admin due_soon notification count (normal threshold):")
        print(f"    admin user ids: {admin_ids}")
        admin_due_soon_count = 0
        all_open_tickets = list(db.scalars(select(TicketModel).where(
            TicketModel.status.in_(("pending", "accepted", "assigned", "processing"))
        )).all())
        for t in all_open_tickets:
            recipients = _recipients_for_ticket("ticket_due_soon", t, db)
            admin_in_set = recipients & admin_ids
            if admin_in_set:
                admin_due_soon_count += len(admin_in_set)
                print(f"    ⚠ {t.ticket_id}: admin in due_soon recipients: {admin_in_set}")
        print(f"    Total admin entries across all due_soon tickets: {admin_due_soon_count} (expected 0)")

        # 4. Snapshot notification counts before scan, then run scan twice.
        print(f"\n[4] Idempotency test — running scan_due_soon twice and scan_overdue twice:")
        before_outbox = int(db.scalar(select(func.count(NotificationOutboxModel.id))) or 0)
        before_notif = int(db.scalar(select(func.count(NotificationModel.id))) or 0)
        print(f"    before: outbox={before_outbox} notifications={before_notif}")

        # Force every pending ticket to be "due_soon" so we can exercise the code path.
        # We temporarily set accept_due_at to 1 hour from now for pending tickets,
        # and resolve_due_at to 1 hour from now for processing/assigned tickets.
        now = datetime.now(timezone.utc)
        soon = now + timedelta(hours=1)
        previously_due = {}
        for t in all_open_tickets:
            previously_due[t.ticket_id] = (t.accept_due_at, t.resolve_due_at)
            if t.status == "pending":
                t.accept_due_at = soon
            else:
                t.resolve_due_at = soon
        db.commit()
        print(f"    Temporarily moved {len(all_open_tickets)} tickets' deadlines to ~1h from now")

        try:
            created1 = scan_due_soon(db)
            after_outbox_1 = int(db.scalar(select(func.count(NotificationOutboxModel.id))) or 0)
            print(f"    first scan_due_soon: created={created1} outbox_now={after_outbox_1}")

            created2 = scan_due_soon(db)
            after_outbox_2 = int(db.scalar(select(func.count(NotificationOutboxModel.id))) or 0)
            print(f"    second scan_due_soon: created={created2} outbox_now={after_outbox_2}")
            if created2 != 0:
                print("    ⚠ IDEMPOTENCY FAILURE: second scan_due_soon created new outbox items!")
            else:
                print("    ✓ Idempotency: second scan_due_soon created 0 new items")

            # Now run scan_overdue twice (tickets not yet overdue, so should produce 0).
            overdue1 = scan_overdue(db)
            print(f"    first scan_overdue (no overdue tickets expected): created={overdue1}")

            # Force tickets overdue to verify scan_overdue produces admin notifications.
            past = now - timedelta(hours=1)
            for t in all_open_tickets:
                if t.status == "pending":
                    t.accept_due_at = past
                else:
                    t.resolve_due_at = past
            db.commit()

            overdue2 = scan_overdue(db)
            print(f"    second scan_overdue (forced overdue): created={overdue2}")
            overdue_admin_count = int(db.scalar(select(func.count(NotificationOutboxModel.id)).where(
                NotificationOutboxModel.event_type == "ticket_overdue",
                NotificationOutboxModel.recipient_user_id.in_(admin_ids),
            )) or 0)
            print(f"    overdue outbox items addressed to admins: {overdue_admin_count}")

            overdue3 = scan_overdue(db)
            print(f"    third scan_overdue (idempotency): created={overdue3} (expected 0)")
            if overdue3 != 0:
                print("    ⚠ IDEMPOTENCY FAILURE: third scan_overdue created new items!")
            else:
                print("    ✓ Idempotency: third scan_overdue created 0 new items")
        finally:
            # Restore original deadlines so we don't disturb other tests.
            for t in all_open_tickets:
                orig_accept, orig_resolve = previously_due[t.ticket_id]
                t.accept_due_at = orig_accept
                t.resolve_due_at = orig_resolve
            db.commit()
            print(f"    Restored original deadlines for {len(all_open_tickets)} tickets")

        # 5. Per-ticket notification counts (using outbox since process_outbox may not have run yet).
        print(f"\n[5] Per-ticket outbox notification counts (current snapshot):")
        rows = db.execute(select(
            NotificationOutboxModel.ticket_id,
            NotificationOutboxModel.event_type,
            func.count(NotificationOutboxModel.id).label("cnt"),
        ).group_by(
            NotificationOutboxModel.ticket_id, NotificationOutboxModel.event_type
        ).order_by(
            NotificationOutboxModel.ticket_id, NotificationOutboxModel.event_type
        )).all()
        for row in rows:
            print(f"  {row.ticket_id} {row.event_type}: {row.cnt}")

    print("\n" + "=" * 80)
    print("Verification complete.")
    print("=" * 80)


if __name__ == "__main__":
    main()
