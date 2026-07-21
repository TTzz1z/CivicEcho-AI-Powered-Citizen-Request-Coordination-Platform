"""citizen feedback, formal resolution and standardized rejection

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("resolution_summary", sa.String(500)))
    op.add_column("tickets", sa.Column("resolution_measures", sa.Text()))
    op.add_column("tickets", sa.Column("resolution_outcome", sa.String(32)))
    op.add_column("tickets", sa.Column("public_reply", sa.Text()))
    op.add_column("tickets", sa.Column("internal_note", sa.Text()))
    op.add_column("tickets", sa.Column("rejection_reason_code", sa.String(64)))
    op.add_column("tickets", sa.Column("rejection_detail", sa.Text()))
    op.add_column("tickets", sa.Column("suggested_channel", sa.String(500)))
    op.add_column("tickets", sa.Column("needs_supplement", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tickets", sa.Column("closure_type", sa.String(32)))
    op.create_check_constraint(
        "ck_tickets_resolution_outcome", "tickets",
        "resolution_outcome IS NULL OR resolution_outcome IN ('resolved','partially_resolved','unresolved')",
    )
    op.create_check_constraint(
        "ck_tickets_closure_type", "tickets",
        "closure_type IS NULL OR closure_type IN ('citizen_confirmed','admin_override')",
    )

    op.add_column(
        "ticket_status_history",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
    )
    op.create_check_constraint(
        "ck_ticket_history_visibility", "ticket_status_history",
        "visibility IN ('public','internal')",
    )

    op.create_table(
        "ticket_feedbacks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("citizen_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolution_version", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "rating IN ('satisfied','mostly_satisfied','dissatisfied')",
            name="ck_ticket_feedback_rating",
        ),
        sa.CheckConstraint("result IN ('closed','reopened')", name="ck_ticket_feedback_result"),
        sa.UniqueConstraint("ticket_id", "resolution_version", name="uq_ticket_feedback_resolution"),
    )
    op.create_index("ix_ticket_feedback_ticket_created", "ticket_feedbacks", ["ticket_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ticket_feedback_ticket_created", table_name="ticket_feedbacks")
    op.drop_table("ticket_feedbacks")
    op.drop_constraint("ck_ticket_history_visibility", "ticket_status_history", type_="check")
    op.drop_column("ticket_status_history", "visibility")
    op.drop_constraint("ck_tickets_closure_type", "tickets", type_="check")
    op.drop_constraint("ck_tickets_resolution_outcome", "tickets", type_="check")
    for column in [
        "closure_type", "needs_supplement", "suggested_channel", "rejection_detail",
        "rejection_reason_code", "internal_note", "public_reply", "resolution_outcome",
        "resolution_measures", "resolution_summary",
    ]:
        op.drop_column("tickets", column)
