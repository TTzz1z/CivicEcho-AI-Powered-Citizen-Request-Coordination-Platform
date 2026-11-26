from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import CategoryModel, DepartmentModel, TicketModel


class AnalyticsRepository:
    def __init__(self, db: Session):
        self.db = db

    def counts_by(self, column):
        return [(str(name), int(value)) for name, value in self.db.execute(
            select(column, func.count(TicketModel.id)).group_by(column)
        ).all()]

    def department_counts(self):
        rows = self.db.execute(
            select(DepartmentModel.name, func.count(TicketModel.id))
            .join(TicketModel, TicketModel.assigned_department_id == DepartmentModel.id)
            .group_by(DepartmentModel.id, DepartmentModel.name)
            .order_by(func.count(TicketModel.id).desc())
        ).all()
        return [(name, int(value)) for name, value in rows]

    def daily_intake(self, start: date, stop: date, timezone_name: str):
        zone = ZoneInfo(timezone_name)
        day = func.date(func.timezone(timezone_name, TicketModel.created_at))
        rows = self.db.execute(
            select(day, func.count(TicketModel.id))
            .where(
                TicketModel.created_at >= datetime.combine(start, time.min, tzinfo=zone),
                TicketModel.created_at < datetime.combine(stop, time.min, tzinfo=zone),
            )
            .group_by(day)
        ).all()
        return {key: int(value) for key, value in rows}

    def recent(self, limit=8):
        return list(self.db.scalars(
            select(TicketModel).options(
                joinedload(TicketModel.department),
                joinedload(TicketModel.creator),
                joinedload(TicketModel.assignee),
                joinedload(TicketModel.category).joinedload(CategoryModel.parent).joinedload(CategoryModel.parent),
            ).order_by(TicketModel.created_at.desc()).limit(limit)
        ).all())

    def sla_summary(self):
        now = func.now()
        open_filter = TicketModel.status.notin_(("resolved", "closed", "rejected"))
        active_deadline = case((TicketModel.status == "pending", TicketModel.accept_due_at), else_=TicketModel.resolve_due_at)
        soon = int(self.db.scalar(select(func.count(TicketModel.id)).where(
            open_filter, TicketModel.sla_paused_at.is_(None), active_deadline >= now,
            active_deadline <= now + timedelta(hours=get_settings().worker_due_soon_hours),
        )) or 0)
        overdue = int(self.db.scalar(select(func.count(TicketModel.id)).where(
            open_filter, TicketModel.sla_paused_at.is_(None), active_deadline < now,
        )) or 0)
        avg_accept = self.db.scalar(select(func.avg(func.extract("epoch", TicketModel.accepted_at - TicketModel.created_at) / 60)).where(
            TicketModel.accepted_at.is_not(None)
        ))
        avg_resolve = self.db.scalar(select(func.avg(func.extract("epoch", TicketModel.resolved_at - TicketModel.accepted_at) / 60)).where(
            TicketModel.resolved_at.is_not(None), TicketModel.accepted_at.is_not(None)
        ))
        return (
            soon, overdue,
            round(float(avg_accept), 1) if avg_accept is not None else None,
            round(float(avg_resolve), 1) if avg_resolve is not None else None,
        )

    def department_sla(self):
        completion = func.coalesce(TicketModel.resolved_at, TicketModel.closed_at, func.now())
        overdue_expr = case((completion > TicketModel.resolve_due_at, 1), else_=0)
        rows = self.db.execute(
            select(DepartmentModel.name, func.count(TicketModel.id), func.sum(overdue_expr))
            .join(TicketModel, TicketModel.assigned_department_id == DepartmentModel.id)
            .where(TicketModel.resolve_due_at.is_not(None), TicketModel.status != "rejected")
            .group_by(DepartmentModel.id, DepartmentModel.name)
            .order_by(DepartmentModel.name)
        ).all()
        return [(name, int(total), int(overdue or 0)) for name, total, overdue in rows]
