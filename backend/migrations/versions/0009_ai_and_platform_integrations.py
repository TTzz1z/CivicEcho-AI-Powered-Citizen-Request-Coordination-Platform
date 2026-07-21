"""phase 6 AI recommendations and platform integration metadata

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_subject", sa.String(255)))
    op.add_column("users", sa.Column("directory_external_id", sa.String(255)))
    op.create_unique_constraint("uq_users_oidc_subject", "users", ["oidc_subject"])
    op.create_unique_constraint("uq_users_directory_external_id", "users", ["directory_external_id"])

    op.add_column("tickets", sa.Column("external_platform", sa.String(32)))
    op.add_column("tickets", sa.Column("external_ticket_id", sa.String(128)))
    op.add_column("tickets", sa.Column("external_sync_status", sa.String(24)))
    op.add_column("tickets", sa.Column("external_synced_at", sa.DateTime(timezone=True)))
    op.create_index("ix_tickets_external_reference", "tickets", ["external_platform", "external_ticket_id"], unique=True)

    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestion_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="none"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(32), nullable=False, server_default="rules"),
        sa.Column("model_name", sa.String(100), nullable=False, server_default="phase6-rules-v1"),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text()),
        sa.Column("generated_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_decision", sa.String(24)),
        sa.Column("review_comment", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("suggestion_type IN ('assignment','similarity','summary','completeness','document_draft','risk')", name="ck_ai_suggestion_type"),
        sa.CheckConstraint("status IN ('completed','failed')", name="ck_ai_suggestion_status"),
        sa.CheckConstraint("risk_level IN ('none','attention','urgent','sensitive')", name="ck_ai_suggestion_risk"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_ai_suggestion_confidence"),
        sa.CheckConstraint("review_decision IS NULL OR review_decision IN ('helpful','not_helpful')", name="ck_ai_suggestion_review"),
        sa.UniqueConstraint("ticket_id", "suggestion_type", "input_fingerprint", name="uq_ai_suggestion_input"),
    )
    op.create_index("ix_ai_suggestions_ticket_created", "ai_suggestions", ["ticket_id", "created_at"])
    op.create_index("ix_ai_suggestions_type_risk_created", "ai_suggestions", ["suggestion_type", "risk_level", "created_at"])

    op.create_table(
        "integration_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_type", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("external_id", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("response_code", sa.Integer()),
        sa.Column("error_summary", sa.String(500)),
        sa.Column("requested_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("integration_type IN ('oidc','directory','work_order','sms','map','division','logging','monitoring')", name="ck_integration_type"),
        sa.CheckConstraint("direction IN ('inbound','outbound')", name="ck_integration_direction"),
        sa.CheckConstraint("status IN ('pending','success','failed','skipped')", name="ck_integration_status"),
    )
    op.create_index("ix_integration_events_type_created", "integration_events", ["integration_type", "created_at"])
    op.create_index("ix_integration_events_resource", "integration_events", ["resource_type", "resource_id", "created_at"])

    # Existing users and tickets remain valid. No historical AI output or external reference
    # is fabricated during migration; all new columns are nullable and records are opt-in.


def downgrade() -> None:
    op.drop_index("ix_integration_events_resource", table_name="integration_events")
    op.drop_index("ix_integration_events_type_created", table_name="integration_events")
    op.drop_table("integration_events")
    op.drop_index("ix_ai_suggestions_type_risk_created", table_name="ai_suggestions")
    op.drop_index("ix_ai_suggestions_ticket_created", table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
    op.drop_index("ix_tickets_external_reference", table_name="tickets")
    op.drop_column("tickets", "external_synced_at")
    op.drop_column("tickets", "external_sync_status")
    op.drop_column("tickets", "external_ticket_id")
    op.drop_column("tickets", "external_platform")
    op.drop_constraint("uq_users_directory_external_id", "users", type_="unique")
    op.drop_constraint("uq_users_oidc_subject", "users", type_="unique")
    op.drop_column("users", "directory_external_id")
    op.drop_column("users", "oidc_subject")
