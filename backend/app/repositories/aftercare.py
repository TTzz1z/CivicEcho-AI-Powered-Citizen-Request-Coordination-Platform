from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.dialects.postgresql import insert

from ..authorization import Principal
from ..models import AppealModel, FollowUpTaskModel, NotificationModel, PhoneFollowUpRecordModel, TicketModel, WorkOrderModel


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_missing(self, items: list[NotificationModel], *, commit: bool = True) -> None:
        if not items:
            return
        rows = [{column.name: getattr(item, column.name) for column in NotificationModel.__table__.columns
                 if column.name not in {"created_at", "read_at"}} for item in items]
        self.db.execute(insert(NotificationModel).values(rows).on_conflict_do_nothing(index_elements=["event_key"]))
        if commit:
            self.db.commit()

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

    def resolve_stream_cursor(self, user_id: int, raw_cursor: str | None) -> tuple[datetime, str] | None:
        if not raw_cursor or not raw_cursor.strip():
            return None
        value = raw_cursor.strip()
        if "|" in value:
            ts_part, notif_id = value.split("|", 1)
            try:
                parsed = datetime.fromisoformat(ts_part)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed, notif_id
            except ValueError:
                return None
        row = self.db.execute(
            select(NotificationModel.created_at, NotificationModel.id).where(
                NotificationModel.id == value,
                NotificationModel.recipient_user_id == user_id,
            )
        ).first()
        if row:
            return row[0], row[1]
        return None

    def latest_stream_cursor(self, user_id: int) -> tuple[datetime, str] | None:
        row = self.db.execute(
            select(NotificationModel.created_at, NotificationModel.id)
            .where(NotificationModel.recipient_user_id == user_id)
            .order_by(NotificationModel.created_at.desc(), NotificationModel.id.desc())
            .limit(1)
        ).first()
        return (row[0], row[1]) if row else None

    def unread_count_for_user(self, user_id: int) -> int:
        return int(self.db.scalar(
            select(func.count()).select_from(NotificationModel).where(
                NotificationModel.recipient_user_id == user_id,
                NotificationModel.status == "unread",
            )
        ) or 0)

    def stream_updates(
        self,
        user_id: int,
        cursor: tuple[datetime, str] | None,
        *,
        limit: int = 50,
    ) -> tuple[int, list[NotificationModel], tuple[datetime, str] | None]:
        unread_count = self.unread_count_for_user(user_id)
        if cursor is None:
            items = list(self.db.scalars(
                select(NotificationModel)
                .where(
                    NotificationModel.recipient_user_id == user_id,
                    NotificationModel.status == "unread",
                )
                .order_by(NotificationModel.created_at.asc(), NotificationModel.id.asc())
                .limit(limit)
            ).all())
            next_cursor = (items[-1].created_at, items[-1].id) if items else self.latest_stream_cursor(user_id)
            if next_cursor is None:
                next_cursor = (datetime.now(timezone.utc), "")
            return unread_count, items, next_cursor

        cursor_ts, cursor_id = cursor
        items = list(self.db.scalars(
            select(NotificationModel)
            .where(
                NotificationModel.recipient_user_id == user_id,
                or_(
                    NotificationModel.created_at > cursor_ts,
                    and_(
                        NotificationModel.created_at == cursor_ts,
                        NotificationModel.id > cursor_id,
                    ),
                ),
            )
            .order_by(NotificationModel.created_at.asc(), NotificationModel.id.asc())
            .limit(limit)
        ).all())
        next_cursor = (items[-1].created_at, items[-1].id) if items else cursor
        return unread_count, items, next_cursor


class AftercareRepository:
    def __init__(self, db: Session):
        self.db = db

    def ticket(self, ticket_id: str, lock: bool = False) -> TicketModel | None:
        statement = select(TicketModel).where(TicketModel.ticket_id == ticket_id.upper())
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(statement)

    def lock_ticket_for(self, related_model: type[FollowUpTaskModel] | type[AppealModel], related_id: str) -> TicketModel | None:
        return self.db.scalar(
            select(TicketModel)
            .join(related_model, related_model.ticket_id == TicketModel.ticket_id)
            .where(related_model.id == related_id)
            .with_for_update(of=TicketModel)
            .execution_options(populate_existing=True)
        )

    def follow_up(self, task_id: str, lock: bool = False) -> FollowUpTaskModel | None:
        statement = select(FollowUpTaskModel).options(
            selectinload(FollowUpTaskModel.records).selectinload(PhoneFollowUpRecordModel.caller),
            selectinload(FollowUpTaskModel.assignee),
        ).where(FollowUpTaskModel.id == task_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(statement)

    def appeal(self, appeal_id: str, lock: bool = False) -> AppealModel | None:
        statement = select(AppealModel).options(
            selectinload(AppealModel.citizen), selectinload(AppealModel.reviewer)
        ).where(AppealModel.id == appeal_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
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

    def _sla_tickets(self, matches) -> list[TicketModel]:
        return list(self.db.scalars(select(TicketModel).where(
            TicketModel.sla_paused_at.is_(None),
            or_(
                (TicketModel.status == "pending") & matches(TicketModel.accept_due_at),
                TicketModel.status.in_(("accepted", "assigned", "processing")) & matches(TicketModel.resolve_due_at),
            ),
        )).all())

    def due_soon_tickets(self, threshold: datetime, *, now: datetime | None = None) -> list[TicketModel]:
        now = now or datetime.now(timezone.utc)
        return self._sla_tickets(lambda deadline: deadline.between(now, threshold))

    def overdue_tickets(self, *, now: datetime | None = None) -> list[TicketModel]:
        """Return tickets whose SLA deadline has already passed (P0-G escalation)."""
        now = now or datetime.now(timezone.utc)
        return self._sla_tickets(lambda deadline: deadline < now)

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
