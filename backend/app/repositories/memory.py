from datetime import datetime, timedelta, timezone
from threading import RLock

from ..authorization import AuthorizationPolicy, Principal
from ..models import TicketFeedbackModel, TicketModel, TicketStatusHistoryModel
from ..schemas import TicketQuery
from .base import CreateResult, PageResult, TicketRepository


class InMemoryTicketRepository(TicketRepository):
    """Thread-safe test/local substitute; never used as production persistence."""

    def __init__(self):
        self._tickets: dict[str, TicketModel] = {}
        self._idempotency: dict[str, str] = {}
        self._sequence = 0
        self._lock = RLock()

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def create(self, ticket_id, data, creator_user_id=None, anonymous_key=None) -> CreateResult:
        with self._lock:
            existing_id = self._idempotency.get(data.idempotency_key)
            if existing_id:
                return CreateResult(self._tickets[existing_id], True)
            now = datetime.now(timezone.utc)
            values = data.model_dump(exclude={"creator_reference"})
            values["occurred_at"] = values.get("occurred_at_text")
            ticket = TicketModel(
                id=self._sequence, ticket_id=ticket_id, status="pending", version=1,
                creator_user_id=creator_user_id, anonymous_creator_key=anonymous_key,
                accepted_at=None, resolved_at=None, closed_at=None,
                resolution_summary=None, resolution_measures=None, resolution_outcome=None,
                public_reply=None, internal_note=None, rejection_reason_code=None,
                rejection_detail=None, suggested_channel=None, needs_supplement=False,
                collaboration_status="none", supplement_reason=None,
                supplement_requested_at=None, supplemented_at=None,
                dispatch_return_reason=None, dispute_reason=None, dispute_resolution=None,
                closure_type=None,
                category_id=None, priority_confirmed_at=None, priority_confirmed_by=None,
                accept_due_at=now + timedelta(minutes=120), resolve_due_at=now + timedelta(minutes=4320),
                sla_paused_at=None, sla_pause_reason=None, total_paused_seconds=0, reminder_count=0,
                assigned_department_id=None, assigned_user_id=None,
                created_at=now, updated_at=now, **values,
            )
            ticket.history = [TicketStatusHistoryModel(
                id=1, ticket_id=ticket_id, operator_user_id=creator_user_id,
                operation_type="create", content="创建工单", previous_status=None,
                current_status="pending", remark="创建工单", visibility="public", created_at=now,
            )]
            ticket.feedbacks = []
            self._tickets[ticket_id] = ticket
            self._idempotency[data.idempotency_key] = ticket_id
            return CreateResult(ticket, False)

    def get(self, ticket_id: str):
        return self._tickets.get(ticket_id.upper())

    def list(self, query: TicketQuery, principal: Principal) -> PageResult:
        items = [item for item in self._tickets.values() if AuthorizationPolicy.can_view(principal, item)]
        if query.status:
            items = [x for x in items if x.status == query.status]
        if query.request_type:
            items = [x for x in items if x.request_type == query.request_type]
        if query.department_id:
            items = [x for x in items if x.assigned_department_id == query.department_id]
        if query.category_id:
            items = [x for x in items if x.category_id == query.category_id]
        if query.priority:
            items = [x for x in items if x.priority == query.priority]
        if query.keyword:
            word = query.keyword.lower()
            items = [x for x in items if word in f"{x.description} {x.location} {x.event or ''}".lower()]
        if query.mine:
            items = [x for x in items if x.creator_user_id == principal.user_id]
        if query.my_department:
            items = [x for x in items if x.assigned_department_id == principal.department_id]
        reverse = query.order == "desc"
        items.sort(key=lambda x: getattr(x, query.sort), reverse=reverse)
        total = len(items)
        start = (query.page - 1) * query.page_size
        return PageResult(items[start:start + query.page_size], total)

    def transition(self, ticket_id, expected_version, status, operation_type, content, operator_user_id, updates,
                   visibility="internal", *, commit: bool = True):
        del commit  # in-memory repo has no transactional boundary
        with self._lock:
            ticket = self.get(ticket_id)
            if not ticket or ticket.version != expected_version:
                return None
            previous = ticket.status
            ticket.status = status
            ticket.version += 1
            ticket.updated_at = datetime.now(timezone.utc)
            for key, value in updates.items():
                setattr(ticket, key, value)
            ticket.history.append(TicketStatusHistoryModel(
                id=len(ticket.history) + 1, ticket_id=ticket.ticket_id,
                operator_user_id=operator_user_id, operation_type=operation_type,
                content=content, previous_status=previous, current_status=status,
                remark=content, visibility=visibility, created_at=ticket.updated_at,
            ))
            return ticket

    def feedback_transition(self, ticket_id, expected_version, status, content, operator_user_id,
                            updates, rating, comment, result):
        with self._lock:
            ticket = self.get(ticket_id)
            if not ticket or ticket.version != expected_version:
                return None
            if any(item.resolution_version == expected_version for item in ticket.feedbacks):
                return None
            previous = ticket.status
            ticket.status = status
            ticket.version += 1
            ticket.updated_at = datetime.now(timezone.utc)
            for key, value in updates.items():
                setattr(ticket, key, value)
            ticket.history.append(TicketStatusHistoryModel(
                id=len(ticket.history) + 1, ticket_id=ticket.ticket_id,
                operator_user_id=operator_user_id, operation_type="citizen_feedback",
                content=content, previous_status=previous, current_status=status,
                remark=content, visibility="public", created_at=ticket.updated_at,
            ))
            ticket.feedbacks.append(TicketFeedbackModel(
                id=len(ticket.feedbacks) + 1, ticket_id=ticket.ticket_id,
                citizen_user_id=operator_user_id, resolution_version=expected_version,
                rating=rating, comment=comment, result=result, created_at=ticket.updated_at,
            ))
            return ticket

    def history(self, ticket_id: str):
        ticket = self.get(ticket_id)
        return list(ticket.history) if ticket else []

    def feedbacks(self, ticket_id: str):
        ticket = self.get(ticket_id)
        return list(ticket.feedbacks) if ticket else []
