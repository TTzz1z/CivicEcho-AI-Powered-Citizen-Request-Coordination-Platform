from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..authorization import AuthorizationPolicy, Principal
from ..config import get_settings
from ..models import CategoryModel, TicketFeedbackModel, TicketModel, TicketStatusHistoryModel, WorkOrderHistoryModel, WorkOrderModel
from ..schemas import TicketFilterQuery, TicketQuery
from .base import CreateResult, PageResult, TicketRepository


class PostgreSQLTicketRepository(TicketRepository):
    model = TicketModel
    def __init__(self, db: Session):
        self.db = db

    def next_sequence(self) -> int:
        return int(self.db.execute(text("SELECT nextval('ticket_number_seq')")).scalar_one())

    def create(self, ticket_id, data, creator_user_id=None, anonymous_key=None, *, commit: bool = True) -> CreateResult:
        existing = self.db.scalar(select(TicketModel).where(TicketModel.idempotency_key == data.idempotency_key))
        if existing:
            return CreateResult(existing, True)
        values = data.model_dump(exclude={"creator_reference"})
        values["occurred_at"] = values.get("occurred_at_text")
        now = datetime.now(timezone.utc)
        ticket = TicketModel(
            ticket_id=ticket_id, status="pending", version=1,
            creator_user_id=creator_user_id, anonymous_creator_key=anonymous_key,
            accept_due_at=now + timedelta(minutes=120), resolve_due_at=now + timedelta(minutes=4320),
            **values,
        )
        ticket.history.append(TicketStatusHistoryModel(
            operator_user_id=creator_user_id, operation_type="create", content="创建工单",
            previous_status=None, current_status="pending", remark="创建工单", visibility="public",
        ))
        self.db.add(ticket)
        try:
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            self.db.refresh(ticket)
            return CreateResult(ticket, False)
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(TicketModel).where(TicketModel.idempotency_key == data.idempotency_key))
            if existing:
                return CreateResult(existing, True)
            raise

    def get(self, ticket_id: str):
        return self.db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id.upper()))

    def _filtered(self, query: TicketFilterQuery, principal: Principal):
        statement = AuthorizationPolicy.apply_query_scope(select(TicketModel), principal)
        if query.status:
            statement = statement.where(TicketModel.status == query.status)
        if query.request_type:
            statement = statement.where(TicketModel.request_type == query.request_type)
        if query.department_id:
            statement = statement.where(TicketModel.assigned_department_id == query.department_id)
        if query.category_id:
            statement = statement.where(TicketModel.category_id == query.category_id)
        if query.priority:
            statement = statement.where(TicketModel.priority == query.priority)
        if query.created_from:
            statement = statement.where(TicketModel.created_at >= query.created_from)
        if query.created_to:
            statement = statement.where(TicketModel.created_at < query.created_to)
        if query.keyword:
            raw = query.keyword.strip()
            pattern = f"%{raw}%"
            # Ticket numbers (QT…) must match ticket_id; free text still hits description/location/event.
            statement = statement.where(or_(
                TicketModel.ticket_id.ilike(pattern),
                TicketModel.description.ilike(pattern),
                TicketModel.location.ilike(pattern),
                TicketModel.event.ilike(pattern),
            ))
        if query.mine and principal.role != "citizen":
            mine_column = TicketModel.assigned_user_id if principal.role == "department_staff" else TicketModel.creator_user_id
            statement = statement.where(mine_column == principal.user_id)
        if query.my_department:
            statement = statement.where(TicketModel.assigned_department_id == principal.department_id)
        if query.work_queue == "awaiting_review":
            statement = statement.where(TicketModel.collaboration_status == "awaiting_review")
        elif query.work_queue == "returned":
            returned = WorkOrderModel.status == "returned"
            reviewer_return = and_(
                WorkOrderModel.status == "processing", WorkOrderModel.task_type == "primary",
                WorkOrderModel.history.any(and_(
                    WorkOrderHistoryModel.action == "return_to_department",
                    WorkOrderHistoryModel.created_at >= func.coalesce(WorkOrderModel.accepted_at, WorkOrderModel.created_at),
                )),
            )
            if principal.role == "department_staff":
                reviewer_return = and_(reviewer_return, WorkOrderModel.department_id == principal.department_id)
            statement = statement.where(or_(
                and_(TicketModel.collaboration_status == "awaiting_dispatch", TicketModel.work_orders.any(returned)),
                and_(TicketModel.collaboration_status == "in_progress", TicketModel.work_orders.any(reviewer_return)),
            ))
        if query.sla_state:
            now = func.now()
            deadline = case((TicketModel.status == "pending", TicketModel.accept_due_at), else_=TicketModel.resolve_due_at)
            is_open = TicketModel.status.in_(("pending", "accepted", "assigned", "processing"))
            threshold = now + timedelta(hours=get_settings().worker_due_soon_hours)
            if query.sla_state == "paused":
                statement = statement.where(is_open, TicketModel.sla_paused_at.is_not(None))
            elif query.sla_state == "overdue":
                statement = statement.where(is_open, TicketModel.sla_paused_at.is_(None), deadline < now)
            elif query.sla_state == "due_soon":
                statement = statement.where(is_open, TicketModel.sla_paused_at.is_(None), deadline.between(now, threshold))
            else:
                statement = statement.where(or_(
                    ~is_open,
                    and_(TicketModel.sla_paused_at.is_(None), or_(deadline.is_(None), deadline > threshold)),
                ))
        return statement

    def list(self, query: TicketQuery, principal: Principal) -> PageResult:
        filtered = self._filtered(query, principal)
        total = int(self.db.scalar(select(func.count()).select_from(filtered.order_by(None).subquery())) or 0)
        order_column = {
            "created_at": TicketModel.created_at,
            "updated_at": TicketModel.updated_at,
            "priority": case({"normal": 1, "expedited": 2, "urgent": 3, "major": 4}, value=TicketModel.priority),
        }[query.sort]
        order = order_column.asc() if query.order == "asc" else order_column.desc()
        statement = (
            filtered.options(
                joinedload(TicketModel.creator), joinedload(TicketModel.assignee),
                joinedload(TicketModel.department),
                joinedload(TicketModel.category).joinedload(CategoryModel.parent).joinedload(CategoryModel.parent),
            )
            .order_by(order, TicketModel.id.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        return PageResult(list(self.db.scalars(statement).all()), total)

    def list_for_export(self, query: TicketFilterQuery, principal: Principal, *, limit: int = 5000) -> list[TicketModel]:
        filtered = self._filtered(query, principal)
        order_column = {
            "created_at": TicketModel.created_at,
            "updated_at": TicketModel.updated_at,
            "priority": case({"normal": 1, "expedited": 2, "urgent": 3, "major": 4}, value=TicketModel.priority),
        }[query.sort]
        order = order_column.asc() if query.order == "asc" else order_column.desc()
        statement = (
            filtered.options(
                joinedload(TicketModel.creator), joinedload(TicketModel.assignee),
                joinedload(TicketModel.department),
                joinedload(TicketModel.category).joinedload(CategoryModel.parent).joinedload(CategoryModel.parent),
            )
            .order_by(order, TicketModel.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(statement).all())

    def transition(self, ticket_id, expected_version, status, operation_type, content, operator_user_id, updates,
                   visibility="internal", *, commit: bool = True):
        ticket = self.get(ticket_id)
        if not ticket:
            return None
        previous = ticket.status
        values = dict(updates, status=status, version=expected_version + 1, updated_at=func.now())
        changed = self.db.execute(
            update(TicketModel)
            .where(TicketModel.ticket_id == ticket_id.upper(), TicketModel.version == expected_version)
            .values(**values)
            .returning(TicketModel.id)
        ).first()
        if not changed:
            self.db.rollback()
            return None
        self.db.add(TicketStatusHistoryModel(
            ticket_id=ticket_id.upper(), operator_user_id=operator_user_id,
            operation_type=operation_type, content=content, previous_status=previous,
            current_status=status, remark=content, visibility=visibility,
        ))
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return self.get(ticket_id)

    def feedback_transition(self, ticket_id, expected_version, status, content, operator_user_id,
                            updates, rating, comment, result, *, commit: bool = True):
        ticket = self.get(ticket_id)
        if not ticket:
            return None
        previous = ticket.status
        values = dict(updates, status=status, version=expected_version + 1, updated_at=func.now())
        changed = self.db.execute(
            update(TicketModel)
            .where(TicketModel.ticket_id == ticket_id.upper(), TicketModel.version == expected_version)
            .values(**values)
            .returning(TicketModel.id)
        ).first()
        if not changed:
            self.db.rollback()
            return None
        self.db.add(TicketStatusHistoryModel(
            ticket_id=ticket_id.upper(), operator_user_id=operator_user_id,
            operation_type="citizen_feedback", content=content, previous_status=previous,
            current_status=status, remark=content, visibility="public",
        ))
        self.db.add(TicketFeedbackModel(
            ticket_id=ticket_id.upper(), citizen_user_id=operator_user_id,
            resolution_version=expected_version, rating=rating, comment=comment, result=result,
        ))
        try:
            if commit:
                self.db.commit()
            else:
                self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return None
        return self.get(ticket_id)

    def history(self, ticket_id: str):
        statement = select(TicketStatusHistoryModel).where(TicketStatusHistoryModel.ticket_id == ticket_id.upper()).order_by(TicketStatusHistoryModel.created_at, TicketStatusHistoryModel.id)
        return list(self.db.scalars(statement).all())

    def feedbacks(self, ticket_id: str):
        statement = select(TicketFeedbackModel).where(TicketFeedbackModel.ticket_id == ticket_id.upper()).order_by(TicketFeedbackModel.created_at, TicketFeedbackModel.id)
        return list(self.db.scalars(statement).all())
