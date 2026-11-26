from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..csv_utils import iter_csv_chunks
from ..database import get_db
from ..errors import PermissionDenied
from ..repositories.identity import AuditRepository, CategoryRepository, DepartmentRepository, UserRepository
from ..repositories.postgres import PostgreSQLTicketRepository
from ..repositories.work_orders import WorkOrderRepository
from ..repositories.aftercare import AftercareRepository, NotificationRepository
from ..schemas import (
    STATUS_LABELS, SuccessResponse, TicketAccept, TicketAction, TicketAdminClose, TicketAssign,
    TicketBatchAssign, TicketBatchAssignResult, TicketContactUpdate,
    TicketCreated, TicketCreate, TicketDetail, TicketExportQuery, TicketFeedbackCreate, TicketList, TicketQuery,
    TicketRead, TicketReject, TicketResolve, TicketServiceStatus, TicketSlaAction, TicketStatusUpdate,
    TicketDisputeOpen, TicketDisputeResolve, TicketSupplementRequest, TicketSupplementSubmit,
    TicketReturnToDepartment,
    WorkOrderAction, WorkOrderAssigneeUpdate, WorkOrderCreate, WorkOrderRead, WorkOrderResult, WorkOrderTransfer,
)
from ..services.ticket_service import TicketService
from ..services.work_order_service import WorkOrderService
from ..services.aftercare_service import AftercareService
from .dependencies import (
    get_current_principal, get_user_principal, require_anon_ticket_rate_limit, require_export_rate_limit,
)


router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])


def get_service(db: Session = Depends(get_db)) -> TicketService:
    aftercare = AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))
    return TicketService(
        PostgreSQLTicketRepository(db), DepartmentRepository(db), AuditRepository(db),
        UserRepository(db), CategoryRepository(db), WorkOrderRepository(db),
        aftercare,
    )


def get_aftercare_service(db: Session = Depends(get_db)) -> AftercareService:
    return AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))


def get_work_order_service(db: Session = Depends(get_db)) -> WorkOrderService:
    return WorkOrderService(
        WorkOrderRepository(db), DepartmentRepository(db), UserRepository(db), AuditRepository(db),
        get_aftercare_service(db),
    )


@router.post("", response_model=SuccessResponse[TicketCreated], status_code=status.HTTP_201_CREATED, response_model_exclude_none=True)
def create_ticket(
    payload: TicketCreate,
    principal: Principal = Depends(get_current_principal),
    _: None = Depends(require_anon_ticket_rate_limit),
    service: TicketService = Depends(get_service),
):
    if principal.kind == "service" and not (payload.creator_reference or "").strip():
        raise PermissionDenied("服务身份创建工单需要会话引用")
    result = service.create(payload, principal)
    return SuccessResponse(data=TicketCreated(ticket=service._present(result.ticket, principal), idempotent_replay=result.replayed))


@router.post("/batch-assign", response_model=SuccessResponse[TicketBatchAssignResult], response_model_exclude_none=True)
def batch_assign(
    payload: TicketBatchAssign,
    principal: Principal = Depends(get_user_principal),
    service: TicketService = Depends(get_service),
):
    return SuccessResponse(data=service.batch_assign(payload, principal))


