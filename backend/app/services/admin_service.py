from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied
from ..models import DepartmentModel, UserModel
from ..repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from ..schemas import DepartmentCreate, DepartmentUpdate, UserCreate, UserUpdate
from ..security import hash_password


class AdminService:
    def __init__(self, users: UserRepository, departments: DepartmentRepository, audit: AuditRepository):
        self.users = users
        self.departments = departments
        self.audit = audit

    @staticmethod
    def require_admin(principal: Principal):
        AuthorizationPolicy.require_roles(principal, "admin")

    def list_users(self, principal, **query):
        self.require_admin(principal)
        return self.users.list_page(**query)

    def create_user(self, payload: UserCreate, principal):
        self.require_admin(principal)
        if self.users.get_by_username(payload.username):
            raise BusinessError("USERNAME_EXISTS", "用户名已存在", 409)
        self._validate_department(payload.role, payload.department_id)
        user = self.users.add(UserModel(
            username=payload.username, password_hash=hash_password(payload.password),
            display_name=payload.display_name, role=payload.role,
            department_id=payload.department_id, is_active=payload.is_active,
        ))
        self.audit.log(principal, "create_user", resource_type="user", resource_id=str(user.id))
        return user

    def update_user(self, user_id: int, payload: UserUpdate, principal):
        self.require_admin(principal)
        user = self.users.get(user_id)
        if not user:
            raise BusinessError("USER_NOT_FOUND", "未找到用户", 404)
        if user.id == principal.user_id and payload.is_active is False:
            raise PermissionDenied("管理员不能停用当前登录账号")
        role = payload.role if payload.role is not None else user.role
        department_id = payload.department_id if "department_id" in payload.model_fields_set else user.department_id
        self._validate_department(role, department_id)
        for field in ("display_name", "role", "is_active"):
            value = getattr(payload, field)
            if value is not None:
                setattr(user, field, value)
        if "department_id" in payload.model_fields_set:
            user.department_id = payload.department_id
        if payload.password:
            user.password_hash = hash_password(payload.password)
        user = self.users.save(user)
        self.audit.log(principal, "update_user", resource_type="user", resource_id=str(user.id))
        return user

    def create_department(self, payload: DepartmentCreate, principal):
        self.require_admin(principal)
        if self.departments.get_by_code(payload.code):
            raise BusinessError("DEPARTMENT_CODE_EXISTS", "部门编码已存在", 409)
        department = self.departments.add(DepartmentModel(**payload.model_dump(), is_active=True))
        self.audit.log(principal, "create_department", resource_type="department", resource_id=str(department.id))
        return department

    def update_department(self, department_id: int, payload: DepartmentUpdate, principal):
        self.require_admin(principal)
        department = self.departments.get(department_id)
        if not department:
            raise BusinessError("DEPARTMENT_NOT_FOUND", "未找到指定部门", 404)
        for field in payload.model_fields_set:
            setattr(department, field, getattr(payload, field))
        department = self.departments.save(department)
        self.audit.log(principal, "update_department", resource_type="department", resource_id=str(department.id))
        return department

    def _validate_department(self, role, department_id):
        if role == "department_staff" and department_id is None:
            raise BusinessError("DEPARTMENT_REQUIRED", "部门人员必须归属部门", 422)
        if department_id is not None:
            department = self.departments.get(department_id)
            if not department or not department.is_active:
                raise BusinessError("INVALID_DEPARTMENT", "用户所属部门不存在或已停用", 409)
