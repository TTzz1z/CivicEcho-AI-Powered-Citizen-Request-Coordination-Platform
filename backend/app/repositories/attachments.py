from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TicketAttachmentModel


class AttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, attachment: TicketAttachmentModel) -> TicketAttachmentModel:
        self.db.add(attachment)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(attachment)
        return attachment

    def get(self, attachment_id: str, include_deleted: bool = False) -> TicketAttachmentModel | None:
        statement = select(TicketAttachmentModel).where(TicketAttachmentModel.id == attachment_id)
        if not include_deleted:
            statement = statement.where(TicketAttachmentModel.is_deleted.is_(False))
        return self.db.scalar(statement)

    def list_for_ticket(self, ticket_id: str) -> list[TicketAttachmentModel]:
        return list(self.db.scalars(
            select(TicketAttachmentModel)
            .where(
                TicketAttachmentModel.ticket_id == ticket_id.upper(),
                TicketAttachmentModel.is_deleted.is_(False),
            )
            .order_by(TicketAttachmentModel.created_at, TicketAttachmentModel.id)
        ).all())

    def soft_delete(self, attachment: TicketAttachmentModel, user_id: int, reason: str) -> None:
        attachment.is_deleted = True
        attachment.deleted_at = datetime.now(timezone.utc)
        attachment.deleted_by_user_id = user_id
        attachment.delete_reason = reason
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
