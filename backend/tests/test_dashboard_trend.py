from datetime import date, datetime, timezone
from uuid import uuid4

from app.database import SessionLocal
from app.models import TicketModel
from app.repositories.analytics import AnalyticsRepository


def test_daily_intake_uses_local_midnight_and_excludes_window_end():
    prefix = uuid4().hex[:12]
    times = (
        datetime(2025, 2, 1, 15, 59, 59, tzinfo=timezone.utc),
        datetime(2025, 2, 1, 16, 0, tzinfo=timezone.utc),
        datetime(2025, 2, 2, 16, 0, tzinfo=timezone.utc),
    )
    with SessionLocal() as db:
        query = AnalyticsRepository(db)
        start, stop = date(2025, 2, 2), date(2025, 2, 3)
        original = query.daily_intake(start, stop, "Asia/Shanghai").get(start, 0)
        for index, timestamp in enumerate(times):
            db.add(TicketModel(
                ticket_id=f"trend-{prefix}-{index}", idempotency_key=f"trend-{prefix}-{index}",
                request_type="咨询", description="趋势边界测试", location="测试", source="test",
                priority="normal", status="pending", created_at=timestamp,
            ))
        db.flush()
        assert query.daily_intake(start, stop, "Asia/Shanghai") == {start: original + 1}
