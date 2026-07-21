"""phase 5 notifications, follow-ups and appeals

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("handling_round", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tickets", sa.Column("appeal_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_tickets_handling_round", "tickets", "handling_round >= 1")
    op.create_check_constraint("ck_tickets_appeal_count", "tickets", "appeal_count BETWEEN 0 AND 2")
    op.drop_constraint("ck_tickets_closure_type", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_closure_type", "tickets",
        "closure_type IS NULL OR closure_type IN ('citizen_confirmed','admin_override','phone_confirmed')",
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipient_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False, server_default="in_app"),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unread"),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="delivered"),
        sa.Column("event_key", sa.String(160), nullable=False, unique=True),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("channel IN ('in_app','sms','wechat','email','government_message')", name="ck_notifications_channel"),
        sa.CheckConstraint("status IN ('unread','read')", name="ck_notifications_status"),
        sa.CheckConstraint("delivery_status IN ('pending','delivered','failed','skipped')", name="ck_notifications_delivery"),
    )
    op.create_index("ix_notifications_recipient_status_created", "notifications", ["recipient_user_id", "status", "created_at"])
    op.create_index("ix_notifications_ticket_created", "notifications", ["ticket_id", "created_at"])

    op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("handling_round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("assigned_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','in_progress','completed','cancelled')", name="ck_follow_up_tasks_status"),
        sa.UniqueConstraint("ticket_id", "handling_round", name="uq_follow_up_ticket_round"),
    )
    op.create_index("ix_follow_up_tasks_status_due", "follow_up_tasks", ["status", "due_at"])
    op.create_index("ix_follow_up_tasks_assignee_status", "follow_up_tasks", ["assigned_user_id", "status"])

    op.create_table(
        "phone_follow_up_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("follow_up_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("caller_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("contact_result", sa.String(24), nullable=False),
        sa.Column("satisfaction", sa.String(32)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("contact_result IN ('reached','no_answer','wrong_number')", name="ck_phone_follow_up_contact"),
        sa.CheckConstraint("satisfaction IS NULL OR satisfaction IN ('satisfied','mostly_satisfied','dissatisfied')", name="ck_phone_follow_up_satisfaction"),
        sa.CheckConstraint("outcome IN ('confirmed','needs_followup','appeal_requested')", name="ck_phone_follow_up_outcome"),
    )
    op.create_index("ix_phone_follow_up_ticket_created", "phone_follow_up_records", ["ticket_id", "created_at"])

    op.create_table(
        "appeals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("appeal_no", sa.String(64), nullable=False, unique=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("citizen_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("desired_resolution", sa.Text(), nullable=False),
        sa.Column("review_comment", sa.Text()),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reprocess_instructions", sa.Text()),
        sa.Column("result_summary", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sequence BETWEEN 1 AND 2", name="ck_appeals_sequence"),
        sa.CheckConstraint("status IN ('submitted','approved','rejected','reprocessing','completed')", name="ck_appeals_status"),
        sa.UniqueConstraint("ticket_id", "sequence", name="uq_appeal_ticket_sequence"),
    )
    op.create_index("ix_appeals_status_created", "appeals", ["status", "created_at"])
    op.create_index("ix_appeals_ticket_created", "appeals", ["ticket_id", "created_at"])

    # Backfill only durable facts. Closed/resolved legacy tickets do not get synthetic
    # notifications or follow-up tasks, so historical data remains semantically intact.
    op.execute("UPDATE tickets SET handling_round = 1 WHERE handling_round IS NULL")
    op.execute("UPDATE tickets SET appeal_count = 0 WHERE appeal_count IS NULL")


def downgrade() -> None:
    op.drop_index("ix_appeals_ticket_created", table_name="appeals")
    op.drop_index("ix_appeals_status_created", table_name="appeals")
    op.drop_table("appeals")
    op.drop_index("ix_phone_follow_up_ticket_created", table_name="phone_follow_up_records")
    op.drop_table("phone_follow_up_records")
    op.drop_index("ix_follow_up_tasks_assignee_status", table_name="follow_up_tasks")
    op.drop_index("ix_follow_up_tasks_status_due", table_name="follow_up_tasks")
    op.drop_table("follow_up_tasks")
    op.drop_index("ix_notifications_ticket_created", table_name="notifications")
    op.drop_index("ix_notifications_recipient_status_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_constraint("ck_tickets_closure_type", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_closure_type", "tickets",
        "closure_type IS NULL OR closure_type IN ('citizen_confirmed','admin_override')",
    )
    op.drop_constraint("ck_tickets_appeal_count", "tickets", type_="check")
    op.drop_constraint("ck_tickets_handling_round", "tickets", type_="check")
    op.drop_column("tickets", "appeal_count")
    op.drop_column("tickets", "handling_round")
