"""Extend ai_suggestions for ticket_advice evidence chain.

Revision ID: 0023
Revises: 0022
"""
from alembic import op


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ai_suggestion_type", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_type",
        "ai_suggestions",
        "suggestion_type IN ("
        "'assignment','similarity','summary','completeness','document_draft','risk',"
        "'ticket_advice'"
        ")",
    )
    op.drop_constraint("ck_ai_suggestion_review", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_review",
        "ai_suggestions",
        "review_decision IS NULL OR review_decision IN ("
        "'helpful','not_helpful',"
        "'adopted','adopted_with_edits','rejected'"
        ")",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ai_suggestions SET review_decision = NULL "
        "WHERE review_decision IN ('adopted','adopted_with_edits','rejected')"
    )
    op.execute("DELETE FROM ai_suggestions WHERE suggestion_type = 'ticket_advice'")
    op.drop_constraint("ck_ai_suggestion_review", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_review",
        "ai_suggestions",
        "review_decision IS NULL OR review_decision IN ('helpful','not_helpful')",
    )
    op.drop_constraint("ck_ai_suggestion_type", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_type",
        "ai_suggestions",
        "suggestion_type IN ("
        "'assignment','similarity','summary','completeness','document_draft','risk'"
        ")",
    )
