from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..authorization import AuthorizationPolicy, Principal
from ..models import AiSuggestionModel, DepartmentModel, TicketModel


class AiRepository:
    def __init__(self, db: Session):
        self.db = db

    def ticket(self, ticket_id: str) -> TicketModel | None:
        return self.db.scalar(
            select(TicketModel)
            .where(TicketModel.ticket_id == ticket_id.upper())
            .options(selectinload(TicketModel.category), selectinload(TicketModel.department), selectinload(TicketModel.work_orders))
        )

    def candidates(self, ticket_id: str, limit: int = 300) -> list[TicketModel]:
        return list(self.db.scalars(
            select(TicketModel).where(TicketModel.ticket_id != ticket_id).order_by(TicketModel.created_at.desc()).limit(limit)
        ).all())

    def active_departments(self) -> list[DepartmentModel]:
        return list(self.db.scalars(select(DepartmentModel).where(DepartmentModel.is_active.is_(True))).all())

    def assignment_history(self, category_id: int | None, location: str, limit: int = 500):
        statement = select(TicketModel).where(
            TicketModel.assigned_department_id.is_not(None),
            TicketModel.status.in_(("resolved", "closed")),
        )
        if category_id:
            statement = statement.where(TicketModel.category_id == category_id)
        return list(self.db.scalars(statement.order_by(TicketModel.created_at.desc()).limit(limit)).all())

    def existing(self, ticket_id: str, suggestion_type: str, fingerprint: str):
        return self.db.scalar(select(AiSuggestionModel).where(
            AiSuggestionModel.ticket_id == ticket_id,
            AiSuggestionModel.suggestion_type == suggestion_type,
            AiSuggestionModel.input_fingerprint == fingerprint,
        ))

    def add(self, suggestion: AiSuggestionModel, *, commit: bool = True) -> AiSuggestionModel:
        self.db.add(suggestion)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(suggestion)
        return suggestion

    def list_for_ticket(self, ticket_id: str) -> list[AiSuggestionModel]:
        return list(self.db.scalars(
            select(AiSuggestionModel).where(AiSuggestionModel.ticket_id == ticket_id)
            .order_by(AiSuggestionModel.created_at.desc(), AiSuggestionModel.suggestion_type)
        ).all())

    def get(self, suggestion_id: str) -> AiSuggestionModel | None:
        return self.db.get(AiSuggestionModel, suggestion_id)

    def save(self, suggestion: AiSuggestionModel, *, commit: bool = True) -> AiSuggestionModel:
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(suggestion)
        return suggestion

    def hotspot_rows(self, principal: Principal, days: int):
        since = datetime.now(timezone.utc) - timedelta(days=days)
        scoped = AuthorizationPolicy.apply_query_scope(select(TicketModel), principal).where(TicketModel.created_at >= since)
        return list(self.db.scalars(scoped.order_by(TicketModel.created_at.desc()).limit(2000)).all())
