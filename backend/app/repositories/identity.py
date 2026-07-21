import json
from typing import Optional

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..models import AuditLogModel, CategoryModel, DepartmentModel, UserModel
from ..logging_config import redact, request_id_context


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_username(self, username: str) -> Optional[UserModel]:
        return self.db.scalar(select(UserModel).where(UserModel.username == username))

    def get_by_oidc_subject(self, subject: str) -> Optional[UserModel]:
        return self.db.scalar(select(UserModel).where(UserModel.oidc_subject == subject))

    def get_by_directory_id(self, external_id: str) -> Optional[UserModel]:
        return self.db.scalar(select(UserModel).where(UserModel.directory_external_id == external_id))

    def get(self, user_id: int) -> Optional[UserModel]:
        return self.db.get(UserModel, user_id)

    def add(self, user: UserModel) -> UserModel:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def list_page(self, page: int, page_size: int, keyword: str | None, role: str | None,
                  is_active: bool | None, department_id: int | None, sort: str, order: str):
        statement = select(UserModel)
        if keyword:
            term = f"%{keyword.strip()}%"
            statement = statement.where(or_(UserModel.username.ilike(term), UserModel.display_name.ilike(term)))
        if role:
            statement = statement.where(UserModel.role == role)
        if is_active is not None:
            statement = statement.where(UserModel.is_active.is_(is_active))
        if department_id is not None:
            statement = statement.where(UserModel.department_id == department_id)
        total = int(self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        column = {"username": UserModel.username, "display_name": UserModel.display_name,
                  "role": UserModel.role, "created_at": UserModel.created_at}[sort]
        direction = asc if order == "asc" else desc
        items = list(self.db.scalars(statement.order_by(direction(column), UserModel.id.asc())
                                     .offset((page - 1) * page_size).limit(page_size)).all())
        return items, total

    def save(self, user: UserModel) -> UserModel:
        self.db.commit()
        self.db.refresh(user)
        return user

    def list_department_staff(self, department_id: int) -> list[UserModel]:
        return list(self.db.scalars(
            select(UserModel).where(
                UserModel.department_id == department_id,
                UserModel.role == "department_staff",
                UserModel.is_active.is_(True),
            ).order_by(UserModel.display_name, UserModel.id)
        ).all())


class DepartmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_active(self) -> list[DepartmentModel]:
        return list(self.db.scalars(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).order_by(DepartmentModel.id)).all())

    def list_all(self) -> list[DepartmentModel]:
        return list(self.db.scalars(select(DepartmentModel).order_by(DepartmentModel.id)).all())

    def get(self, department_id: int) -> Optional[DepartmentModel]:
        return self.db.get(DepartmentModel, department_id)

    def get_by_code(self, code: str) -> Optional[DepartmentModel]:
        return self.db.scalar(select(DepartmentModel).where(DepartmentModel.code == code))

    def add(self, department: DepartmentModel) -> DepartmentModel:
        self.db.add(department)
        self.db.commit()
        self.db.refresh(department)
        return department

    def save(self, department: DepartmentModel) -> DepartmentModel:
        self.db.commit()
        self.db.refresh(department)
        return department


class CategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self, include_inactive: bool = False) -> list[CategoryModel]:
        statement = select(CategoryModel)
        if not include_inactive:
            statement = statement.where(CategoryModel.is_active.is_(True))
        return list(self.db.scalars(statement.order_by(CategoryModel.level, CategoryModel.code)).all())

    def get(self, category_id: int) -> Optional[CategoryModel]:
        return self.db.get(CategoryModel, category_id)

    def get_by_code(self, code: str) -> Optional[CategoryModel]:
        return self.db.scalar(select(CategoryModel).where(CategoryModel.code == code))

    def has_active_children(self, category_id: int) -> bool:
        return bool(self.db.scalar(select(func.count()).select_from(CategoryModel).where(
            CategoryModel.parent_id == category_id, CategoryModel.is_active.is_(True)
        )))

    def add(self, category: CategoryModel) -> CategoryModel:
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def save(self, category: CategoryModel) -> CategoryModel:
        self.db.commit()
        self.db.refresh(category)
        return category


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        principal: Principal | None,
        action: str,
        outcome: str = "success",
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
        commit: bool = True,
    ) -> None:
        safe_details = redact(details or {})
        self.db.add(AuditLogModel(
            actor_user_id=principal.user_id if principal else None,
            actor_type=principal.kind if principal else "anonymous",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=json.dumps(safe_details, ensure_ascii=False) if safe_details else None,
            request_id=request_id_context.get(),
        ))
        if commit:
            self.db.commit()

    def list(self, page: int, page_size: int, action: str | None = None):
        statement = select(AuditLogModel)
        if action:
            statement = statement.where(AuditLogModel.action == action)
        total = int(self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(self.db.scalars(
            statement.order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return items, total
