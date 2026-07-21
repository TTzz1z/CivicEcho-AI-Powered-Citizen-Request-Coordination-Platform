"""Cleanup test notifications created by verify_notification_scope.py.

The verification script temporarily forces tickets overdue and runs scan_overdue,
which creates test escalation notifications in the outbox. These would be
delivered by process_outbox over the next several hours. This script removes
them so the database stays clean for subsequent tests.

Usage:
    docker compose exec backend python /tmp/cleanup_verify_notifications.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import delete, func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import NotificationModel, NotificationOutboxModel  # noqa: E402


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    with SessionLocal() as db:
        # Delete test outbox items created in the last hour (verification script run).
        outbox_before = int(db.scalar(select(func.count(NotificationOutboxModel.id)).where(
            NotificationOutboxModel.created_at >= cutoff
        )) or 0)
        notif_before = int(db.scalar(select(func.count(NotificationModel.id)).where(
            NotificationModel.created_at >= cutoff
        )) or 0)
        print(f"Test items created in last hour: outbox={outbox_before} notifications={notif_before}")

        db.execute(delete(NotificationOutboxModel).where(
            NotificationOutboxModel.created_at >= cutoff
        ))
        db.execute(delete(NotificationModel).where(
            NotificationModel.created_at >= cutoff
        ))
        db.commit()

        outbox_after = int(db.scalar(select(func.count(NotificationOutboxModel.id))) or 0)
        notif_after = int(db.scalar(select(func.count(NotificationModel.id))) or 0)
        print(f"After cleanup: outbox={outbox_after} notifications={notif_after}")


if __name__ == "__main__":
    main()
