import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied, TicketNotFound, VersionConflict
from ..models import AppealModel, FollowUpTaskModel, NotificationModel, PhoneFollowUpRecordModel, TicketStatusHistoryModel, UserModel
from ..repositories.aftercare import AftercareRepository, NotificationRepository
from ..repositories.identity import AuditRepository
from ..schemas import AppealList, AppealRead, FollowUpTaskList, FollowUpTaskRead, NotificationList, NotificationRead, PhoneFollowUpRecordRead


logger = logging.getLogger(__name__)


APPEAL_LIMIT = 2
APPEAL_WINDOW_DAYS = 15
FOLLOW_UP_DUE_HOURS = 48
ACTIVE_APPEAL_STATUSES = {"submitted", "approved", "reprocessing"}

EVENT_COPY = {
    "ticket_created": ("工单创建成功", "您的诉求已登记，工单号为 {ticket_id}。"),
    "ticket_accepted": ("工单已受理", "工单 {ticket_id} 已受理，正在安排承办。"),
    "supplement_required": ("需要补充材料", "工单 {ticket_id} 需要补充材料：{detail}"),
    "ticket_assigned": ("工单已派发", "工单 {ticket_id} 已派发至承办部门。"),
    "ticket_due_soon": ("工单即将超时", "工单 {ticket_id} 距办理时限不足 4 小时，请及时处理。"),
    "ticket_overdue": ("工单已超时", "工单 {ticket_id} 已超过办理时限，请立即处理或升级。"),
    "processing_completed": ("处理完成", "工单 {ticket_id} 已形成处理结果。"),
    "awaiting_confirmation": ("等待市民确认", "请查看工单 {ticket_id} 的办理结果并确认或提出申诉。"),
    "ticket_closed": ("工单已办结", "工单 {ticket_id} 已办结，感谢您的参与。"),
    "appeal_submitted": ("收到市民申诉", "工单 {ticket_id} 有新的市民申诉，请审核。"),
    "appeal_approved": ("申诉审核通过", "工单 {ticket_id} 的申诉已通过审核，将重新办理。"),
    "appeal_rejected": ("申诉审核结果", "工单 {ticket_id} 的申诉未通过审核：{detail}"),
    "appeal_completed": ("申诉处理完成", "工单 {ticket_id} 的重新办理结果已出具：{detail}"),
    "appeal_prompt": ("请提交正式申诉", "电话回访中记录到您对工单 {ticket_id} 有异议，请在申诉期限内提交正式申诉。"),
}


