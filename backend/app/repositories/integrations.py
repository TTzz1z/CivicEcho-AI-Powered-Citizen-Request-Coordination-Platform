from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..logging_config import request_id_context
from ..models import IntegrationEventModel, TicketModel


class IntegrationRepository:
    def __init__(self, db: Session):
        self.db = db

    def start(self, integration_type: str, operation: str, direction: str, principal=None,
              resource_type: str | None = None, resource_id: str | None = None,
              payload_hash: str | None = None) -> IntegrationEventModel:
        event = IntegrationEventModel(
            id=str(uuid4()), integration_type=integration_type, operation=operation,
            direction=direction, resource_type=resource_type, resource_id=resource_id,
            status="pending", payload_hash=payload_hash,
            requested_by_user_id=getattr(principal, "user_id", None), request_id=request_id_context.get(),
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def finish(self, event: IntegrationEventModel, status: str, external_id: str | None = None,
               response_code: int | None = None, error_summary: str | None = None):
        event.status = status
        event.external_id = external_id
        event.response_code = response_code
        event.error_summary = error_summary[:500] if error_summary else None
        event.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(event)
        return event

    def ticket(self, ticket_id: str):
        return self.db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id.upper()))

    def save_ticket(self, ticket: TicketModel):
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def metrics(self):
        rows = self.db.execute(select(
            IntegrationEventModel.integration_type,
            IntegrationEventModel.status,
            func.count(IntegrationEventModel.id),
        ).group_by(IntegrationEventModel.integration_type, IntegrationEventModel.status)).all()
        return [{"integration_type": kind, "status": status, "count": int(count)} for kind, status, count in rows]
