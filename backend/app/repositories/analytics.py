from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from ..models import DepartmentModel, TicketModel


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

    def recent(self, limit=8):
        return list(self.db.scalars(
            select(TicketModel).options(
                selectinload(TicketModel.department),
                selectinload(TicketModel.creator),
                selectinload(TicketModel.assignee),
            ).order_by(TicketModel.created_at.desc()).limit(limit)
        ).all())

    def sla_summary(self):
        now = func.now()
        open_filter = TicketModel.status.notin_(("resolved", "closed", "rejected"))
        active_deadline = case((TicketModel.status == "pending", TicketModel.accept_due_at), else_=TicketModel.resolve_due_at)
        soon = int(self.db.scalar(select(func.count(TicketModel.id)).where(
            open_filter, TicketModel.sla_paused_at.is_(None), active_deadline >= now,
            active_deadline <= now + timedelta(hours=4),
        )) or 0)
        overdue = int(self.db.scalar(select(func.count(TicketModel.id)).where(
            open_filter, TicketModel.sla_paused_at.is_(None), active_deadline < now,
        )) or 0)
        avg_accept = float(self.db.scalar(select(func.avg(func.extract("epoch", TicketModel.accepted_at - TicketModel.created_at) / 60)).where(
            TicketModel.accepted_at.is_not(None)
        )) or 0)
        avg_resolve = float(self.db.scalar(select(func.avg(func.extract("epoch", TicketModel.resolved_at - TicketModel.accepted_at) / 60)).where(
            TicketModel.resolved_at.is_not(None), TicketModel.accepted_at.is_not(None)
        )) or 0)
        return soon, overdue, round(avg_accept, 1), round(avg_resolve, 1)

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