class AftercareService:
    def __init__(self, repository: AftercareRepository, notifications: NotificationRepository, audit: AuditRepository):
        self.repository = repository
        self.notifications = notifications
        self.audit = audit

    def _audit(self, principal, action, resource_type, resource_id, details=None, *, commit: bool = True):
        self.audit.log(principal, action, "success", resource_type, resource_id, details, commit=commit)

    def _emit_best_effort(self, event_type: str, ticket, *, detail: str = "", occurrence: str | int | None = None,
                          recipient_ids: set[int] | None = None, threshold_level: str = "info") -> None:
        try:
            self.emit(event_type, ticket, detail=detail, occurrence=occurrence,
                      recipient_ids=recipient_ids, threshold_level=threshold_level)
        except Exception:
            logger.exception("notification emit failed for %s on %s", event_type, getattr(ticket, "ticket_id", None))

    def _role_user_ids(self, *roles: str) -> list[int]:
        return list(self.repository.db.scalars(select(UserModel.id).where(
            UserModel.role.in_(roles), UserModel.is_active.is_(True)
        )).all())

    def _department_user_ids(self, department_id: int | None) -> list[int]:
        if department_id is None:
            return []
        return list(self.repository.db.scalars(select(UserModel.id).where(
            UserModel.role == "department_staff", UserModel.department_id == department_id, UserModel.is_active.is_(True)
        )).all())

    def _duty_agent_ids(self) -> list[int]:
        """Return the duty agent(s) for unassigned ticket queue notifications.

        P0-G: instead of broadcasting to ALL agents, notify only the first
        active agent (the "duty agent" in demo). In production this would be
        replaced by a real on-call roster.
        """
        return list(self.repository.db.scalars(select(UserModel.id).where(
            UserModel.role == "agent", UserModel.is_active.is_(True)
        ).order_by(UserModel.id).limit(1)).all())

    def _work_order_assignee_ids(self, ticket) -> list[int]:
        """Return active work order assignees for the ticket (P0-G)."""
        from ..models import WorkOrderModel
        return list(self.repository.db.scalars(select(WorkOrderModel.assignee_user_id).where(
            WorkOrderModel.ticket_id == ticket.ticket_id,
            WorkOrderModel.assignee_user_id.is_not(None),
            WorkOrderModel.status.notin_(("returned", "transferred", "cancelled")),
        )).all())

    def _recipients(self, event_type: str, ticket) -> set[int]:
        """Determine notification recipients.

        P0-G+ round-2 narrowing:
        - ticket_due_soon (normal approaching deadline):
          * pending: notify only duty agent (single agent, not all agents)
          * assigned/processing: notify assigned_user + primary dept staff + work order assignees
          * admins are NOT notified for normal due_soon (only for overdue escalation)
          * citizens never receive internal SLA notifications
        - ticket_overdue (deadline already passed, escalation):
          * notify assigned_user + primary dept staff + all admins (escalation)
        - appeal_submitted: admins only (they are the reviewers)
        """
        recipients: set[int] = set()
        if event_type == "ticket_due_soon":
            # Internal SLA notification — citizens must NOT receive this (P0-G).
            if ticket.status == "pending":
                # Pending: notify only the duty agent (not all agents)
                recipients.update(self._duty_agent_ids())
            else:
                # assigned/processing: notify assigned_user + primary dept staff + work order assignees
                if ticket.assigned_user_id:
                    recipients.add(ticket.assigned_user_id)
                else:
                    recipients.update(self._department_user_ids(ticket.assigned_department_id))
                # Also notify work order assignees (P0-G: actual handler)
                recipients.update(self._work_order_assignee_ids(ticket))
            return recipients
        if event_type == "ticket_overdue":
            # Escalation: notify assigned_user + dept staff + all admins
            if ticket.assigned_user_id:
                recipients.add(ticket.assigned_user_id)
            else:
                recipients.update(self._department_user_ids(ticket.assigned_department_id))
            recipients.update(self._work_order_assignee_ids(ticket))
            recipients.update(self._role_user_ids("admin"))
            return recipients
        if event_type == "appeal_submitted":
            # Only admins review appeals — do not broadcast to all agents.
            recipients.update(self._role_user_ids("admin"))
            if ticket.assigned_user_id:
                recipients.add(ticket.assigned_user_id)
            recipients.discard(ticket.creator_user_id)
            return recipients
        # Other events: keep existing recipient logic
        if ticket.creator_user_id:
            recipients.add(ticket.creator_user_id)
        if event_type == "ticket_created":
            recipients.update(self._role_user_ids("agent"))
        if event_type in {"ticket_assigned", "appeal_approved", "appeal_completed"}:
            if ticket.assigned_user_id:
                recipients.add(ticket.assigned_user_id)
            else:
                recipients.update(self._department_user_ids(ticket.assigned_department_id))
        return recipients

    def emit(self, event_type: str, ticket, *, detail: str = "", occurrence: str | int | None = None,
             recipient_ids: set[int] | None = None, threshold_level: str = "info") -> None:
        title, template = EVENT_COPY[event_type]
        content = template.format(ticket_id=ticket.ticket_id, detail=detail)
        recipients = recipient_ids if recipient_ids is not None else self._recipients(event_type, ticket)
        marker = occurrence if occurrence is not None else ticket.version
        # P0-G: idempotency key must include ticket_id + handling_round + event_type
        # + threshold_level + recipient_user_id to prevent duplicate notifications.
        handling_round = getattr(ticket, "handling_round", 1) or 1
        items = [NotificationModel(
            id=str(uuid4()), recipient_user_id=user_id, ticket_id=ticket.ticket_id,
            event_type=event_type, channel="in_app", title=title, content=content,
            status="unread", delivery_status="delivered",
            event_key=f"{event_type}:{ticket.ticket_id}:r{handling_round}:{threshold_level}:{marker}:{user_id}",
            metadata_json=json.dumps({"ticket_id": ticket.ticket_id, "handling_round": handling_round, "threshold_level": threshold_level}, ensure_ascii=False),
        ) for user_id in recipients]
        self.notifications.add_missing(items)

    def on_ticket_event(self, event_type: str, ticket, principal: Principal | None = None, detail: str = "") -> None:
        if event_type == "resolved":
            active = self.repository.active_appeal(ticket.ticket_id)
            if active and active.status == "reprocessing":
                active.status = "completed"
                active.result_summary = ticket.public_reply or ticket.resolution_summary
                active.completed_at = datetime.now(timezone.utc)
                self.repository.commit()
                self._emit_best_effort("appeal_completed", ticket, detail=active.result_summary or "已完成", occurrence=active.appeal_no)
                if principal:
                    self._audit(principal, "complete_appeal", "appeal", active.id, {"appeal_no": active.appeal_no})
            self._ensure_follow_up(ticket)
            self._emit_best_effort("processing_completed", ticket, occurrence=ticket.handling_round)
            self._emit_best_effort("awaiting_confirmation", ticket, occurrence=ticket.handling_round)
            return
        if event_type == "closed":
            for task in ticket.follow_up_tasks:
                if task.status in {"pending", "in_progress"}:
                    task.status = "cancelled"
                    task.completed_at = datetime.now(timezone.utc)
            self.repository.commit()
            self._emit_best_effort("ticket_closed", ticket, occurrence=ticket.handling_round)
            return
        self._emit_best_effort(event_type, ticket, detail=detail)

    def _ensure_follow_up(self, ticket) -> FollowUpTaskModel:
        existing = self.repository.db.scalar(select(FollowUpTaskModel).where(
            FollowUpTaskModel.ticket_id == ticket.ticket_id,
            FollowUpTaskModel.handling_round == ticket.handling_round,
        ))
        if existing:
            return existing
        task = FollowUpTaskModel(
            id=str(uuid4()), ticket_id=ticket.ticket_id, handling_round=ticket.handling_round,
            status="pending", due_at=datetime.now(timezone.utc) + timedelta(hours=FOLLOW_UP_DUE_HOURS),
        )
        self.repository.db.add(task)
        self.repository.commit()
        return task

    def scan_due_soon(self) -> None:
        threshold = datetime.now(timezone.utc) + timedelta(hours=4)
        for ticket in self.repository.due_soon_tickets(threshold):
            deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
            # P0-G: pass threshold_level for idempotency key uniqueness
            self.emit("ticket_due_soon", ticket,
                      occurrence=deadline.isoformat() if deadline else ticket.version,
                      threshold_level="due_soon")

    def scan_overdue(self) -> None:
        """P0-G+: scan overdue tickets and emit escalation notifications to admins."""
        for ticket in self.repository.overdue_tickets():
            deadline = ticket.accept_due_at if ticket.status == "pending" else ticket.resolve_due_at
            self.emit("ticket_overdue", ticket,
                      occurrence=deadline.isoformat() if deadline else ticket.version,
                      threshold_level="overdue")

    def list_notifications(self, principal: Principal, page: int, page_size: int, unread_only: bool):
        AuthorizationPolicy.require_roles(principal, "citizen", "agent", "department_staff", "admin")
        items, total, unread = self.notifications.list_for_user(principal.user_id, page, page_size, unread_only)
        return NotificationList(items=[NotificationRead.model_validate(item) for item in items], page=page,
                                page_size=page_size, total=total, unread_count=unread)

    def read_notification(self, notification_id: str, principal: Principal):
        item = self.notifications.mark_read(notification_id, principal.user_id)
        if not item:
            raise BusinessError("NOTIFICATION_NOT_FOUND", "通知不存在", 404)
        self._audit(principal, "read_notification", "notification", item.id)
        return NotificationRead.model_validate(item)

    def read_all_notifications(self, principal: Principal) -> int:
        count = self.notifications.mark_all_read(principal.user_id)
        self._audit(principal, "read_all_notifications", "notification", str(principal.user_id), {"count": count})
        return count

    @staticmethod
    def _follow_up_read(item: FollowUpTaskModel) -> FollowUpTaskRead:
        records = [PhoneFollowUpRecordRead.model_validate(record).model_copy(update={
            "caller_name": record.caller.display_name if record.caller else None,
        }) for record in sorted(item.records, key=lambda value: value.created_at, reverse=True)]
        return FollowUpTaskRead.model_validate(item).model_copy(update={
            "assignee_name": item.assignee.display_name if item.assignee else None,
            "records": records,
        })

    @staticmethod
    def _appeal_read(item: AppealModel, principal: Principal) -> AppealRead:
        result = AppealRead.model_validate(item).model_copy(update={
            "citizen_name": item.citizen.display_name if item.citizen else None,
            "reviewer_name": item.reviewer.display_name if item.reviewer else None,
        })
        if principal.role == "citizen":
            result = result.model_copy(update={"reprocess_instructions": None})
        return result

    def list_follow_ups(self, principal: Principal, page: int, page_size: int, status: str | None):
        AuthorizationPolicy.require_roles(principal, "agent", "admin")
        if status and status not in {"pending", "in_progress", "completed", "cancelled"}:
            raise BusinessError("INVALID_FOLLOW_UP_STATUS", "回访状态筛选值无效", 422)
        items, total = self.repository.list_follow_ups(principal, page, page_size, status)
        return FollowUpTaskList(items=[self._follow_up_read(item) for item in items], page=page, page_size=page_size, total=total)

    def list_appeals(self, principal: Principal, page: int, page_size: int, status: str | None):
        AuthorizationPolicy.require_roles(principal, "citizen", "agent", "department_staff", "admin")
        allowed = {"submitted", "approved", "rejected", "reprocessing", "completed"}
        if status and status not in allowed:
            raise BusinessError("INVALID_APPEAL_STATUS", "申诉状态筛选值无效", 422)
        items, total = self.repository.list_appeals(principal, page, page_size, status)
        return AppealList(items=[self._appeal_read(item, principal) for item in items], page=page, page_size=page_size, total=total)

    def create_appeal(self, ticket_id: str, reason: str, desired_resolution: str, principal: Principal):
        AuthorizationPolicy.require_roles(principal, "citizen")
        ticket = self.repository.ticket(ticket_id, lock=True)
        if not ticket:
            raise TicketNotFound(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        if ticket.status not in {"resolved", "closed"}:
            raise BusinessError("APPEAL_NOT_ALLOWED", "只有处理完成或已办结工单可以申诉", 409)
        reference = ticket.closed_at or ticket.resolved_at
        if not reference or datetime.now(timezone.utc) > reference + timedelta(days=APPEAL_WINDOW_DAYS):
            raise BusinessError("APPEAL_WINDOW_EXPIRED", f"申诉须在处理完成后 {APPEAL_WINDOW_DAYS} 天内提交", 409)
        if ticket.appeal_count >= APPEAL_LIMIT:
            raise BusinessError("APPEAL_LIMIT_REACHED", f"同一工单最多申诉 {APPEAL_LIMIT} 次", 409)
        if self.repository.active_appeal(ticket.ticket_id):
            raise BusinessError("ACTIVE_APPEAL_EXISTS", "当前工单已有待处理申诉", 409)
        sequence = ticket.appeal_count + 1
        item = AppealModel(
            id=str(uuid4()), appeal_no=f"{ticket.ticket_id}-SS-{sequence}", ticket_id=ticket.ticket_id,
            citizen_user_id=principal.user_id, sequence=sequence, status="submitted",
            reason=reason.strip(), desired_resolution=desired_resolution.strip(),
        )
        ticket.appeal_count = sequence
        ticket.version += 1
        self.repository.db.add(item)
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="submit_appeal",
            content=f"市民提交第 {sequence} 次申诉", previous_status=ticket.status,
            current_status=ticket.status, remark=reason.strip(), visibility="public",
        ))
        try:
            self._audit(principal, "submit_appeal", "appeal", item.id,
                        {"ticket_id": ticket.ticket_id, "sequence": sequence}, commit=False)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        self.repository.db.refresh(item)
        self._emit_best_effort("appeal_submitted", ticket, occurrence=item.appeal_no)
        return self._appeal_read(item, principal)

    def review_appeal(self, appeal_id: str, decision: str, review_comment: str,
                      reprocess_instructions: str | None, principal: Principal):
        AuthorizationPolicy.require_roles(principal, "admin")
        item = self.repository.appeal(appeal_id, lock=True)
        if not item:
            raise BusinessError("APPEAL_NOT_FOUND", "申诉不存在", 404)
        if item.status != "submitted":
            raise BusinessError("APPEAL_ALREADY_REVIEWED", "申诉已经审核，不能重复操作", 409)
        ticket = self.repository.ticket(item.ticket_id, lock=True)
        if not ticket:
            raise TicketNotFound(item.ticket_id)
        now = datetime.now(timezone.utc)
        item.review_comment = review_comment.strip()
        item.reviewed_by_user_id = principal.user_id
        item.reviewed_at = now
        if decision == "rejected":
            item.status = "rejected"
            item.completed_at = now
            event = "appeal_rejected"
            detail = item.review_comment
        else:
            item.status = "reprocessing"
            item.reprocess_instructions = (reprocess_instructions or "").strip()
            previous = ticket.status
            for task in ticket.follow_up_tasks:
                if task.status in {"pending", "in_progress"}:
                    task.status = "cancelled"
                    task.completed_at = now
            ticket.status = "processing"
            ticket.handling_round += 1
            ticket.resolved_at = None
            ticket.closed_at = None
            ticket.closure_type = None
            ticket.collaboration_status = "in_progress"
            ticket.version += 1
            # P0-A: reset primary work order so department can re-submit after appeal approval.
            from ..models import WorkOrderModel
            primary_order = self.repository.db.scalar(select(WorkOrderModel).where(
                WorkOrderModel.ticket_id == ticket.ticket_id,
                WorkOrderModel.task_type == "primary",
                WorkOrderModel.status.notin_(("returned", "transferred", "cancelled")),
            ))
            if primary_order:
                primary_order.status = "processing"
                primary_order.submitted_at = None
                primary_order.completed_at = None
                primary_order.result_summary = None
                primary_order.result_measures = None
                primary_order.result_outcome = None
                primary_order.public_content = None
                primary_order.internal_note = None
                primary_order.version += 1
            self.repository.db.add(TicketStatusHistoryModel(
                ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="approve_appeal",
                content=f"第 {item.sequence} 次申诉审核通过，进入重新办理",
                previous_status=previous, current_status="processing",
                remark=item.reprocess_instructions, visibility="public",
            ))
            event = "appeal_approved"
            detail = item.reprocess_instructions
        try:
            self._audit(principal, "review_appeal", "appeal", item.id,
                        {"decision": decision, "ticket_id": ticket.ticket_id}, commit=False)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        self._emit_best_effort(event, ticket, detail=detail, occurrence=item.appeal_no)
        return self._appeal_read(item, principal)

    def record_phone_follow_up(self, task_id: str, ticket_version: int, contact_result: str,
                               satisfaction: str | None, outcome: str, notes: str, principal: Principal):
        AuthorizationPolicy.require_roles(principal, "agent", "admin")
        task = self.repository.follow_up(task_id, lock=True)
        if not task:
            raise BusinessError("FOLLOW_UP_NOT_FOUND", "回访任务不存在", 404)
        if task.status in {"completed", "cancelled"}:
            raise BusinessError("FOLLOW_UP_CLOSED", "回访任务已经结束", 409)
        ticket = self.repository.ticket(task.ticket_id, lock=True)
        if not ticket:
            raise TicketNotFound(task.ticket_id)
        if ticket.version != ticket_version:
            raise VersionConflict()
        record = PhoneFollowUpRecordModel(
            id=str(uuid4()), task_id=task.id, ticket_id=ticket.ticket_id,
            caller_user_id=principal.user_id, contact_result=contact_result,
            satisfaction=satisfaction, outcome=outcome, notes=notes.strip(),
        )
        task.records.append(record)
        now = datetime.now(timezone.utc)
        if outcome == "needs_followup":
            task.status = "in_progress"
        else:
            task.status = "completed"
            task.completed_at = now
        if outcome == "confirmed":
            if ticket.status != "resolved":
                raise BusinessError("FOLLOW_UP_CONFIRM_NOT_ALLOWED", "只有待确认工单可以通过回访办结", 409)
            ticket.status = "closed"
            ticket.closed_at = now
            ticket.closure_type = "phone_confirmed"
            ticket.version += 1
            self.repository.db.add(TicketStatusHistoryModel(
                ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="phone_follow_up_close",
                content="电话回访确认办理结果，工单办结", previous_status="resolved", current_status="closed",
                remark=notes.strip(), visibility="public",
            ))
        try:
            self._audit(principal, "record_phone_follow_up", "follow_up_task", task.id, {
                "ticket_id": ticket.ticket_id, "contact_result": contact_result, "outcome": outcome,
            }, commit=False)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        self.repository.db.refresh(record)
        if outcome == "confirmed":
            self._emit_best_effort("ticket_closed", ticket, occurrence=f"phone-{task.handling_round}")
        elif outcome == "appeal_requested" and ticket.creator_user_id:
            self._emit_best_effort("appeal_prompt", ticket, occurrence=record.id, recipient_ids={ticket.creator_user_id})
        return self._follow_up_read(self.repository.follow_up(task.id))
