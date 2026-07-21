from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..repositories.analytics import AnalyticsRepository
from ..repositories.identity import AuditRepository, CategoryRepository, DepartmentRepository, UserRepository
from ..repositories.postgres import PostgreSQLTicketRepository
from ..schemas import AuditLogList, DashboardData, SuccessResponse
from ..services.analytics_service import AnalyticsService
from ..services.ticket_service import TicketService
from .dependencies import get_user_principal

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
