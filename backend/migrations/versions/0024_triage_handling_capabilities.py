"""Add triage_assistant / handling_assistant suggestion types.

Revision ID: 0024
Revises: 0023
"""
from alembic import op


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ai_suggestion_type", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_type",
        "ai_suggestions",
        "suggestion_type IN ("
        "'assignment','similarity','summary','completeness','document_draft','risk',"
        "'ticket_advice','triage_assistant','handling_assistant'"
        ")",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ai_suggestions WHERE suggestion_type IN "
        "('triage_assistant','handling_assistant')"
    )
    op.drop_constraint("ck_ai_suggestion_type", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_ai_suggestion_type",
        "ai_suggestions",
        "suggestion_type IN ("
        "'assignment','similarity','summary','completeness','document_draft','risk',"
        "'ticket_advice'"
        ")",
    )
