from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..authorization import Principal
from ..models import AppealModel, FollowUpTaskModel, NotificationModel, PhoneFollowUpRecordModel, TicketModel, WorkOrderModel


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_missing(self, items: list[NotificationModel], *, commit: bool = True) -> None:
        if not items:
            return
        keys = [item.event_key for item in items]
        existing = set(self.db.scalars(select(NotificationModel.event_key).where(NotificationModel.event_key.in_(keys))).all())
        self.db.add_all([item for item in items if item.event_key not in existing])
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    def list_for_user(self, user_id: int, page: int, page_size: int, unread_only: bool):
        statement = select(NotificationModel).where(NotificationModel.recipient_user_id == user_id)
        if unread_only:
            statement = statement.where(NotificationModel.status == "unread")
        total = int(self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(self.db.scalars(statement.order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
                                     .offset((page - 1) * page_size).limit(page_size)).all())
        unread = int(self.db.scalar(select(func.count()).select_from(NotificationModel).where(
            NotificationModel.recipient_user_id == user_id, NotificationModel.status == "unread"
        )) or 0)
        return items, total, unread

    def mark_read(self, notification_id: str, user_id: int) -> NotificationModel | None:
        item = self.db.get(NotificationModel, notification_id)
        if not item or item.recipient_user_id != user_id:
            return None
        if item.status != "read":
            item.status = "read"
            item.read_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(item)
        return item

    def mark_all_read(self, user_id: int) -> int:
        items = list(self.db.scalars(select(NotificationModel).where(
            NotificationModel.recipient_user_id == user_id, NotificationModel.status == "unread"
        )).all())
        now = datetime.now(timezone.utc)
        for item in items:
            item.status = "read"
            item.read_at = now
        self.db.commit()
        return len(items)


class AftercareRepository:
    def __init__(self, db: Session):
        self.db = db

    def ticket(self, ticket_id: str, lock: bool = False) -> TicketModel | None:
        statement = select(TicketModel).where(TicketModel.ticket_id == ticket_id.upper())
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def follow_up(self, task_id: str, lock: bool = False) -> FollowUpTaskModel | None:
        statement = select(FollowUpTaskModel).options(
            selectinload(FollowUpTaskModel.records).selectinload(PhoneFollowUpRecordModel.caller),
            selectinload(FollowUpTaskModel.assignee),
        ).where(FollowUpTaskModel.id == task_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def appeal(self, appeal_id: str, lock: bool = False) -> AppealModel | None:
        statement = select(AppealModel).options(
            selectinload(AppealModel.citizen), selectinload(AppealModel.reviewer)
        ).where(AppealModel.id == appeal_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def active_appeal(self, ticket_id: str) -> AppealModel | None:
        return self.db.scalar(select(AppealModel).where(
            AppealModel.ticket_id == ticket_id,
            AppealModel.status.in_(("submitted", "approved", "reprocessing")),
        ).order_by(AppealModel.sequence.desc()))

    def list_follow_ups(self, principal: Principal, page: int, page_size: int, status: str | None):
        statement = select(FollowUpTaskModel).options(
            selectinload(FollowUpTaskModel.records).selectinload(PhoneFollowUpRecordModel.caller),
            selectinload(FollowUpTaskModel.assignee),
        )
        if principal.role not in {"agent", "admin"}:
            statement = statement.where(False)
        if status:
            statement = statement.where(FollowUpTaskModel.status == status)
        total = int(self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(self.db.scalars(statement.order_by(FollowUpTaskModel.due_at, FollowUpTaskModel.created_at)
                                     .offset((page - 1) * page_size).limit(page_size)).unique().all())
        return items, total

    def list_appeals(self, principal: Principal, page: int, page_size: int, status: str | None):
        statement = select(AppealModel).options(
            selectinload(AppealModel.citizen), selectinload(AppealModel.reviewer)
        )
        if principal.role == "citizen":
            statement = statement.where(AppealModel.citizen_user_id == principal.user_id)
        elif principal.role == "department_staff":
            statement = statement.join(TicketModel, TicketModel.ticket_id == AppealModel.ticket_id).where(
                or_(
                    TicketModel.assigned_department_id == principal.department_id,
                    AppealModel.ticket_id.in_(select(WorkOrderModel.ticket_id).where(WorkOrderModel.department_id == principal.department_id)),
                )
            )
        elif principal.role not in {"agent", "admin"}:
            statement = statement.where(False)
        if status:
            statement = statement.where(AppealModel.status == status)
        total = int(self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(self.db.scalars(statement.order_by(AppealModel.created_at.desc(), AppealModel.appeal_no.desc())
                                     .offset((page - 1) * page_size).limit(page_size)).unique().all())
        return items, total

    def due_soon_tickets(self, threshold: datetime) -> list[TicketModel]:
        now = datetime.now(timezone.utc)
        return list(self.db.scalars(select(TicketModel).where(
            TicketModel.status.in_(("pending", "accepted", "assigned", "processing")),
            TicketModel.sla_paused_at.is_(None),
            or_(
                TicketModel.accept_due_at.between(now, threshold),
                TicketModel.resolve_due_at.between(now, threshold),
            ),
        )).all())

    def overdue_tickets(self) -> list[TicketModel]:
        """Return tickets whose SLA deadline has already passed (P0-G escalation)."""
        now = datetime.now(timezone.utc)
        return list(self.db.scalars(select(TicketModel).where(
            TicketModel.status.in_(("pending", "accepted", "assigned", "processing")),
            TicketModel.sla_paused_at.is_(None),
            or_(
                (TicketModel.accept_due_at.is_not(None)) & (TicketModel.accept_due_at < now),
                (TicketModel.resolve_due_at.is_not(None)) & (TicketModel.resolve_due_at < now),
            ),
        )).all())

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
