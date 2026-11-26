from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..csv_utils import iter_csv_chunks
from ..database import get_db
from ..repositories.analytics import AnalyticsRepository
from ..repositories.identity import AuditRepository, CategoryRepository, DepartmentRepository, UserRepository
from ..repositories.postgres import PostgreSQLTicketRepository
from ..schemas import AuditLogList, DashboardData, SuccessResponse
from ..services.analytics_service import AnalyticsService
from ..services.ticket_service import TicketService
from .dependencies import get_user_principal, require_export_rate_limit

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def get_service(db: Session = Depends(get_db)):
    tickets = TicketService(PostgreSQLTicketRepository(db), DepartmentRepository(db), AuditRepository(db), UserRepository(db), CategoryRepository(db))
    return AnalyticsService(AnalyticsRepository(db), AuditRepository(db), tickets)


@router.get("/dashboard", response_model=SuccessResponse[DashboardData])
def dashboard(principal: Principal = Depends(get_user_principal), service: AnalyticsService = Depends(get_service)):
    return SuccessResponse(data=service.dashboard(principal))


@router.get("/audit-logs", response_model=SuccessResponse[AuditLogList])
def audit_logs(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), action: str | None = None,
    principal: Principal = Depends(get_user_principal), service: AnalyticsService = Depends(get_service),
):
    return SuccessResponse(data=service.audit_logs(principal, page, page_size, action))


@router.get("/audit-logs/export")
def export_audit_logs(
    action: str | None = None,
    outcome: str | None = None,
    q: str | None = None,
    query: str | None = None,
    limit: int = Query(default=5000, ge=1, le=10000),
    principal: Principal = Depends(get_user_principal),
    _: None = Depends(require_export_rate_limit),
    service: AnalyticsService = Depends(get_service),
):
    items = service.export_audit_logs(
        principal,
        action=action,
        outcome=outcome,
        q=q or query,
        limit=limit,
    )
    headers = [
        "日志ID", "操作类型", "结果", "操作者ID", "操作者类型",
        "资源类型", "资源ID", "请求ID", "详情", "创建时间",
    ]
    rows = [
        [
            item.id,
            item.action,
            item.outcome,
            item.actor_user_id if item.actor_user_id is not None else "",
            item.actor_type,
            item.resource_type or "",
            item.resource_id or "",
            item.request_id or "",
            item.details or "",
            item.created_at.isoformat() if item.created_at else "",
        ]
        for item in items
    ]
    filename = f"audit-logs-export-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.csv"
    return StreamingResponse(
        iter_csv_chunks(headers, rows, chunk_size=200),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
