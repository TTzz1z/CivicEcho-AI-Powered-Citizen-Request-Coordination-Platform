"""worker notification outbox and SLA policies

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("recipient_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=True),
        sa.Column("channel", sa.String(24), nullable=False, server_default="in_app"),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
    )
    op.create_unique_constraint("uq_outbox_idempotency_key", "notification_outbox", ["idempotency_key"])
    op.create_index("ix_outbox_status_next_retry", "notification_outbox", ["status", "next_retry_at"])
    op.create_index("ix_outbox_recipient_created", "notification_outbox", ["recipient_user_id", "created_at"])

    op.create_table(
        "sla_policies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category_id", sa.BigInteger(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("priority", sa.String(24), nullable=True),
        sa.Column("accept_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("resolve_minutes", sa.Integer(), nullable=False, server_default="2880"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_sla_policies_name", "sla_policies", ["name"])
    op.create_index("ix_sla_policies_category_priority", "sla_policies", ["category_id", "priority"])


def downgrade() -> None:
    op.drop_table("sla_policies")
    op.drop_table("notification_outbox")
