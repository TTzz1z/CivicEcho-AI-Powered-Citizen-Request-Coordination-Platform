from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import TicketModel, WorkOrderHistoryModel, WorkOrderModel


class WorkOrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def ticket(self, ticket_id: str, *, for_update: bool = False):
        statement = select(TicketModel).where(TicketModel.ticket_id == ticket_id.upper())
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def get(self, work_order_id: str, *, for_update: bool = False):
        statement = (
            select(WorkOrderModel)
            .options(
                selectinload(WorkOrderModel.department),
                selectinload(WorkOrderModel.assignee),
                selectinload(WorkOrderModel.history),
            )
            .where(WorkOrderModel.id == work_order_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def list_for_ticket(self, ticket_id: str) -> list[WorkOrderModel]:
        return list(self.db.scalars(
            select(WorkOrderModel)
            .options(
                selectinload(WorkOrderModel.department),
                selectinload(WorkOrderModel.assignee),
                selectinload(WorkOrderModel.history),
            )
            .where(WorkOrderModel.ticket_id == ticket_id.upper())
            .order_by(WorkOrderModel.created_at, WorkOrderModel.work_order_no)
        ).all())

    def add(self, work_order: WorkOrderModel, operator_user_id: int | None, action: str, content: str) -> None:
        self.db.add(work_order)
        self.db.add(WorkOrderHistoryModel(
            work_order=work_order,
            operator_user_id=operator_user_id,
            action=action,
            previous_status=None,
            current_status=work_order.status,
            content=content,
        ))

    def record(self, work_order: WorkOrderModel, operator_user_id: int | None, action: str,
               previous_status: str, content: str) -> None:
        self.db.add(WorkOrderHistoryModel(
            work_order_id=work_order.id,
            operator_user_id=operator_user_id,
            action=action,
            previous_status=previous_status,
            current_status=work_order.status,
            content=content,
        ))

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
