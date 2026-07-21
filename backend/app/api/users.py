from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from ..schemas import ROLES, SuccessResponse, UserCreate, UserList, UserRead, UserUpdate
from ..services.admin_service import AdminService
from .dependencies import get_user_principal


router = APIRouter(prefix="/api/v1/users", tags=["users"])


def get_admin_service(db: Session = Depends(get_db)):
    return AdminService(UserRepository(db), DepartmentRepository(db), AuditRepository(db))


@router.get("", response_model=SuccessResponse[UserList])
def list_users(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100), role: str | None = None,
    is_active: bool | None = None, department_id: int | None = Query(None, gt=0),
    sort: Literal["username", "display_name", "role", "created_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    principal: Principal = Depends(get_user_principal), service: AdminService = Depends(get_admin_service),
):
    if role is not None and role not in ROLES:
        from ..errors import BusinessError
        raise BusinessError("INVALID_ROLE", "角色筛选值无效", 422)
    items, total = service.list_users(principal, page=page, page_size=page_size, keyword=keyword,
                                      role=role, is_active=is_active, department_id=department_id,
                                      sort=sort, order=order)
    return SuccessResponse(data=UserList(items=items, page=page, page_size=page_size, total=total))


@router.post("", response_model=SuccessResponse[UserRead], status_code=201)
def create_user(payload: UserCreate, principal: Principal = Depends(get_user_principal), service: AdminService = Depends(get_admin_service)):
    return SuccessResponse(data=service.create_user(payload, principal))


@router.patch("/{user_id}", response_model=SuccessResponse[UserRead])
def update_user(user_id: int, payload: UserUpdate, principal: Principal = Depends(get_user_principal), service: AdminService = Depends(get_admin_service)):
    return SuccessResponse(data=service.update_user(user_id, payload, principal))
