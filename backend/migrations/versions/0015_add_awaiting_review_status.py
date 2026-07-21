"""Add awaiting_review to collaboration_status and dissatisfied_recorded to feedback result (P0-A, P0-B).

Revision ID: 0015
Revises: 0014
"""
from alembic import op


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_tickets_collaboration_status", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_collaboration_status", "tickets",
        "collaboration_status IN ('none','awaiting_citizen','awaiting_dispatch','in_progress','awaiting_summary','awaiting_review','disputed','completed')",
    )
    op.drop_constraint("ck_ticket_feedback_result", "ticket_feedbacks", type_="check")
    op.create_check_constraint(
        "ck_ticket_feedback_result", "ticket_feedbacks",
        "result IN ('closed','reopened','dissatisfied_recorded')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ticket_feedback_result", "ticket_feedbacks", type_="check")
    op.create_check_constraint(
        "ck_ticket_feedback_result", "ticket_feedbacks",
        "result IN ('closed','reopened')",
    )
    op.drop_constraint("ck_tickets_collaboration_status", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_collaboration_status", "tickets",
        "collaboration_status IN ('none','awaiting_citizen','awaiting_dispatch','in_progress','awaiting_summary','disputed','completed')",
    )
