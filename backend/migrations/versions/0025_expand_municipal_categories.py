"""Expand municipal appeal categories under CSGL for demo coverage.

Revision ID: 0025
Revises: 0024

Idempotent upserts by code so already-deployed DBs that ran 0005 still pick up
new municipal leaves (road/water/power/sanitation/greening) without relying on
rewriting historical migration 0005.
"""
from alembic import op


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


# Level-2 under CSGL (城市管理)
L2_CATEGORIES = (
    # code, name, accept_sla, resolve_sla
    ("CSGL-GS", "供水排水", 120, 2880),
    ("CSGL-HW", "市容环卫", 120, 2880),
    ("CSGL-YL", "园林绿化", 120, 4320),
)

# Level-3 leaves: code, name, parent_code, department_code, accept_sla, resolve_sla
L3_CATEGORIES = (
    # 公共设施（保留路灯，不在此 upsert；由 0005 创建）
    ("CSGL-GGSS-DL", "道路破损", "CSGL-GGSS", "urban-management", 120, 2880),
    ("CSGL-GGSS-JG", "井盖缺损", "CSGL-GGSS", "urban-management", 60, 1440),
    ("CSGL-GGSS-GD", "供电故障", "CSGL-GGSS", "general-intake", 60, 1440),
    # 供水排水
    ("CSGL-GS-TS", "供水停水", "CSGL-GS", "general-intake", 60, 1440),
    ("CSGL-GS-JS", "排水积水", "CSGL-GS", "urban-management", 60, 1440),
    # 市容环卫
    ("CSGL-HW-LJ", "垃圾清运", "CSGL-HW", "urban-management", 120, 2880),
    ("CSGL-HW-ZW", "占道堆物", "CSGL-HW", "urban-management", 120, 2880),
    # 园林绿化
    ("CSGL-YL-LH", "绿化养护", "CSGL-YL", "urban-management", 120, 4320),
    ("CSGL-YL-SM", "树木倾倒", "CSGL-YL", "urban-management", 60, 1440),
)

# Also refresh existing LD default binding (urban-management) without changing code/name.
EXISTING_L3_REFRESH = (
    ("CSGL-GGSS-LD", "路灯故障", "CSGL-GGSS", "urban-management", 60, 1440),
)


def _upsert_l2(code: str, name: str, accept_sla: int, resolve_sla: int) -> None:
    op.execute(
        f"""
        INSERT INTO categories (code, name, parent_id, level, accept_sla_minutes, resolve_sla_minutes)
        SELECT '{code}', '{name}', id, 2, {accept_sla}, {resolve_sla}
        FROM categories WHERE code = 'CSGL'
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            accept_sla_minutes = EXCLUDED.accept_sla_minutes,
            resolve_sla_minutes = EXCLUDED.resolve_sla_minutes,
            updated_at = NOW()
        """
    )


def _upsert_l3(
    code: str,
    name: str,
    parent_code: str,
    department_code: str,
    accept_sla: int,
    resolve_sla: int,
) -> None:
    op.execute(
        f"""
        INSERT INTO categories (
            code, name, parent_id, level, default_department_id,
            accept_sla_minutes, resolve_sla_minutes
        )
        SELECT '{code}', '{name}', c.id, 3, d.id, {accept_sla}, {resolve_sla}
        FROM categories c
        CROSS JOIN departments d
        WHERE c.code = '{parent_code}' AND d.code = '{department_code}'
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            default_department_id = EXCLUDED.default_department_id,
            accept_sla_minutes = EXCLUDED.accept_sla_minutes,
            resolve_sla_minutes = EXCLUDED.resolve_sla_minutes,
            is_active = TRUE,
            updated_at = NOW()
        """
    )


def upgrade() -> None:
    for code, name, accept_sla, resolve_sla in L2_CATEGORIES:
        _upsert_l2(code, name, accept_sla, resolve_sla)

    for row in (*EXISTING_L3_REFRESH, *L3_CATEGORIES):
        _upsert_l3(*row)


def downgrade() -> None:
    # Delete leaves first (parent_id ON DELETE RESTRICT).
    leaf_codes = ", ".join(f"'{c[0]}'" for c in L3_CATEGORIES)
    op.execute(f"DELETE FROM categories WHERE code IN ({leaf_codes})")
    l2_codes = ", ".join(f"'{c[0]}'" for c in L2_CATEGORIES)
    op.execute(f"DELETE FROM categories WHERE code IN ({l2_codes})")