@router.get("/export")
def export_tickets(
    query: Annotated[TicketExportQuery, Query()],
    principal: Principal = Depends(get_user_principal),
    _: None = Depends(require_export_rate_limit),
    service: TicketService = Depends(get_service),
):
    items = service.export_tickets(query, principal, limit=query.limit)
    headers = [
        "工单号", "诉求类型", "状态", "优先级", "区域位置", "诉求内容",
        "承办部门", "承办人", "创建人", "SLA状态", "是否超时",
        "答复概要", "办理结果", "公开答复", "内部备注", "创建时间", "更新时间",
    ]
    rows = [
        [
            item.ticket_id,
            item.request_type,
            item.status_label or STATUS_LABELS.get(item.status, item.status),
            item.priority,
            item.location,
            item.description,
            item.department_name or "",
            item.assignee_name or "",
            item.creator_name or "",
            item.sla_state,
            "是" if item.is_overdue else "否",
            item.resolution_summary or "",
            item.resolution_outcome or "",
            item.public_reply or "",
            item.internal_note or "",
            item.created_at.isoformat() if item.created_at else "",
            item.updated_at.isoformat() if item.updated_at else "",
        ]
        for item in items
    ]
    filename = f"tickets-export-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.csv"
    return StreamingResponse(
        iter_csv_chunks(headers, rows, chunk_size=200),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{ticket_id}", response_model=SuccessResponse[TicketDetail | TicketServiceStatus], response_model_exclude_none=True)
def get_ticket(
    ticket_id: str,
    x_creator_reference: str | None = Header(default=None),
    principal: Principal = Depends(get_current_principal),
    service: TicketService = Depends(get_service),
):
    result = service.detail(ticket_id, principal, x_creator_reference)
    if principal.kind == "service":
        return SuccessResponse(data=TicketServiceStatus(
            ticket_id=result.ticket_id, request_type=result.request_type, status=result.status,
            status_label=result.status_label or result.status, created_at=result.created_at,
        ))
    return SuccessResponse(data=result)


@router.get("", response_model=SuccessResponse[TicketList], response_model_exclude_none=True)
def list_tickets(
    query: Annotated[TicketQuery, Query()],
    principal: Principal = Depends(get_user_principal),
    service: TicketService = Depends(get_service),
):
    return SuccessResponse(data=service.list_tickets(query, principal))


@router.post("/{ticket_id}/accept", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def accept(ticket_id: str, payload: TicketAccept, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.accept(ticket_id, payload.version, payload.remark, principal, payload.category_id, payload.priority))


@router.post("/{ticket_id}/assign", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def assign(ticket_id: str, payload: TicketAssign, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.assign(ticket_id, payload.version, payload.remark, payload.department_id, payload.assigned_user_id, principal))


@router.post("/{ticket_id}/supplement-request", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def request_supplement(ticket_id: str, payload: TicketSupplementRequest, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.request_supplement(
        ticket_id, payload.version, payload.remark, payload.supplement_reason, principal,
    ))


@router.post("/{ticket_id}/supplement", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def submit_supplement(ticket_id: str, payload: TicketSupplementSubmit, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.submit_supplement(
        ticket_id, payload.version, payload.remark, payload.supplement_content, principal,
    ))


@router.get("/{ticket_id}/work-orders", response_model=SuccessResponse[list[WorkOrderRead]], response_model_exclude_none=True)
def list_work_orders(ticket_id: str, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.list(ticket_id, principal))


@router.post("/{ticket_id}/work-orders", response_model=SuccessResponse[WorkOrderRead], status_code=status.HTTP_201_CREATED, response_model_exclude_none=True)
def create_work_order(ticket_id: str, payload: WorkOrderCreate, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service), aftercare: AftercareService = Depends(get_aftercare_service)):
    result = service.create(
        ticket_id, payload.version, payload.task_type, payload.department_id,
        payload.assignee_user_id, payload.instructions, principal,
    )
    if payload.task_type == "primary":
        aftercare.on_ticket_event("ticket_assigned", service.repository.ticket(ticket_id), principal)
    return SuccessResponse(data=result)


@router.post("/{ticket_id}/work-orders/{work_order_id}/assign", response_model=SuccessResponse[WorkOrderRead], response_model_exclude_none=True)
def assign_work_order(ticket_id: str, work_order_id: str, payload: WorkOrderAssigneeUpdate, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.assign(work_order_id, payload.version, payload.assignee_user_id, payload.remark, principal, ticket_id=ticket_id))


@router.post("/{ticket_id}/work-orders/{work_order_id}/start", response_model=SuccessResponse[WorkOrderRead], response_model_exclude_none=True)
def start_work_order(ticket_id: str, work_order_id: str, payload: WorkOrderAction, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.start(work_order_id, payload.version, payload.remark, principal, ticket_id=ticket_id))


@router.post("/{ticket_id}/work-orders/{work_order_id}/return", response_model=SuccessResponse[WorkOrderRead], response_model_exclude_none=True)
def return_work_order(ticket_id: str, work_order_id: str, payload: WorkOrderAction, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.return_to_agent(work_order_id, payload.version, payload.remark, principal, ticket_id=ticket_id))


@router.post("/{ticket_id}/work-orders/{work_order_id}/transfer", response_model=SuccessResponse[WorkOrderRead], response_model_exclude_none=True)
def transfer_work_order(ticket_id: str, work_order_id: str, payload: WorkOrderTransfer, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.transfer(
        work_order_id, payload.version, payload.target_department_id,
        payload.assignee_user_id, payload.remark, principal, ticket_id=ticket_id,
    ))


@router.post("/{ticket_id}/work-orders/{work_order_id}/submit", response_model=SuccessResponse[WorkOrderRead], response_model_exclude_none=True)
def submit_work_order(ticket_id: str, work_order_id: str, payload: WorkOrderResult, principal: Principal = Depends(get_user_principal), service: WorkOrderService = Depends(get_work_order_service)):
    return SuccessResponse(data=service.submit(
        work_order_id, payload.version, payload.remark, payload.result_summary,
        payload.result_measures, payload.result_outcome, payload.public_content,
        payload.internal_note, principal, ticket_id=ticket_id,
    ))


@router.post("/{ticket_id}/summary", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def summarize_ticket(ticket_id: str, payload: TicketResolve, principal: Principal = Depends(get_user_principal), work_orders: WorkOrderService = Depends(get_work_order_service), tickets: TicketService = Depends(get_service)):
    """Primary department submits final reply for agent review (P0-A).

    No longer resolves the ticket directly — the ticket stays in processing
    with collaboration_status=awaiting_review until an agent calls
    /review-resolve.
    """
    ticket = work_orders.summarize(ticket_id, payload, principal)
    return SuccessResponse(data=tickets._present(ticket, principal))


@router.post("/{ticket_id}/review-resolve", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def review_and_resolve(ticket_id: str, payload: TicketResolve, principal: Principal = Depends(get_user_principal), work_orders: WorkOrderService = Depends(get_work_order_service), tickets: TicketService = Depends(get_service), aftercare: AftercareService = Depends(get_aftercare_service)):
    """Agent reviews the department reply and finalizes the ticket (P0-A)."""
    ticket = work_orders.review_and_resolve(ticket_id, payload, principal)
    aftercare.on_ticket_event("resolved", ticket, principal)
    return SuccessResponse(data=tickets._present(ticket, principal))


@router.post("/{ticket_id}/return-to-department", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def return_to_department(ticket_id: str, payload: TicketReturnToDepartment, principal: Principal = Depends(get_user_principal), work_orders: WorkOrderService = Depends(get_work_order_service), tickets: TicketService = Depends(get_service)):
    """Agent returns the ticket to the primary department for supplement (P0-A)."""
    ticket = work_orders.return_to_department(ticket_id, payload.version, payload.remark, payload.return_reason, principal)
    return SuccessResponse(data=tickets._present(ticket, principal))


@router.post("/{ticket_id}/dispute", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def open_dispute(ticket_id: str, payload: TicketDisputeOpen, principal: Principal = Depends(get_user_principal), work_orders: WorkOrderService = Depends(get_work_order_service), tickets: TicketService = Depends(get_service)):
    ticket = work_orders.open_dispute(ticket_id, payload.version, payload.dispute_reason, payload.remark, principal)
    return SuccessResponse(data=tickets._present(ticket, principal))


@router.post("/{ticket_id}/dispute/resolve", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def resolve_dispute(ticket_id: str, payload: TicketDisputeResolve, principal: Principal = Depends(get_user_principal), work_orders: WorkOrderService = Depends(get_work_order_service), tickets: TicketService = Depends(get_service)):
    ticket = work_orders.resolve_dispute(
        ticket_id, payload.version, payload.resolution, payload.primary_work_order_id, payload.remark, principal,
    )
    return SuccessResponse(data=tickets._present(ticket, principal))


@router.post("/{ticket_id}/process", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def process(ticket_id: str, payload: TicketAction, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.process(ticket_id, payload.version, payload.remark, principal))


@router.post("/{ticket_id}/note", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def add_note(ticket_id: str, payload: TicketAction, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.add_note(ticket_id, payload.version, payload.remark, principal))


@router.post("/{ticket_id}/close", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def close(ticket_id: str, payload: TicketAdminClose, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.close(ticket_id, payload.version, payload.remark, payload.override_reason, principal))


@router.post("/{ticket_id}/reject", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def reject(ticket_id: str, payload: TicketReject, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.reject(
        ticket_id, payload.version, payload.remark, payload.reason_code,
        payload.rejection_detail, payload.suggested_channel, payload.needs_supplement, principal,
    ))


@router.post("/{ticket_id}/feedback", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def submit_feedback(ticket_id: str, payload: TicketFeedbackCreate, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.submit_feedback(
        ticket_id, payload.version, payload.rating, payload.comment, principal,
    ))


@router.patch("/{ticket_id}/status", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def update_ticket_status(ticket_id: str, payload: TicketStatusUpdate, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.update_status(ticket_id, payload.status, payload.remark, payload.version, principal))


@router.patch("/{ticket_id}/contact", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def update_contact(ticket_id: str, payload: TicketContactUpdate, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.update_contact(ticket_id, payload.version, payload.remark, payload.contact, principal))


@router.post("/{ticket_id}/sla/pause", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def pause_sla(ticket_id: str, payload: TicketSlaAction, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.pause_sla(ticket_id, payload.version, payload.remark, payload.reason, principal))


@router.post("/{ticket_id}/sla/resume", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def resume_sla(ticket_id: str, payload: TicketAction, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.resume_sla(ticket_id, payload.version, payload.remark, principal))


@router.post("/{ticket_id}/remind", response_model=SuccessResponse[TicketRead], response_model_exclude_none=True)
def remind(ticket_id: str, payload: TicketAction, principal: Principal = Depends(get_user_principal), service: TicketService = Depends(get_service)):
    return SuccessResponse(data=service.remind(ticket_id, payload.version, payload.remark, principal))


@router.post("/bind-anonymous", response_model=SuccessResponse[dict], status_code=200)
def bind_anonymous_tickets(payload: dict, principal: Principal = Depends(get_user_principal), db: Session = Depends(get_db)):
    """Bind anonymous tickets created by sender_id to the logged-in citizen.

    SECURITY BOUNDARY (not production-grade account recovery):
    - Ownership proof is possession of the browser-local `sender_id` (SHA-256 hashed
      at create time as `anonymous_creator_key`). Anyone who obtains that id can claim
      unbound tickets for it (XSS, shared device, log leak).
    - Soft guards only: require citizen role; allow `web-anon-*` or the caller's own
      `web-user-{id}`; reject other accounts' `web-user-*` references.
    - Do not advertise this as secure cross-device account recovery.
    """
    from ..authorization import AuthorizationPolicy
    from ..errors import BusinessError
    from ..models import TicketModel
    from ..security import anonymous_creator_key
    from sqlalchemy import update
    AuthorizationPolicy.require_roles(principal, "citizen")
    sender_id = payload.get("sender_id", "")
    if not isinstance(sender_id, str) or not sender_id.strip():
        raise BusinessError("INVALID_REQUEST", "缺少 sender_id", 422)
    sender_id = sender_id.strip()
    if sender_id.startswith("web-user-"):
        if sender_id != f"web-user-{principal.user_id}":
            raise PermissionDenied("无权绑定其他账号的会话工单")
    elif not sender_id.startswith("web-anon-"):
        raise BusinessError("INVALID_REQUEST", "不支持的 sender_id 格式", 422)
    anon_key = anonymous_creator_key(sender_id)
    result = db.execute(
        update(TicketModel)
        .where(TicketModel.anonymous_creator_key == anon_key, TicketModel.creator_user_id.is_(None))
        .values(creator_user_id=principal.user_id)
    )
    db.commit()
    return SuccessResponse(data={"bound_count": result.rowcount})
