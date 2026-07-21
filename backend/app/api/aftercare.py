from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..repositories.aftercare import AftercareRepository, NotificationRepository
from ..repositories.identity import AuditRepository
from ..schemas import (
    AppealCreate, AppealList, AppealRead, AppealReview, FollowUpTaskList,
    FollowUpTaskRead, PhoneFollowUpCreate, SuccessResponse,
)
from ..services.aftercare_service import AftercareService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1", tags=["aftercare"])


def get_service(db: Session = Depends(get_db)) -> AftercareService:
    return AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))


@router.get("/follow-ups", response_model=SuccessResponse[FollowUpTaskList], response_model_exclude_none=True)
def list_follow_ups(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(get_user_principal), service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.list_follow_ups(principal, page, page_size, status_filter))


@router.post("/follow-ups/{task_id}/phone-record", response_model=SuccessResponse[FollowUpTaskRead], response_model_exclude_none=True)
def record_phone_follow_up(
    task_id: str, payload: PhoneFollowUpCreate, principal: Principal = Depends(get_user_principal),
    service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.record_phone_follow_up(
        task_id, payload.ticket_version, payload.contact_result, payload.satisfaction,
        payload.outcome, payload.notes, principal,
    ))


@router.get("/appeals", response_model=SuccessResponse[AppealList], response_model_exclude_none=True)
def list_appeals(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(get_user_principal), service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.list_appeals(principal, page, page_size, status_filter))


@router.post("/tickets/{ticket_id}/appeals", response_model=SuccessResponse[AppealRead], status_code=status.HTTP_201_CREATED, response_model_exclude_none=True)
def create_appeal(
    ticket_id: str, payload: AppealCreate, principal: Principal = Depends(get_user_principal),
    service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.create_appeal(
        ticket_id, payload.reason, payload.desired_resolution, principal,
    ))


@router.post("/appeals/{appeal_id}/review", response_model=SuccessResponse[AppealRead], response_model_exclude_none=True)
def review_appeal(
    appeal_id: str, payload: AppealReview, principal: Principal = Depends(get_user_principal),
    service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.review_appeal(
        appeal_id, payload.decision, payload.review_comment,
        payload.reprocess_instructions, principal,
    ))

