"""enterprise ticket workflow, identity, departments and audit

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


DEPARTMENTS = [
    ("urban-management", "城市管理", "市容、环卫、道路与公共设施"),
    ("transport", "交通运输", "公交、道路运输与交通服务"),
    ("housing-property", "住房物业", "住房、物业与小区管理"),
    ("education", "教育服务", "学校与教育公共服务"),
    ("health", "医疗卫生", "医疗与公共卫生服务"),
    ("community-civil", "社区民政", "社区、养老与民政服务"),
    ("general-intake", "综合受理", "跨部门事项与统一受理"),
]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_departments_code"),
        sa.UniqueConstraint("name", name="uq_departments_name"),
    )
    departments = sa.table("departments", sa.column("code"), sa.column("name"), sa.column("description"))
    op.bulk_insert(departments, [{"code": code, "name": name, "description": description} for code, name, description in DEPARTMENTS])

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('citizen','agent','department_staff','admin')", name="ck_users_role"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_department_role", "users", ["department_id", "role"])

    op.add_column("tickets", sa.Column("occurred_at_text", sa.String(200)))
    op.add_column("tickets", sa.Column("occurred_at_start", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("occurred_at_end", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("occurred_at_precision", sa.String(32)))
    op.add_column("tickets", sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"))
    op.add_column("tickets", sa.Column("creator_user_id", sa.BigInteger()))
    op.add_column("tickets", sa.Column("anonymous_creator_key", sa.String(64)))
    op.add_column("tickets", sa.Column("assigned_department_id", sa.BigInteger()))
    op.add_column("tickets", sa.Column("assigned_user_id", sa.BigInteger()))
    op.add_column("tickets", sa.Column("priority", sa.String(16), nullable=False, server_default="normal"))
    op.add_column("tickets", sa.Column("accepted_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE tickets SET occurred_at_text = occurred_at WHERE occurred_at_text IS NULL")
    op.execute("""
        UPDATE tickets SET status = CASE status
          WHEN '待受理' THEN 'pending' WHEN '受理中' THEN 'accepted'
          WHEN '处理中' THEN 'processing' WHEN '已办结' THEN 'closed'
          WHEN '已关闭' THEN 'closed' ELSE status END
    """)
    op.create_foreign_key("fk_tickets_creator_user", "tickets", "users", ["creator_user_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tickets_assigned_department", "tickets", "departments", ["assigned_department_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tickets_assigned_user", "tickets", "users", ["assigned_user_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_tickets_status", "tickets", "status IN ('pending','accepted','assigned','processing','resolved','closed','rejected')")
    op.create_check_constraint("ck_tickets_priority", "tickets", "priority IN ('low','normal','high','urgent')")
    op.create_index("ix_tickets_status_created", "tickets", ["status", "created_at"])
    op.create_index("ix_tickets_department_status", "tickets", ["assigned_department_id", "status"])
    op.create_index("ix_tickets_creator_created", "tickets", ["creator_user_id", "created_at"])
    op.create_index("ix_tickets_anonymous_creator", "tickets", ["anonymous_creator_key"])

    op.add_column("ticket_status_history", sa.Column("operator_user_id", sa.BigInteger()))
    op.add_column("ticket_status_history", sa.Column("operation_type", sa.String(32), nullable=False, server_default="status_change"))
    op.add_column("ticket_status_history", sa.Column("content", sa.Text()))
    op.execute("UPDATE ticket_status_history SET content = remark WHERE content IS NULL")
    op.execute("""
        UPDATE ticket_status_history SET
          previous_status = CASE previous_status WHEN '待受理' THEN 'pending' WHEN '受理中' THEN 'accepted' WHEN '处理中' THEN 'processing' WHEN '已办结' THEN 'closed' WHEN '已关闭' THEN 'closed' ELSE previous_status END,
          current_status = CASE current_status WHEN '待受理' THEN 'pending' WHEN '受理中' THEN 'accepted' WHEN '处理中' THEN 'processing' WHEN '已办结' THEN 'closed' WHEN '已关闭' THEN 'closed' ELSE current_status END
    """)
    op.create_foreign_key("fk_ticket_history_operator", "ticket_status_history", "users", ["operator_user_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_actor_created", "audit_logs", ["actor_user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_constraint("fk_ticket_history_operator", "ticket_status_history", type_="foreignkey")
    op.drop_column("ticket_status_history", "content")
    op.drop_column("ticket_status_history", "operation_type")
    op.drop_column("ticket_status_history", "operator_user_id")
    for index in ["ix_tickets_anonymous_creator", "ix_tickets_creator_created", "ix_tickets_department_status", "ix_tickets_status_created"]:
        op.drop_index(index, table_name="tickets")
    op.drop_constraint("ck_tickets_priority", "tickets", type_="check")
    op.drop_constraint("ck_tickets_status", "tickets", type_="check")
    for constraint in ["fk_tickets_assigned_user", "fk_tickets_assigned_department", "fk_tickets_creator_user"]:
        op.drop_constraint(constraint, "tickets", type_="foreignkey")
    for column in ["version", "closed_at", "resolved_at", "accepted_at", "priority", "assigned_user_id", "assigned_department_id", "anonymous_creator_key", "creator_user_id", "timezone", "occurred_at_precision", "occurred_at_end", "occurred_at_start", "occurred_at_text"]:
        op.drop_column("tickets", column)
    op.drop_table("users")
    op.drop_table("departments")
