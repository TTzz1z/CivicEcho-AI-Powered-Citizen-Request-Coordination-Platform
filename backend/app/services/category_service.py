from ..authorization import AuthorizationPolicy
from ..errors import BusinessError
from ..models import CategoryModel
from ..schemas import CategoryCreate, CategoryRead, CategoryUpdate


class CategoryService:
    def __init__(self, categories, departments, audit):
        self.categories = categories
        self.departments = departments
        self.audit = audit

    @staticmethod
    def _present(category: CategoryModel) -> CategoryRead:
        return CategoryRead.model_validate(category).model_copy(update={
            "default_department_name": category.default_department.name if category.default_department else None,
        })

    def list(self, principal):
        include_inactive = principal.role == "admin"
        return [self._present(item) for item in self.categories.list(include_inactive)]

    def _validate_parent(self, parent_id, category_id=None):
        if parent_id is None:
            return 1
        if parent_id == category_id:
            raise BusinessError("INVALID_CATEGORY_PARENT", "分类不能以自身为上级", 422)
        parent = self.categories.get(parent_id)
        if not parent:
            raise BusinessError("CATEGORY_PARENT_NOT_FOUND", "未找到上级分类", 404)
        if not parent.is_active:
            raise BusinessError("CATEGORY_PARENT_INACTIVE", "停用分类不能作为上级", 409)
        if parent.level >= 3:
            raise BusinessError("CATEGORY_LEVEL_EXCEEDED", "分类最多支持三级", 422)
        return parent.level + 1

    def _validate_department(self, department_id):
        if department_id is None:
            return
        department = self.departments.get(department_id)
        if not department or not department.is_active:
            raise BusinessError("INVALID_DEPARTMENT", "默认责任部门不存在或已停用", 409)

    def create(self, payload: CategoryCreate, principal):
        AuthorizationPolicy.require_roles(principal, "admin")
        if self.categories.get_by_code(payload.code):
            raise BusinessError("CATEGORY_CODE_EXISTS", "分类编码已存在", 409)
        level = self._validate_parent(payload.parent_id)
        self._validate_department(payload.default_department_id)
        category = self.categories.add(CategoryModel(**payload.model_dump(), level=level, is_active=True))
        self.audit.log(principal, "create_category", resource_type="category", resource_id=str(category.id),
                       details={"code": category.code, "level": category.level})
        return self._present(category)

    def update(self, category_id: int, payload: CategoryUpdate, principal):
        AuthorizationPolicy.require_roles(principal, "admin")
        category = self.categories.get(category_id)
        if not category:
            raise BusinessError("CATEGORY_NOT_FOUND", "未找到分类", 404)
        parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else category.parent_id
        level = self._validate_parent(parent_id, category_id)
        if level > category.level and self.categories.has_active_children(category.id):
            raise BusinessError("CATEGORY_HAS_CHILDREN", "存在启用子分类时不能下移层级", 409)
        department_id = payload.default_department_id if "default_department_id" in payload.model_fields_set else category.default_department_id
        self._validate_department(department_id)
        if payload.is_active is False and self.categories.has_active_children(category.id):
            raise BusinessError("CATEGORY_HAS_ACTIVE_CHILDREN", "请先停用子分类", 409)
        for field in payload.model_fields_set:
            setattr(category, field, getattr(payload, field))
        category.level = level
        category = self.categories.save(category)
        self.audit.log(principal, "update_category", resource_type="category", resource_id=str(category.id),
                       details={"fields": sorted(payload.model_fields_set), "active": category.is_active})
        return self._present(category)
