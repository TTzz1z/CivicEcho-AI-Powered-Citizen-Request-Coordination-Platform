from datetime import datetime, timezone
from uuid import uuid4

from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied, TicketNotFound, VersionConflict
from ..models import TicketStatusHistoryModel, WorkOrderModel
from ..repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from ..repositories.work_orders import WorkOrderRepository
from ..schemas import TicketResolve, WorkOrderRead


ACTIVE_STATUSES = {"pending", "processing", "submitted"}


class WorkOrderService:
    def __init__(self, repository: WorkOrderRepository, departments: DepartmentRepository,
                 users: UserRepository, audit: AuditRepository):
        self.repository = repository
        self.departments = departments
        self.users = users
        self.audit = audit

    @staticmethod
    def _present(item: WorkOrderModel) -> WorkOrderRead:
        return WorkOrderRead.model_validate(item).model_copy(update={
            "department_name": item.department.name if item.department else None,
            "assignee_name": item.assignee.display_name if item.assignee else None,
            "history": sorted(item.history, key=lambda value: value.created_at),
        })

    def _ticket(self, ticket_id: str, principal: Principal, *, lock: bool = False):
        ticket = self.repository.ticket(ticket_id, for_update=lock)
        if not ticket:
            raise TicketNotFound(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        return ticket

    def _validate_department(self, department_id: int):
        department = self.departments.get(department_id)
        if not department or not department.is_active:
            raise BusinessError("INVALID_DEPARTMENT", "目标部门不存在或已停用", 422)
        return department

    def _validate_assignee(self, user_id: int | None, department_id: int):
        if user_id is None:
            return None
        user = self.users.get(user_id)
        if not user or not user.is_active or user.role != "department_staff" or user.department_id != department_id:
            raise BusinessError("INVALID_ASSIGNEE", "责任人必须是目标部门的在职办理人员", 422)
        return user

    @staticmethod
    def _can_operate(item: WorkOrderModel, principal: Principal) -> bool:
        return principal.role == "admin" or (
            principal.role == "department_staff"
            and principal.department_id == item.department_id
            and (item.assignee_user_id is None or item.assignee_user_id == principal.user_id)
        )

    def list(self, ticket_id: str, principal: Principal) -> list[WorkOrderRead]:
        self._ticket(ticket_id, principal)
        return [self._present(item) for item in self.repository.list_for_ticket(ticket_id)]

    def create(self, ticket_id: str, version: int, task_type: str, department_id: int,
               assignee_user_id: int | None, instructions: str, principal: Principal) -> WorkOrderRead:
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied("只有坐席或管理员可以创建部门任务")
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.status not in {"accepted", "assigned", "processing"}:
            raise BusinessError("WORK_ORDER_NOT_ALLOWED", "当前主单状态不能创建部门任务", 409)
        department = self._validate_department(department_id)
        self._validate_assignee(assignee_user_id, department_id)
        existing = self.repository.list_for_ticket(ticket_id)
        if task_type == "primary" and any(x.task_type == "primary" and x.status in ACTIVE_STATUSES for x in existing):
            raise BusinessError("PRIMARY_WORK_ORDER_EXISTS", "主办任务已存在；请使用转派或争议协调", 409)
        if task_type in {"support", "review"} and not any(x.task_type == "primary" and x.status in ACTIVE_STATUSES for x in existing):
            raise BusinessError("PRIMARY_WORK_ORDER_REQUIRED", "请先创建主办任务", 409)
        suffix = uuid4().hex[:8].upper()
        type_code = {"primary": "M", "support": "C", "review": "R"}[task_type]
        item = WorkOrderModel(
            id=str(uuid4()), work_order_no=f"{ticket.ticket_id}-{type_code}-{suffix}", ticket_id=ticket.ticket_id,
            task_type=task_type, status="pending", department_id=department_id,
            assignee_user_id=assignee_user_id, instructions=instructions.strip(), created_by_user_id=principal.user_id,
        )
        self.repository.add(item, principal.user_id, "create", instructions.strip())
        previous = ticket.status
        if task_type == "primary":
            ticket.assigned_department_id = department_id
            ticket.assigned_user_id = assignee_user_id
            ticket.status = "assigned"
        ticket.collaboration_status = "in_progress"
        ticket.dispatch_return_reason = None
        ticket.version += 1
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="create_work_order",
            content=f"创建{'主办' if task_type == 'primary' else '协办' if task_type == 'support' else '复核'}任务：{department.name}",
            previous_status=previous, current_status=ticket.status, remark=instructions.strip(), visibility="internal",
        ))
        self.repository.commit()
        self.audit.log(principal, "create_work_order", resource_type="work_order", resource_id=item.id,
                       details={"ticket_id": ticket.ticket_id, "task_type": task_type, "department_id": department_id})
        return self._present(self.repository.get(item.id))

    def assign(self, work_order_id: str, version: int, assignee_user_id: int, remark: str,
               principal: Principal) -> WorkOrderRead:
        item = self.repository.get(work_order_id, for_update=True)
        if not item:
            raise BusinessError("WORK_ORDER_NOT_FOUND", "部门任务不存在", 404)
        if principal.role not in {"agent", "admin"} and not (
            principal.role == "department_staff" and principal.department_id == item.department_id
        ):
            raise PermissionDenied("无权指定该任务责任人")
        if item.version != version:
            raise VersionConflict()
        self._validate_assignee(assignee_user_id, item.department_id)
        previous = item.status
        item.assignee_user_id = assignee_user_id
        item.version += 1
        self.repository.record(item, principal.user_id, "assign", previous, remark)
        self.repository.commit()
        self.audit.log(principal, "assign_work_order", resource_type="work_order", resource_id=item.id,
                       details={"assignee_user_id": assignee_user_id})
        return self._present(self.repository.get(item.id))

    def start(self, work_order_id: str, version: int, remark: str, principal: Principal) -> WorkOrderRead:
        item = self.repository.get(work_order_id, for_update=True)
        if not item:
            raise BusinessError("WORK_ORDER_NOT_FOUND", "部门任务不存在", 404)
        if not self._can_operate(item, principal):
            raise PermissionDenied("无权办理该部门任务")
        if item.version != version:
            raise VersionConflict()
        if item.status != "pending":
            raise BusinessError("INVALID_WORK_ORDER_STATUS", "只有待办理任务可以开始处理", 409)
        previous = item.status
        item.status = "processing"
        item.accepted_at = datetime.now(timezone.utc)
        if principal.role == "department_staff" and item.assignee_user_id is None:
            item.assignee_user_id = principal.user_id
        item.version += 1
        ticket = self.repository.ticket(item.ticket_id, for_update=True)
        if item.task_type == "primary":
            ticket.status = "processing"
            ticket.assigned_user_id = item.assignee_user_id
        ticket.version += 1
        self.repository.record(item, principal.user_id, "start", previous, remark)
        self.repository.commit()
        self.audit.log(principal, "start_work_order", resource_type="work_order", resource_id=item.id)
        return self._present(self.repository.get(item.id))

    def return_to_agent(self, work_order_id: str, version: int, remark: str, principal: Principal) -> WorkOrderRead:
        item = self.repository.get(work_order_id, for_update=True)
        if not item:
            raise BusinessError("WORK_ORDER_NOT_FOUND", "部门任务不存在", 404)
        if not self._can_operate(item, principal):
            raise PermissionDenied("无权退回该部门任务")
        if item.version != version:
            raise VersionConflict()
        if item.status not in {"pending", "processing"}:
            raise BusinessError("INVALID_WORK_ORDER_STATUS", "当前任务不能退回", 409)
        previous = item.status
        item.status = "returned"
        item.return_reason = remark.strip()
        item.version += 1
        ticket = self.repository.ticket(item.ticket_id, for_update=True)
        ticket.collaboration_status = "awaiting_dispatch"
        ticket.dispatch_return_reason = remark.strip()
        if item.task_type == "primary":
            ticket.status = "accepted"
            ticket.assigned_department_id = None
            ticket.assigned_user_id = None
        self.repository.record(item, principal.user_id, "return_to_agent", previous, remark)
        ticket.version += 1
        self.repository.commit()
        self.audit.log(principal, "return_work_order", resource_type="work_order", resource_id=item.id,
                       details={"reason": remark})
        return self._present(self.repository.get(item.id))

    def transfer(self, work_order_id: str, version: int, target_department_id: int,
                 assignee_user_id: int | None, remark: str, principal: Principal) -> WorkOrderRead:
        item = self.repository.get(work_order_id, for_update=True)
        if not item:
            raise BusinessError("WORK_ORDER_NOT_FOUND", "部门任务不存在", 404)
        if not self._can_operate(item, principal):
            raise PermissionDenied("无权转派该部门任务")
        if item.version != version:
            raise VersionConflict()
        if item.status not in {"pending", "processing"}:
            raise BusinessError("INVALID_WORK_ORDER_STATUS", "当前任务不能转派", 409)
        if target_department_id == item.department_id:
            raise BusinessError("SAME_DEPARTMENT", "请选择其他部门", 422)
        self._validate_department(target_department_id)
        self._validate_assignee(assignee_user_id, target_department_id)
        previous = item.status
        item.status = "transferred"
        item.return_reason = remark.strip()
        item.version += 1
        self.repository.record(item, principal.user_id, "transfer_out", previous, remark)
        successor = WorkOrderModel(
            id=str(uuid4()), work_order_no=f"{item.ticket_id}-T-{uuid4().hex[:8].upper()}",
            ticket_id=item.ticket_id, task_type=item.task_type, status="pending",
            department_id=target_department_id, assignee_user_id=assignee_user_id,
            instructions=f"由 {item.department.name} 转派：{remark.strip()}", source_work_order_id=item.id,
            created_by_user_id=principal.user_id,
        )
        self.repository.add(successor, principal.user_id, "transfer_in", successor.instructions)
        ticket = self.repository.ticket(item.ticket_id, for_update=True)
        if item.task_type == "primary":
            ticket.assigned_department_id = target_department_id
            ticket.assigned_user_id = assignee_user_id
            ticket.status = "assigned"
        ticket.collaboration_status = "in_progress"
        ticket.version += 1
        self.repository.commit()
        self.audit.log(principal, "transfer_work_order", resource_type="work_order", resource_id=item.id,
                       details={"successor_id": successor.id, "target_department_id": target_department_id})
        return self._present(self.repository.get(successor.id))

    def submit(self, work_order_id: str, version: int, remark: str, result_summary: str,
               result_measures: str, result_outcome: str, public_content: str,
               internal_note: str | None, principal: Principal) -> WorkOrderRead:
        item = self.repository.get(work_order_id, for_update=True)
        if not item:
            raise BusinessError("WORK_ORDER_NOT_FOUND", "部门任务不存在", 404)
        if not self._can_operate(item, principal):
            raise PermissionDenied("无权提交该部门任务结果")
        if item.version != version:
            raise VersionConflict()
        if item.status not in {"pending", "processing"}:
            raise BusinessError("INVALID_WORK_ORDER_STATUS", "当前任务不能提交结果", 409)
        previous = item.status
        item.status = "submitted"
        item.result_summary = result_summary.strip()
        item.result_measures = result_measures.strip()
        item.result_outcome = result_outcome
        item.public_content = public_content.strip()
        item.internal_note = internal_note.strip() if internal_note else None
        item.submitted_at = datetime.now(timezone.utc)
        item.version += 1
        self.repository.record(item, principal.user_id, "submit_result", previous, remark)
        ticket = self.repository.ticket(item.ticket_id, for_update=True)
        ticket.version += 1
        active = [x for x in self.repository.list_for_ticket(item.ticket_id) if x.status not in {"returned", "transferred", "cancelled"}]
        if (active and all(x.status == "submitted" for x in active)
                and ticket.collaboration_status != "awaiting_dispatch"):
            ticket.collaboration_status = "awaiting_summary"
        self.repository.commit()
        self.audit.log(principal, "submit_work_order_result", resource_type="work_order", resource_id=item.id)
        return self._present(self.repository.get(item.id))

    def summarize(self, ticket_id: str, payload: TicketResolve, principal: Principal):
        """Primary department submits final reply for agent review (P0-A).

        Previously this method set ticket.status="resolved" directly. Now it
        only records the resolution payload and moves collaboration_status to
        awaiting_review. The master ticket remains in "processing" until an
        agent calls review_and_resolve (or admin fallback).
        """
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != payload.version:
            raise VersionConflict()
        orders = [x for x in self.repository.list_for_ticket(ticket_id) if x.status not in {"returned", "transferred", "cancelled"}]
        primary = next((x for x in orders if x.task_type == "primary"), None)
        if principal.role != "admin" and not (
            primary and principal.role == "department_staff" and principal.department_id == primary.department_id
            and (primary.assignee_user_id is None or primary.assignee_user_id == principal.user_id)
        ):
            raise PermissionDenied("只有主办部门责任人可以汇总最终答复")
        if not primary or any(x.status != "submitted" for x in orders):
            raise BusinessError("WORK_ORDERS_NOT_READY", "所有有效主办、协办和复核任务提交后才能汇总", 409)
        if ticket.status not in {"assigned", "processing"}:
            raise BusinessError("INVALID_STATUS_TRANSITION", "当前主单不能汇总答复", 409)
        if ticket.collaboration_status == "awaiting_review":
            raise BusinessError("ALREADY_AWAITING_REVIEW", "工单已提交待审核，请等待坐席审核", 409)
        now = datetime.now(timezone.utc)
        previous = ticket.status
        # P0-A: master ticket stays in processing; only collaboration_status advances.
        ticket.collaboration_status = "awaiting_review"
        ticket.resolution_summary = payload.resolution_summary
        ticket.resolution_measures = payload.resolution_measures
        ticket.resolution_outcome = payload.resolution_outcome
        ticket.public_reply = payload.public_reply
        ticket.internal_note = payload.internal_note
        ticket.version += 1
        primary.completed_at = now
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="submit_for_review",
            content=f"主办部门提交答复待坐席审核：{payload.public_reply}",
            previous_status=previous, current_status=ticket.status,
            remark=payload.remark, visibility="public",
        ))
        self.repository.commit()
        self.audit.log(principal, "submit_for_review", resource_type="ticket", resource_id=ticket.ticket_id,
                       details={"work_order_count": len(orders)})
        return ticket

    def review_and_resolve(self, ticket_id: str, payload: TicketResolve, principal: Principal):
        """Agent reviews the department's submitted reply and finalizes the ticket (P0-A).

        Only agent (or admin fallback) can call this. The ticket must be in
        processing with collaboration_status=awaiting_review. On approval the
        master ticket moves to resolved; the primary work order is marked
        completed. The agent may override the public reply / internal note.
        """
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied("只有坐席可以审核办结工单")
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != payload.version:
            raise VersionConflict()
        if ticket.status != "processing":
            raise BusinessError("INVALID_STATUS_TRANSITION", "只有处理中工单可以审核办结", 409,
                                {"current_status": ticket.status})
        if ticket.collaboration_status != "awaiting_review":
            raise BusinessError("NOT_AWAITING_REVIEW", "当前工单不在待审核状态", 409,
                                {"current_collaboration_status": ticket.collaboration_status})
        orders = [x for x in self.repository.list_for_ticket(ticket_id) if x.status not in {"returned", "transferred", "cancelled"}]
        primary = next((x for x in orders if x.task_type == "primary"), None)
        if not primary:
            raise BusinessError("PRIMARY_WORK_ORDER_REQUIRED", "缺少主办任务，无法审核办结", 409)
        now = datetime.now(timezone.utc)
        previous = ticket.status
        # Agent may override the resolution fields (e.g. redact internal note for public)
        ticket.status = "resolved"
        ticket.collaboration_status = "completed"
        ticket.resolution_summary = payload.resolution_summary
        ticket.resolution_measures = payload.resolution_measures
        ticket.resolution_outcome = payload.resolution_outcome
        ticket.public_reply = payload.public_reply
        ticket.internal_note = payload.internal_note
        ticket.resolved_at = now
        ticket.version += 1
        primary.completed_at = now
        primary.version += 1
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="review_resolve",
            content=f"坐席审核通过并办结：{payload.public_reply}",
            previous_status=previous, current_status="resolved",
            remark=payload.remark, visibility="public",
        ))
        self.repository.commit()
        self.audit.log(principal, "review_and_resolve", resource_type="ticket", resource_id=ticket.ticket_id,
                       details={"work_order_count": len(orders)})
        return ticket

    def return_to_department(self, ticket_id: str, version: int, remark: str,
                             return_reason: str, principal: Principal):
        """Agent returns the ticket to the primary department for supplement (P0-A).

        Only agent (or admin fallback) can call this. The ticket must be in
        processing with collaboration_status=awaiting_review. The primary work
        order is reset to processing so the department can re-submit.
        """
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied("只有坐席可以退回主办部门补充")
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.status != "processing":
            raise BusinessError("INVALID_STATUS_TRANSITION", "只有处理中工单可以退回补充", 409,
                                {"current_status": ticket.status})
        if ticket.collaboration_status != "awaiting_review":
            raise BusinessError("NOT_AWAITING_REVIEW", "当前工单不在待审核状态", 409,
                                {"current_collaboration_status": ticket.collaboration_status})
        orders = [x for x in self.repository.list_for_ticket(ticket_id) if x.status not in {"returned", "transferred", "cancelled"}]
        primary = next((x for x in orders if x.task_type == "primary"), None)
        if not primary:
            raise BusinessError("PRIMARY_WORK_ORDER_REQUIRED", "缺少主办任务，无法退回", 409)
        previous_collab = ticket.collaboration_status
        ticket.collaboration_status = "in_progress"
        ticket.version += 1
        # Reset primary work order to processing so department can re-submit
        prev_order_status = primary.status
        primary.status = "processing"
        primary.submitted_at = None
        primary.completed_at = None
        primary.result_summary = None
        primary.result_measures = None
        primary.result_outcome = None
        primary.public_content = None
        primary.internal_note = None
        primary.version += 1
        self.repository.record(primary, principal.user_id, "return_to_department", prev_order_status, return_reason)
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="return_to_department",
            content=f"坐席退回主办部门补充：{return_reason.strip()}",
            previous_status=ticket.status, current_status=ticket.status,
            remark=remark, visibility="internal",
        ))
        self.repository.commit()
        self.audit.log(principal, "return_to_department", resource_type="ticket", resource_id=ticket.ticket_id,
                       details={"previous_collaboration_status": previous_collab, "reason": return_reason})
        return ticket

    def open_dispute(self, ticket_id: str, version: int, reason: str, remark: str, principal: Principal):
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != version:
            raise VersionConflict()
        if principal.role not in {"agent", "admin", "department_staff"}:
            raise PermissionDenied("当前角色不能发起归属争议")
        ticket.collaboration_status = "disputed"
        ticket.dispute_reason = reason.strip()
        ticket.dispute_resolution = None
        ticket.version += 1
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="open_dispute",
            content=f"发起责任归属争议：{reason.strip()}", previous_status=ticket.status,
            current_status=ticket.status, remark=remark, visibility="internal",
        ))
        self.repository.commit()
        self.audit.log(principal, "open_assignment_dispute", resource_type="ticket", resource_id=ticket.ticket_id,
                       details={"reason": reason})
        return ticket

    def resolve_dispute(self, ticket_id: str, version: int, resolution: str,
                        primary_work_order_id: str | None, remark: str, principal: Principal):
        if principal.role != "admin":
            raise PermissionDenied("只有管理员可以协调责任归属争议")
        ticket = self._ticket(ticket_id, principal, lock=True)
        if ticket.version != version:
            raise VersionConflict()
        if ticket.collaboration_status != "disputed":
            raise BusinessError("NO_ACTIVE_DISPUTE", "当前主单没有待协调争议", 409)
        if primary_work_order_id:
            orders = self.repository.list_for_ticket(ticket_id)
            selected = next((x for x in orders if x.id == primary_work_order_id and x.status in ACTIVE_STATUSES), None)
            if not selected:
                raise BusinessError("INVALID_PRIMARY_WORK_ORDER", "指定的主办任务无效", 422)
            for item in orders:
                if item.task_type == "primary" and item.status in ACTIVE_STATUSES:
                    item.task_type = "support"
                    item.version += 1
            selected.task_type = "primary"
            selected.version += 1
            ticket.assigned_department_id = selected.department_id
            ticket.assigned_user_id = selected.assignee_user_id
        ticket.collaboration_status = "in_progress"
        ticket.dispute_resolution = resolution.strip()
        ticket.version += 1
        self.repository.db.add(TicketStatusHistoryModel(
            ticket_id=ticket.ticket_id, operator_user_id=principal.user_id, operation_type="resolve_dispute",
            content=f"管理员协调结论：{resolution.strip()}", previous_status=ticket.status,
            current_status=ticket.status, remark=remark, visibility="internal",
        ))
        self.repository.commit()
        self.audit.log(principal, "resolve_assignment_dispute", resource_type="ticket", resource_id=ticket.ticket_id,
                       details={"primary_work_order_id": primary_work_order_id, "resolution": resolution})
        return ticket
