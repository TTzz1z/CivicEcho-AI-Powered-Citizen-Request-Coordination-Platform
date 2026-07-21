"""create ticket tables and sequence

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE ticket_number_seq START WITH 1 INCREMENT BY 1")
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ticket_id", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_type", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(500), nullable=False),
        sa.Column("event", sa.Text()),
        sa.Column("occurred_at", sa.String(200)),
        sa.Column("target", sa.String(500)),
        sa.Column("contact", sa.String(200)),
        sa.Column("status", sa.String(32), nullable=False, server_default="待受理"),
        sa.Column("source", sa.String(32), nullable=False, server_default="rasa"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticket_id", name="uq_tickets_ticket_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_tickets_idempotency_key"),
    )
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])
    op.create_index("ix_tickets_contact_created_at", "tickets", ["contact", "created_at"])
    op.create_table(
        "ticket_status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_status", sa.String(32)),
        sa.Column("current_status", sa.String(32), nullable=False),
        sa.Column("remark", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_history_ticket_created", "ticket_status_history", ["ticket_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ticket_status_history")
    op.drop_table("tickets")
    op.execute("DROP SEQUENCE ticket_number_seq")

