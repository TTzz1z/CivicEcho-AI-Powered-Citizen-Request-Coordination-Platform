from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from ..repositories.integrations import IntegrationRepository
from ..schemas import IntegrationStatusRead, OidcExchangeRequest, SmsDispatchRequest, SuccessResponse, TicketSyncRequest, TokenResponse
from ..services.integration_service import IntegrationService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1", tags=["integrations"])


def get_service(db: Session = Depends(get_db)):
    return IntegrationService(IntegrationRepository(db), AuditRepository(db), UserRepository(db), DepartmentRepository(db), get_settings())


@router.get("/auth/oidc/config")
def oidc_config(service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.oidc_config())


@router.post("/auth/oidc/exchange", response_model=SuccessResponse[TokenResponse])
def oidc_exchange(payload: OidcExchangeRequest, service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.oidc_exchange(payload.code, payload.redirect_uri))


@router.get("/integrations/status", response_model=SuccessResponse[list[IntegrationStatusRead]])
def statuses(principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.statuses(principal))


@router.post("/integrations/directory/sync")
def sync_directory(principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.sync_directory(principal))


@router.post("/integrations/tickets/{ticket_id}/sync")
def sync_ticket(ticket_id: str, payload: TicketSyncRequest, principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.sync_ticket(ticket_id, payload.force, principal))


@router.get("/integrations/map/geocode")
def geocode(address: str = Query(min_length=2, max_length=500), principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.proxy_lookup("map", address, principal))


@router.get("/integrations/divisions")
def divisions(parent_code: str = Query(min_length=2, max_length=32), principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.proxy_lookup("division", parent_code, principal))


@router.get("/integrations/metrics")
def metrics(principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.metrics(principal))


@router.post("/integrations/sms/send")
def send_sms(payload: SmsDispatchRequest, principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.send_sms(payload.phone, payload.template_code, payload.parameters, principal))


@router.post("/integrations/{kind}/probe")
def probe(kind: str, principal: Principal = Depends(get_user_principal), service: IntegrationService = Depends(get_service)):
    return SuccessResponse(data=service.probe_observability(kind, principal))
