"""phase 2 categories, confirmed priority and SLA

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("categories.id", ondelete="RESTRICT")),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("default_department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("accept_sla_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("resolve_sla_minutes", sa.Integer(), nullable=False, server_default="4320"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_categories_level"),
        sa.CheckConstraint("accept_sla_minutes > 0", name="ck_categories_accept_sla"),
        sa.CheckConstraint("resolve_sla_minutes > 0", name="ck_categories_resolve_sla"),
        sa.UniqueConstraint("code", name="uq_categories_code"),
        sa.UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
    )
    op.create_index("ix_categories_parent_active", "categories", ["parent_id", "is_active"])
    op.execute("INSERT INTO categories (code,name,parent_id,level,accept_sla_minutes,resolve_sla_minutes) VALUES ('CSGL','城市管理',NULL,1,120,4320)")
    op.execute("INSERT INTO categories (code,name,parent_id,level,accept_sla_minutes,resolve_sla_minutes) SELECT 'CSGL-GGSS','公共设施',id,2,120,2880 FROM categories WHERE code='CSGL'")
    op.execute("""
        INSERT INTO categories (code,name,parent_id,level,default_department_id,accept_sla_minutes,resolve_sla_minutes)
        SELECT 'CSGL-GGSS-LD','路灯故障',c.id,3,d.id,60,1440
        FROM categories c CROSS JOIN departments d
        WHERE c.code='CSGL-GGSS' AND d.code='urban-management'
    """)

    op.add_column("tickets", sa.Column("category_id", sa.BigInteger()))
    op.add_column("tickets", sa.Column("requested_priority", sa.String(16)))
    op.add_column("tickets", sa.Column("priority_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("priority_confirmed_by", sa.BigInteger()))
    op.add_column("tickets", sa.Column("accept_due_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("resolve_due_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("sla_paused_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("sla_pause_reason", sa.String(500)))
    op.add_column("tickets", sa.Column("total_paused_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tickets", sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_tickets_category", "tickets", "categories", ["category_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tickets_priority_confirmer", "tickets", "users", ["priority_confirmed_by"], ["id"], ondelete="SET NULL")

    # Preserve all old rows while translating the former low/normal/high/urgent scale.
    op.drop_constraint("ck_tickets_priority", "tickets", type_="check")
    op.execute("UPDATE tickets SET requested_priority = priority")
    op.execute("UPDATE tickets SET priority = CASE priority WHEN 'high' THEN 'expedited' WHEN 'urgent' THEN 'urgent' ELSE 'normal' END")
    op.create_check_constraint("ck_tickets_priority", "tickets", "priority IN ('normal','expedited','urgent','major')")
    op.create_check_constraint("ck_tickets_requested_priority", "tickets", "requested_priority IS NULL OR requested_priority IN ('low','normal','high','urgent','major','expedited')")

    # Legacy tickets use stable fallback SLAs; classification remains nullable by design.
    op.execute("UPDATE tickets SET accept_due_at = created_at + INTERVAL '2 hours' WHERE accept_due_at IS NULL")
    op.execute("UPDATE tickets SET resolve_due_at = created_at + INTERVAL '3 days' WHERE resolve_due_at IS NULL")
    op.create_index("ix_tickets_category_status", "tickets", ["category_id", "status"])
    op.create_index("ix_tickets_accept_due", "tickets", ["accept_due_at"])
    op.create_index("ix_tickets_resolve_due", "tickets", ["resolve_due_at"])


def downgrade() -> None:
    for index in ["ix_tickets_resolve_due", "ix_tickets_accept_due", "ix_tickets_category_status"]:
        op.drop_index(index, table_name="tickets")
    op.drop_constraint("ck_tickets_requested_priority", "tickets", type_="check")
    op.drop_constraint("ck_tickets_priority", "tickets", type_="check")
    op.execute("UPDATE tickets SET priority = CASE priority WHEN 'expedited' THEN 'high' WHEN 'major' THEN 'urgent' ELSE priority END")
    op.create_check_constraint("ck_tickets_priority", "tickets", "priority IN ('low','normal','high','urgent')")
    op.drop_constraint("fk_tickets_priority_confirmer", "tickets", type_="foreignkey")
    op.drop_constraint("fk_tickets_category", "tickets", type_="foreignkey")
    for column in ["reminder_count", "total_paused_seconds", "sla_pause_reason", "sla_paused_at", "resolve_due_at", "accept_due_at", "priority_confirmed_by", "priority_confirmed_at", "requested_priority", "category_id"]:
        op.drop_column("tickets", column)
    op.drop_index("ix_categories_parent_active", table_name="categories")
    op.drop_table("categories")
