from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied, TicketNotFound, VersionConflict
from ..repositories.base import CreateResult, TicketRepository
from ..repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from ..models import WorkOrderModel
from ..schemas import STATUS_LABELS, TicketCreate, TicketDetail, TicketList, TicketQuery, TicketRead, TicketStatusHistoryRead, WorkOrderRead
from ..security import anonymous_creator_key
from ..time_normalization import normalize_chinese_time


TRANSITIONS = {
    "pending": {"accept": "accepted", "reject": "rejected"},
    "accepted": {"assign": "assigned"},
    "assigned": {"process": "processing"},
    "processing": {"note": "processing", "resolve": "resolved"},
    "resolved": {"close": "closed", "process": "processing"},
}


class TicketService:
    def __init__(
        self,
        repository: TicketRepository,
        departments: DepartmentRepository | None = None,
        audit: AuditRepository | None = None,
        users: UserRepository | None = None,
        categories=None,
        work_orders=None,
        aftercare=None,
    ):
        self.repository = repository
        self.departments = departments
        self.audit = audit
        self.users = users
        self.categories = categories
        self.work_orders = work_orders
        self.aftercare = aftercare

    @staticmethod
    def _default_principal() -> Principal:
        return Principal(kind="service", username="legacy-test", role="service")

    def _audit(self, principal, action, outcome="success", ticket_id=None, details=None, *, commit: bool = True):
        if self.audit:
            self.audit.log(principal, action, outcome, "ticket" if ticket_id else None, ticket_id, details,
                           commit=commit)

    def _db(self):
        """Shared SQLAlchemy session when using Postgres-backed repositories."""
        return getattr(self.repository, "db", None) or getattr(self.work_orders, "db", None)

    def create(self, data: TicketCreate, principal: Principal | None = None) -> CreateResult:
        principal = principal or self._default_principal()
        if principal.kind == "user" and principal.role not in {"citizen", "agent", "admin"}:
            raise PermissionDenied("当前角色不能创建工单")
        if not data.occurred_at_start:
            normalized = normalize_chinese_time(data.occurred_at_text, data.timezone)
            if normalized:
                data = data.model_copy(update={
                    "occurred_at_start": normalized.start,
                    "occurred_at_end": normalized.end,
                    "occurred_at_precision": normalized.precision,
                    "timezone": normalized.timezone,
                })
        requested_priority = data.requested_priority or data.priority
        data = data.model_copy(update={
            "priority": "normal",
            "requested_priority": requested_priority,
        })
        sequence = self.repository.next_sequence()
        ticket_id = f"QT{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')}{sequence:08d}"
        creator_id = principal.user_id if principal.kind == "user" else None
        anon_key = anonymous_creator_key(data.creator_reference) if principal.kind == "service" else None
        result = self.repository.create(ticket_id, data, creator_id, anon_key)
        if not result.replayed:
            self._audit(principal, "create_ticket", ticket_id=result.ticket.ticket_id)
            if self.aftercare:
                self.aftercare.on_ticket_event("ticket_created", result.ticket, principal)
        return result

    def get(self, ticket_id: str):
        ticket = self.repository.get(ticket_id)
        if not ticket:
            raise TicketNotFound(ticket_id)
        return ticket

    def _present(self, ticket, principal: Principal, detail=False):
        # SQLAlchemy column defaults are applied on flush. The legacy in-memory
        # repository returns unflushed model instances, so normalize phase-5
        # fields here as well as through migration server defaults.
        if getattr(ticket, "handling_round", None) is None:
            ticket.handling_round = 1
        if getattr(ticket, "appeal_count", None) is None:
            ticket.appeal_count = 0
        model_type = TicketDetail if detail else TicketRead
        data = model_type.model_validate(ticket)
        department_name = ticket.department.name if getattr(ticket, "department", None) else None
        updates = {
            "status_label": STATUS_LABELS[ticket.status],
            "department_name": department_name,
            "creator_name": ticket.creator.display_name if getattr(ticket, "creator", None) else None,
            "assignee_name": ticket.assignee.display_name if getattr(ticket, "assignee", None) else None,
        }
        category = getattr(ticket, "category", None)
        if category:
            names = []
            current = category
            while current:
                names.append(current.name)
                current = current.parent
            updates.update(category_code=category.code, category_name=category.name,
                           category_path=" / ".join(reversed(names)))
        deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
        stop_at = ticket.sla_paused_at or datetime.now(timezone.utc)
        completed_at = ticket.accepted_at if ticket.status == "pending" else (ticket.resolved_at or ticket.closed_at)
        comparison = completed_at or stop_at
        remaining = int((deadline - comparison).total_seconds()) if deadline else None
        is_open = ticket.status not in {"resolved", "closed", "rejected"}
        is_overdue = bool(deadline and comparison > deadline and (is_open or completed_at))
        if ticket.sla_paused_at:
            sla_state = "paused"
        elif is_open and is_overdue:
            sla_state = "overdue"
        elif is_open and remaining is not None and remaining <= 14400:
            sla_state = "due_soon"
        else:
            sla_state = "on_track"
        updates.update(remaining_seconds=remaining, is_overdue=is_overdue, sla_state=sla_state)
        if principal.kind == "service":
            updates["contact"] = None
            updates["internal_note"] = None
        elif principal.role == "citizen":
            updates["internal_note"] = None
        if detail:
            histories = self.repository.history(ticket.ticket_id)
            if principal.kind == "user" and principal.role in {"agent", "department_staff", "admin"}:
                updates["history"] = histories
            else:
                public_labels = {
                    "create": "创建工单", "accept": "工单已受理", "assign": "工单已派发",
                    "process": "承办部门开始处理", "note": "承办部门更新办理进度",
                    "resolve": "承办部门已提交处理结果", "close": "工单已办结",
                    "reject": "工单不予受理", "update_contact": "联系方式已更新",
                }
                updates["history"] = [
                    TicketStatusHistoryRead.model_validate(item).model_copy(update={
                        "content": public_labels.get(item.operation_type, "工单状态已更新"),
                        "remark": None,
                    }) if getattr(item, "visibility", "public") == "internal" else item
                    for item in histories
                ]
            updates["feedbacks"] = self.repository.feedbacks(ticket.ticket_id)
            if self.work_orders:
                presented_orders = []
                for item in self.work_orders.list_for_ticket(ticket.ticket_id):
                    order = WorkOrderRead.model_validate(item).model_copy(update={
                        "department_name": item.department.name if item.department else None,
                        "assignee_name": item.assignee.display_name if item.assignee else None,
                        "history": sorted(item.history, key=lambda value: value.created_at),
                    })
                    if principal.kind == "service" or principal.role == "citizen":
                        order = order.model_copy(update={"internal_note": None, "history": []})
                    presented_orders.append(order)
                updates["work_orders"] = presented_orders
        return data.model_copy(update=updates)

    def detail(self, ticket_id: str, principal: Principal | None = None, creator_reference: str | None = None):
        principal = principal or self._default_principal()
        ticket = self.get(ticket_id)
        try:
            AuthorizationPolicy.require_view(principal, ticket, anonymous_creator_key(creator_reference))
        except PermissionDenied:
            self._audit(principal, "permission_denied", "denied", ticket.ticket_id, {"operation": "view"})
            raise
        if ticket.contact and principal.kind == "user":
            self._audit(principal, "view_sensitive_ticket", ticket_id=ticket.ticket_id)
        return self._present(ticket, principal, detail=True)

    def list_tickets(self, query: TicketQuery, principal: Principal) -> TicketList:
        if principal.kind != "user":
            raise PermissionDenied()
        if query.my_department and principal.department_id is None:
            return TicketList(items=[], page=query.page, page_size=query.page_size, total=0)
        result = self.repository.list(query, principal)
        return TicketList(
            items=[self._present(item, principal) for item in result.items],
            page=query.page, page_size=query.page_size, total=result.total,
        )

    def _transition(self, ticket_id: str, action: str, version: int, remark: str, principal: Principal,
                    updates: dict | None = None, history_content: str | None = None,
                    visibility: str = "internal", *, commit: bool = True, run_aftercare: bool = True):
        ticket = self.get(ticket_id)
        # P0-R4: permission check MUST come before version check. Otherwise a
        # caller without the required role could enumerate the current version
        # of any ticket by observing the difference between VERSION_CONFLICT
        # and PERMISSION_DENIED responses.
        try:
            AuthorizationPolicy.require_transition(principal, action, ticket)
        except PermissionDenied:
            self._audit(principal, "permission_denied", "denied", ticket.ticket_id, {"operation": action})
            raise
        if ticket.version != version:
            raise VersionConflict()
        new_status = TRANSITIONS.get(ticket.status, {}).get(action)
        if not new_status:
            raise BusinessError(
                "INVALID_STATUS_TRANSITION",
                f"工单不能从 {ticket.status} 执行 {action}",
                409,
                {"current_status": ticket.status, "allowed_actions": sorted(TRANSITIONS.get(ticket.status, {}))},
            )
        now = datetime.now(timezone.utc)
        values = dict(updates or {})
        if action == "accept":
            values["accepted_at"] = now
        elif action == "resolve":
            values["resolved_at"] = now
        elif action == "close":
            values["closed_at"] = now
        elif action == "process" and ticket.status == "resolved":
            values["resolved_at"] = None
        previous_status = ticket.status
        updated = self.repository.transition(
            ticket.ticket_id, version, new_status, action, history_content or remark,
            principal.user_id, values, visibility, commit=commit,
        )
        if not updated:
            raise VersionConflict()
        audit_action = {"accept": "accept_ticket", "assign": "assign_ticket", "reject": "reject_ticket", "note": "add_ticket_note"}.get(action, "change_ticket_status")
        self._audit(
            principal, audit_action, ticket_id=ticket.ticket_id,
            details={"from": previous_status, "to": new_status},
            commit=commit,
        )
        if run_aftercare and self.aftercare:
            event = {"accept": "ticket_accepted", "assign": "ticket_assigned", "resolve": "resolved", "close": "closed"}.get(action)
            if event:
                self.aftercare.on_ticket_event(event, updated, principal)
        return self._present(updated, principal)

    def accept(self, ticket_id, version, remark, principal, category_id=None, priority="normal"):
        if priority not in {"normal", "expedited", "urgent", "major"}:
            raise BusinessError("INVALID_PRIORITY", "优先级值无效", 422)
        ticket = self.get(ticket_id)
        category = None
        if category_id is not None:
            category = self.categories.get(category_id) if self.categories else None
            if not category or not category.is_active:
                raise BusinessError("CATEGORY_UNAVAILABLE", "分类不存在或已停用", 409)
            if self.categories.has_active_children(category.id):
                raise BusinessError("CATEGORY_NOT_LEAF", "工单必须选择末级分类", 422)
        factor = {"normal": 1.0, "expedited": 0.75, "urgent": 0.5, "major": 0.25}[priority]
        now = datetime.now(timezone.utc)
        accept_minutes = category.accept_sla_minutes if category else 120
        resolve_minutes = category.resolve_sla_minutes if category else 4320
        updates = {
            "category_id": category_id,
            "priority": priority,
            "priority_confirmed_at": now,
            "priority_confirmed_by": principal.user_id,
            "accept_due_at": ticket.created_at + timedelta(minutes=max(1, round(accept_minutes * factor))),
            "resolve_due_at": now + timedelta(minutes=max(1, round(resolve_minutes * factor))),
        }
        result = self._transition(ticket_id, "accept", version, remark, principal, updates)
        self._audit(principal, "confirm_ticket_triage", ticket_id=ticket_id,
                    details={"category_id": category_id, "priority": priority})
        return result

    def reject(self, ticket_id, version, remark, reason_code, rejection_detail,
               suggested_channel, needs_supplement, principal):
        return self._transition(ticket_id, "reject", version, remark, principal, {
            "rejection_reason_code": reason_code,
            "rejection_detail": rejection_detail,
            "suggested_channel": suggested_channel,
            "needs_supplement": needs_supplement,
        }, history_content=f"不予受理：{rejection_detail}", visibility="public")

    def assign(self, ticket_id, version, remark, department_id, assigned_user_id, principal):
        if not self.departments:
            raise BusinessError("DEPARTMENT_UNAVAILABLE", "部门服务不可用", 503)
        department = self.departments.get(department_id)
        if not department:
            raise BusinessError("DEPARTMENT_NOT_FOUND", "未找到指定部门", 404)
        if not department.is_active:
            raise BusinessError("DEPARTMENT_INACTIVE", "停用部门不能接收新工单", 409)
        if assigned_user_id is not None:
            user = self.users.get(assigned_user_id) if self.users else None
            if not user or not user.is_active or user.role != "department_staff" or user.department_id != department_id:
                raise BusinessError("INVALID_ASSIGNEE", "承办人必须是该部门的启用部门人员", 409)
        db = self._db()
        try:
            result = self._transition(
                ticket_id, "assign", version, remark, principal, {
                    "assigned_department_id": department_id,
                    "assigned_user_id": assigned_user_id,
                    "collaboration_status": "in_progress",
                },
                commit=False, run_aftercare=False,
            )
            if self.work_orders and not any(
                item.task_type == "primary" and item.status in {"pending", "processing", "submitted"}
                for item in self.work_orders.list_for_ticket(ticket_id)
            ):
                item = WorkOrderModel(
                    id=str(uuid4()), work_order_no=f"{ticket_id}-M-{uuid4().hex[:8].upper()}", ticket_id=ticket_id,
                    task_type="primary", status="pending", department_id=department_id,
                    assignee_user_id=assigned_user_id, instructions=remark, created_by_user_id=principal.user_id,
                )
                self.work_orders.add(item, principal.user_id, "create", remark)
            if db is not None:
                db.commit()
            elif self.work_orders:
                self.work_orders.commit()
        except Exception:
            if db is not None:
                db.rollback()
            elif self.work_orders:
                self.work_orders.rollback()
            raise
        if self.aftercare:
            self.aftercare.on_ticket_event("ticket_assigned", self.get(ticket_id), principal)
        return result

    def process(self, ticket_id, version, remark, principal):
        updates = None
        if principal.role == "department_staff":
            ticket = self.get(ticket_id)
            if ticket.assigned_user_id not in {None, principal.user_id}:
                raise PermissionDenied("该工单已分派给其他承办人")
            updates = {"assigned_user_id": principal.user_id}
        db = self._db()
        try:
            result = self._transition(
                ticket_id, "process", version, remark, principal, updates,
                commit=False, run_aftercare=False,
            )
            if self.work_orders:
                primary = next((item for item in self.work_orders.list_for_ticket(ticket_id)
                                if item.task_type == "primary" and item.status == "pending"), None)
                if primary:
                    previous = primary.status
                    primary.status = "processing"
                    primary.accepted_at = datetime.now(timezone.utc)
                    primary.assignee_user_id = (
                        principal.user_id if principal.role == "department_staff" else primary.assignee_user_id
                    )
                    primary.version += 1
                    self.work_orders.record(primary, principal.user_id, "start", previous, remark)
            if db is not None:
                db.commit()
            elif self.work_orders:
                self.work_orders.commit()
        except Exception:
            if db is not None:
                db.rollback()
            elif self.work_orders:
                self.work_orders.rollback()
            raise
        return result

    def add_note(self, ticket_id, version, remark, principal):
        return self._transition(ticket_id, "note", version, remark, principal)

    def resolve(self, ticket_id, version, remark, resolution_summary, resolution_measures,
                resolution_outcome, public_reply, internal_note, principal):
        if self.work_orders:
            active_orders = [item for item in self.work_orders.list_for_ticket(ticket_id)
                             if item.status not in {"returned", "transferred", "cancelled"}]
            if len(active_orders) > 1:
                raise BusinessError(
                    "COLLABORATION_SUMMARY_REQUIRED",
                    "多部门任务必须分别提交结果后，由主办部门通过汇总接口形成最终答复",
                    409,
                )
        result = self._transition(ticket_id, "resolve", version, remark, principal, {
            "resolution_summary": resolution_summary,
            "resolution_measures": resolution_measures,
            "resolution_outcome": resolution_outcome,
            "public_reply": public_reply,
            "internal_note": internal_note,
            "collaboration_status": "completed",
        }, history_content=public_reply, visibility="public")
        if self.work_orders:
            primary = next((item for item in self.work_orders.list_for_ticket(ticket_id)
                            if item.task_type == "primary" and item.status in {"pending", "processing"}), None)
            if primary:
                previous = primary.status
                primary.status = "submitted"
                primary.result_summary = resolution_summary
                primary.result_measures = resolution_measures
                primary.result_outcome = resolution_outcome
                primary.public_content = public_reply
                primary.internal_note = internal_note
                primary.submitted_at = datetime.now(timezone.utc)
                primary.completed_at = primary.submitted_at
                primary.version += 1
                self.work_orders.record(primary, principal.user_id, "submit_result", previous, remark)
                self.work_orders.commit()
        return result

    def request_supplement(self, ticket_id, version, remark, supplement_reason, principal):
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied("只有坐席或管理员可以退回市民补充材料")
        ticket = self.get(ticket_id)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.status not in {"pending", "accepted"}:
            raise BusinessError("SUPPLEMENT_NOT_ALLOWED", "当前状态不能要求补充材料", 409)
        updated = self.repository.transition(
            ticket.ticket_id, version, ticket.status, "request_supplement",
            f"请补充材料：{supplement_reason.strip()}", principal.user_id,
            {"needs_supplement": True, "collaboration_status": "awaiting_citizen",
             "supplement_reason": supplement_reason.strip(), "supplement_requested_at": datetime.now(timezone.utc)},
            "public",
        )
        if not updated:
            raise VersionConflict()
        self._audit(principal, "request_ticket_supplement", ticket_id=ticket.ticket_id,
                    details={"reason": supplement_reason})
        if self.aftercare:
            self.aftercare.on_ticket_event("supplement_required", updated, principal, supplement_reason.strip())
        return self._present(updated, principal)

    def submit_supplement(self, ticket_id, version, remark, supplement_content, principal):
        AuthorizationPolicy.require_roles(principal, "citizen")
        ticket = self.get(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.collaboration_status != "awaiting_citizen":
            raise BusinessError("SUPPLEMENT_NOT_REQUESTED", "当前工单没有待补充材料", 409)
        updated = self.repository.transition(
            ticket.ticket_id, version, ticket.status, "submit_supplement",
            f"市民已补充：{supplement_content.strip()}", principal.user_id,
            {"needs_supplement": False, "collaboration_status": "none",
             "supplemented_at": datetime.now(timezone.utc)}, "public",
        )
        if not updated:
            raise VersionConflict()
        self._audit(principal, "submit_ticket_supplement", ticket_id=ticket.ticket_id)
        return self._present(updated, principal)

    def close(self, ticket_id, version, remark, override_reason, principal):
        AuthorizationPolicy.require_roles(principal, "admin")
        return self._transition(ticket_id, "close", version, remark, principal, {
            "closure_type": "admin_override",
        }, history_content=f"管理员代为确认办结：{override_reason}", visibility="public")

    def submit_feedback(self, ticket_id, version, rating, comment, principal):
        AuthorizationPolicy.require_roles(principal, "citizen")
        ticket = self.get(ticket_id)
        # P0-R4: permission before version, same reason as _transition.
        if not AuthorizationPolicy.can_view(principal, ticket):
            self._audit(principal, "permission_denied", "denied", ticket.ticket_id, {"operation": "submit_feedback"})
            raise PermissionDenied("只能评价本人创建的工单")
        if ticket.version != version:
            raise VersionConflict()
        if ticket.status != "resolved":
            raise BusinessError(
                "INVALID_STATUS_TRANSITION", "只有待市民确认的工单可以评价", 409,
                {"current_status": ticket.status, "allowed_actions": []},
            )
        now = datetime.now(timezone.utc)
        # P0-B: ratings no longer reopen the ticket. Only satisfied/mostly_satisfied
        # (4-5 star equivalent) close the ticket. dissatisfied (1-3 star) keeps
        # the ticket in resolved; the citizen must submit a formal appeal to reopen.
        if rating == "dissatisfied":
            new_status = "resolved"
            result = "dissatisfied_recorded"
            content = f"市民评价不满意（已记录，如需重开请提交申诉）：{comment}"
            updates = {
                "resolved_at": ticket.resolved_at,
                "closed_at": None,
                "closure_type": None,
            }
        else:
            new_status = "closed"
            result = "closed"
            content = (
                f"市民评价：{'满意' if rating == 'satisfied' else '基本满意'}"
                + (f"；{comment}" if comment else "")
            )
            updates = {
                "resolved_at": ticket.resolved_at,
                "closed_at": now,
                "closure_type": "citizen_confirmed",
            }
        updated = self.repository.feedback_transition(
            ticket.ticket_id, version, new_status, content, principal.user_id,
            updates, rating, comment, result,
        )
        if not updated:
            raise VersionConflict()
        self._audit(principal, "submit_ticket_feedback", ticket_id=ticket.ticket_id, details={
            "rating": rating, "result": result,
        })
        if self.aftercare and new_status == "closed":
            self.aftercare.on_ticket_event("closed", updated, principal)
        return self._present(updated, principal)

    def update_contact(self, ticket_id, version, remark, contact, principal):
        ticket = self.get(ticket_id)
        # P0-R4: permission before version.
        if principal.role not in {"admin", "agent", "citizen"} or not AuthorizationPolicy.can_view(principal, ticket):
            self._audit(principal, "permission_denied", "denied", ticket.ticket_id, {"operation": "update_contact"})
            raise PermissionDenied("无权修改该工单联系方式")
        if ticket.version != version:
            raise VersionConflict()
        updated = self.repository.transition(
            ticket.ticket_id, version, ticket.status, "update_contact", remark,
            principal.user_id, {"contact": contact},
        )
        if not updated:
            raise VersionConflict()
        self._audit(principal, "update_ticket_contact", ticket_id=ticket.ticket_id)
        return self._present(updated, principal)

    def pause_sla(self, ticket_id, version, remark, reason, principal):
        ticket = self.get(ticket_id)
        # P0-R4: permission before version.
        AuthorizationPolicy.require_transition(principal, "pause_sla", ticket)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.status not in {"accepted", "assigned", "processing"}:
            raise BusinessError("SLA_PAUSE_NOT_ALLOWED", "当前状态不能暂停计时", 409)
        if ticket.sla_paused_at:
            raise BusinessError("SLA_ALREADY_PAUSED", "SLA 已处于暂停状态", 409)
        if not reason or len(reason.strip()) < 2:
            raise BusinessError("SLA_PAUSE_REASON_REQUIRED", "暂停计时必须填写原因", 422)
        now = datetime.now(timezone.utc)
        updated = self.repository.transition(ticket_id, version, ticket.status, "pause_sla", remark,
                                             principal.user_id, {"sla_paused_at": now, "sla_pause_reason": reason.strip()})
        if not updated:
            raise VersionConflict()
        self._audit(principal, "pause_ticket_sla", ticket_id=ticket_id, details={"reason": reason.strip()})
        return self._present(updated, principal)

    def resume_sla(self, ticket_id, version, remark, principal):
        ticket = self.get(ticket_id)
        # P0-R4: permission before version.
        AuthorizationPolicy.require_transition(principal, "resume_sla", ticket)
        if ticket.version != version:
            raise VersionConflict()
        if not ticket.sla_paused_at:
            raise BusinessError("SLA_NOT_PAUSED", "SLA 当前未暂停", 409)
        now = datetime.now(timezone.utc)
        seconds = max(0, int((now - ticket.sla_paused_at).total_seconds()))
        delta = timedelta(seconds=seconds)
        updated = self.repository.transition(ticket_id, version, ticket.status, "resume_sla", remark,
            principal.user_id, {
                "sla_paused_at": None, "sla_pause_reason": None,
                "total_paused_seconds": ticket.total_paused_seconds + seconds,
                "accept_due_at": ticket.accept_due_at + delta if ticket.accept_due_at else None,
                "resolve_due_at": ticket.resolve_due_at + delta if ticket.resolve_due_at else None,
            })
        if not updated:
            raise VersionConflict()
        self._audit(principal, "resume_ticket_sla", ticket_id=ticket_id, details={"paused_seconds": seconds})
        return self._present(updated, principal)

    def remind(self, ticket_id, version, remark, principal):
        ticket = self.get(ticket_id)
        # P0-R4: permission before version.
        if ticket.status in {"resolved", "closed", "rejected"}:
            raise BusinessError("REMINDER_NOT_ALLOWED", "终态工单不能催办", 409)
        if principal.role == "citizen":
            AuthorizationPolicy.require_view(principal, ticket)
        elif principal.role == "department_staff":
            AuthorizationPolicy.require_transition(principal, "note", ticket)
        elif principal.role not in {"agent", "admin"}:
            raise PermissionDenied("当前角色不能催办")
        if ticket.version != version:
            raise VersionConflict()
        updated = self.repository.transition(ticket_id, version, ticket.status, "remind", remark,
                                             principal.user_id, {"reminder_count": ticket.reminder_count + 1}, "public")
        if not updated:
            raise VersionConflict()
        self._audit(principal, "remind_ticket", ticket_id=ticket_id,
                    details={"count": updated.reminder_count})
        return self._present(updated, principal)

    def update_status(self, ticket_id: str, status: str, remark: Optional[str], version: int | None = None, principal: Principal | None = None):
        """Compatibility entrypoint; it still delegates to the strict state machine."""
        principal = principal or Principal(kind="user", username="legacy-admin", role="admin")
        mapping = {"accepted": self.accept, "processing": self.process}
        if status not in mapping or version is None or not remark:
            raise BusinessError("INVALID_STATUS", "请使用合法目标状态、备注和 version", 422)
        return mapping[status](ticket_id, version, remark, principal)
