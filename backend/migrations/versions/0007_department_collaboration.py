"""phase 4 department work order collaboration

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("collaboration_status", sa.String(32), nullable=False, server_default="none"))
    op.add_column("tickets", sa.Column("supplement_reason", sa.Text()))
    op.add_column("tickets", sa.Column("supplement_requested_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("supplemented_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("dispatch_return_reason", sa.Text()))
    op.add_column("tickets", sa.Column("dispute_reason", sa.Text()))
    op.add_column("tickets", sa.Column("dispute_resolution", sa.Text()))
    op.create_check_constraint(
        "ck_tickets_collaboration_status", "tickets",
        "collaboration_status IN ('none','awaiting_citizen','awaiting_dispatch','in_progress','awaiting_summary','disputed','completed')",
    )

    op.create_table(
        "work_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_order_no", sa.String(64), nullable=False, unique=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assignee_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.String(500)),
        sa.Column("result_measures", sa.Text()),
        sa.Column("result_outcome", sa.String(32)),
        sa.Column("public_content", sa.Text()),
        sa.Column("internal_note", sa.Text()),
        sa.Column("return_reason", sa.Text()),
        sa.Column("source_work_order_id", sa.String(36), sa.ForeignKey("work_orders.id", ondelete="SET NULL")),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("task_type IN ('primary','support','review')", name="ck_work_orders_task_type"),
        sa.CheckConstraint("status IN ('pending','processing','returned','transferred','submitted','cancelled')", name="ck_work_orders_status"),
        sa.CheckConstraint("result_outcome IS NULL OR result_outcome IN ('resolved','partially_resolved','unresolved')", name="ck_work_orders_outcome"),
    )
    op.create_index("ix_work_orders_ticket_status", "work_orders", ["ticket_id", "status"])
    op.create_index("ix_work_orders_department_status", "work_orders", ["department_id", "status"])
    op.create_index("ix_work_orders_assignee_status", "work_orders", ["assignee_user_id", "status"])

    op.create_table(
        "work_order_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("work_order_id", sa.String(36), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operator_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(24)),
        sa.Column("current_status", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_work_order_history_order_created", "work_order_history", ["work_order_id", "created_at"])

    # Existing single-department assignments become primary tasks without changing ticket numbers or status.
    op.execute("""
        INSERT INTO work_orders (id, work_order_no, ticket_id, task_type, status, department_id,
                                 assignee_user_id, instructions, created_at, updated_at)
        SELECT md5(ticket_id || '-legacy'), ticket_id || '-M-LEGACY', ticket_id, 'primary',
               CASE WHEN status IN ('resolved','closed') THEN 'submitted'
                    WHEN status = 'processing' THEN 'processing' ELSE 'pending' END,
               assigned_department_id, assigned_user_id, '历史主办任务迁移', created_at, updated_at
        FROM tickets WHERE assigned_department_id IS NOT NULL
    """)
    op.execute("UPDATE tickets SET collaboration_status = 'in_progress' WHERE assigned_department_id IS NOT NULL AND status NOT IN ('resolved','closed')")
    op.execute("UPDATE tickets SET collaboration_status = 'completed' WHERE assigned_department_id IS NOT NULL AND status IN ('resolved','closed')")


def downgrade() -> None:
    op.drop_index("ix_work_order_history_order_created", table_name="work_order_history")
    op.drop_table("work_order_history")
    op.drop_index("ix_work_orders_assignee_status", table_name="work_orders")
    op.drop_index("ix_work_orders_department_status", table_name="work_orders")
    op.drop_index("ix_work_orders_ticket_status", table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_constraint("ck_tickets_collaboration_status", "tickets", type_="check")
    for column in ["dispute_resolution", "dispute_reason", "dispatch_return_reason", "supplemented_at", "supplement_requested_at", "supplement_reason", "collaboration_status"]:
        op.drop_column("tickets", column)
