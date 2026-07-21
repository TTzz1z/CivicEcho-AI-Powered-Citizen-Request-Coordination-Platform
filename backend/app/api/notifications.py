from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..repositories.aftercare import AftercareRepository, NotificationRepository
from ..repositories.identity import AuditRepository
from ..schemas import NotificationChannelRead, NotificationList, NotificationRead, SuccessResponse
from ..services.aftercare_service import AftercareService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def get_service(db: Session = Depends(get_db)) -> AftercareService:
    return AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))


@router.get("", response_model=SuccessResponse[NotificationList], response_model_exclude_none=True)
def list_notifications(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False, principal: Principal = Depends(get_user_principal),
    service: AftercareService = Depends(get_service),
):
    return SuccessResponse(data=service.list_notifications(principal, page, page_size, unread_only))


@router.post("/{notification_id}/read", response_model=SuccessResponse[NotificationRead], response_model_exclude_none=True)
def read_notification(notification_id: str, principal: Principal = Depends(get_user_principal),
                      service: AftercareService = Depends(get_service)):
    return SuccessResponse(data=service.read_notification(notification_id, principal))


@router.post("/read-all", response_model=SuccessResponse[dict])
def read_all(principal: Principal = Depends(get_user_principal), service: AftercareService = Depends(get_service)):
    return SuccessResponse(data={"read_count": service.read_all_notifications(principal)})


@router.get("/channels", response_model=SuccessResponse[list[NotificationChannelRead]])
def channels(_: Principal = Depends(get_user_principal)):
    return SuccessResponse(data=[
        NotificationChannelRead(channel="in_app", label="站内通知", enabled=True, phase="P1"),
        NotificationChannelRead(channel="sms", label="短信", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="wechat", label="微信公众号/小程序", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="email", label="邮件", enabled=False, phase="reserved"),
        NotificationChannelRead(channel="government_message", label="政务消息中心", enabled=False, phase="reserved"),
    ])

