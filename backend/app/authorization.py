import hashlib
from dataclasses import dataclass
from typing import Optional

from .errors import PermissionDenied
from .models import TicketModel, WorkOrderModel


USER_ROLES = {"citizen", "agent", "department_staff", "admin"}


@dataclass(frozen=True)
class Principal:
    kind: str
    user_id: Optional[int] = None
    username: str = ""
    role: str = ""
    department_id: Optional[int] = None


class AuthorizationPolicy:
    """Single source of truth for role and ticket access decisions."""

    @staticmethod
    def require_roles(principal: Principal, *roles: str) -> None:
        if principal.kind != "user" or principal.role not in roles:
            raise PermissionDenied()

    @staticmethod
    def can_view(principal: Principal, ticket: TicketModel, anonymous_key: str | None = None) -> bool:
        if principal.kind == "service":
            return ticket.anonymous_creator_key is None or ticket.anonymous_creator_key == anonymous_key
        if principal.role == "admin":
            return True
        if principal.role == "citizen":
            citizen_key = hashlib.sha256(f"web-user-{principal.user_id}".encode("utf-8")).hexdigest()
            return ticket.creator_user_id == principal.user_id or (
                ticket.creator_user_id is None and ticket.anonymous_creator_key == citizen_key
            )
        if principal.role == "department_staff":
            return bool(principal.department_id and (
                ticket.assigned_department_id == principal.department_id
                or any(item.department_id == principal.department_id for item in getattr(ticket, "work_orders", []))
            ))
        if principal.role == "agent":
            # Service-desk agents remain coordinators after initial dispatch so they can
            # add co-handling tasks and act on department returns.
            return ticket.status not in {"closed", "rejected"}
        return False

    @staticmethod
    def require_view(principal: Principal, ticket: TicketModel, anonymous_key: str | None = None) -> None:
        if not AuthorizationPolicy.can_view(principal, ticket, anonymous_key):
            raise PermissionDenied("无权查看该工单")

    @staticmethod
    def require_transition(principal: Principal, action: str, ticket: TicketModel) -> None:
        if principal.role == "admin":
            return
        if action in {"accept", "reject", "assign", "review_resolve", "return_to_department"} and principal.role == "agent":
            return
        # Department staff can process and note, but NOT resolve — resolution
        # now requires agent review (P0-A separation of duties).
        if action in {"process", "note"} and principal.role == "department_staff" and principal.department_id == ticket.assigned_department_id:
            return
        if action in {"pause_sla", "resume_sla"} and principal.role == "department_staff" and principal.department_id == ticket.assigned_department_id:
            return
        raise PermissionDenied("当前角色无权执行此工单操作")

    @staticmethod
    def apply_query_scope(statement, principal: Principal):
        """Apply the same data boundary used by can_view to a SQL query."""
        from sqlalchemy import or_

        if principal.kind != "user":
            raise PermissionDenied()
        if principal.role == "admin":
            return statement
        if principal.role == "citizen":
            citizen_key = hashlib.sha256(f"web-user-{principal.user_id}".encode("utf-8")).hexdigest()
            return statement.where(
                or_(
                    TicketModel.creator_user_id == principal.user_id,
                    (
                        TicketModel.creator_user_id.is_(None)
                        & (TicketModel.anonymous_creator_key == citizen_key)
                    ),
                )
            )
        if principal.role == "department_staff":
            return statement.where(
                (TicketModel.assigned_department_id == principal.department_id)
                | TicketModel.work_orders.any(WorkOrderModel.department_id == principal.department_id)
            )
        if principal.role == "agent":
            return statement.where(
                TicketModel.status.notin_(("closed", "rejected"))
            )
        raise PermissionDenied()
