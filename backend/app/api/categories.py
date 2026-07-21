from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..repositories.identity import AuditRepository, CategoryRepository, DepartmentRepository
from ..schemas import CategoryCreate, CategoryRead, CategoryUpdate, SuccessResponse
from ..services.category_service import CategoryService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


def get_service(db: Session = Depends(get_db)):
    return CategoryService(CategoryRepository(db), DepartmentRepository(db), AuditRepository(db))


@router.get("", response_model=SuccessResponse[list[CategoryRead]])
def list_categories(principal: Principal = Depends(get_user_principal), service: CategoryService = Depends(get_service)):
    return SuccessResponse(data=service.list(principal))


@router.post("", response_model=SuccessResponse[CategoryRead], status_code=201)
def create_category(payload: CategoryCreate, principal: Principal = Depends(get_user_principal), service: CategoryService = Depends(get_service)):
    return SuccessResponse(data=service.create(payload, principal))


@router.patch("/{category_id}", response_model=SuccessResponse[CategoryRead])
def update_category(category_id: int, payload: CategoryUpdate, principal: Principal = Depends(get_user_principal), service: CategoryService = Depends(get_service)):
    return SuccessResponse(data=service.update(category_id, payload, principal))
