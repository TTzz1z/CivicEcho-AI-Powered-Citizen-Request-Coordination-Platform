from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..repositories.ai import AiRepository
from ..repositories.identity import AuditRepository
from ..schemas import AiAnalyzeRequest, AiReviewRequest, AiSuggestionRead, HotspotRead, PreReviewRequest, PreReviewResult, SuccessResponse
from ..services.ai_service import AiService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1/ai", tags=["ai-advisory"])


def get_service(db: Session = Depends(get_db)):
    return AiService(AiRepository(db), AuditRepository(db), get_settings())


@router.post("/tickets/{ticket_id}/analyze", response_model=SuccessResponse[list[AiSuggestionRead]])
def analyze(ticket_id: str, payload: AiAnalyzeRequest, principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    return SuccessResponse(data=service.analyze(
        ticket_id, payload.suggestion_types, principal, capability=payload.capability,
    ))


@router.get("/tickets/{ticket_id}/suggestions", response_model=SuccessResponse[list[AiSuggestionRead]])
def list_suggestions(ticket_id: str, principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    return SuccessResponse(data=service.list(ticket_id, principal))


@router.post("/suggestions/{suggestion_id}/review", response_model=SuccessResponse[AiSuggestionRead])
def review(suggestion_id: str, payload: AiReviewRequest, principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    return SuccessResponse(data=service.review(
        suggestion_id, payload.decision, payload.comment, principal,
        edited_content=payload.edited_content,
    ))


@router.get("/hotspots", response_model=SuccessResponse[list[HotspotRead]])
def hotspots(days: int = Query(30, ge=1, le=365), principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    return SuccessResponse(data=service.hotspots(principal, days))


@router.post("/pre-review", response_model=SuccessResponse[PreReviewResult])
def pre_review(payload: PreReviewRequest, principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    return SuccessResponse(data=service.pre_review(payload, principal))


@router.post("/tickets/{ticket_id}/case-advice")
def case_advice(ticket_id: str, principal: Principal = Depends(get_user_principal), service: AiService = Depends(get_service)):
    """Generate AI case handling advice for department staff (advisory only)."""
    return SuccessResponse(data=service.case_advice(ticket_id, principal))
