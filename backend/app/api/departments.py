from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..repositories.identity import DepartmentRepository
from ..schemas import DepartmentRead, SuccessResponse, UserRead
from ..errors import PermissionDenied
from ..schemas import DepartmentCreate, DepartmentUpdate
from ..repositories.identity import AuditRepository, UserRepository
from ..services.admin_service import AdminService
from .dependencies import get_user_principal
from ..authorization import Principal


router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("", response_model=SuccessResponse[list[DepartmentRead]])
def list_departments(
    principal: Principal = Depends(get_user_principal),
    db: Session = Depends(get_db),
):
    repository = DepartmentRepository(db)
    return SuccessResponse(data=repository.list_all() if principal.role == "admin" else repository.list_active())


def get_admin_service(db: Session = Depends(get_db)):
    return AdminService(UserRepository(db), DepartmentRepository(db), AuditRepository(db))


@router.post("", response_model=SuccessResponse[DepartmentRead], status_code=201)
def create_department(payload: DepartmentCreate, principal: Principal = Depends(get_user_principal), service: AdminService = Depends(get_admin_service)):
    return SuccessResponse(data=service.create_department(payload, principal))


@router.patch("/{department_id}", response_model=SuccessResponse[DepartmentRead])
def update_department(department_id: int, payload: DepartmentUpdate, principal: Principal = Depends(get_user_principal), service: AdminService = Depends(get_admin_service)):
    return SuccessResponse(data=service.update_department(department_id, payload, principal))


@router.get("/{department_id}/staff", response_model=SuccessResponse[list[UserRead]])
def list_department_staff(
    department_id: int,
    principal: Principal = Depends(get_user_principal),
    db: Session = Depends(get_db),
):
    if principal.role not in {"agent", "admin"} and not (
        principal.role == "department_staff" and principal.department_id == department_id
    ):
        raise PermissionDenied("无权查看该部门责任人列表")
    department = DepartmentRepository(db).get(department_id)
    if not department or not department.is_active:
        return SuccessResponse(data=[])
    return SuccessResponse(data=UserRepository(db).list_department_staff(department_id))
