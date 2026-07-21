"""Extend ai_usage_logs for Round 2 unified AI audit.

Revision ID: 0017
Revises: 0016

Adds:
- session_id: per-session identifier (replaces the shared user:default fallback)
- capability: which AI capability produced this call
  (orchestrator_classify|ticket_draft|policy_rag|service_guide|ticket_advice|
   ai_analyze|pre_review|embedding_index|embedding_query|semantic_cache)
- provider: model provider label (deepseek|silicon_flow|openai|volcengine|rules|fallback)
- total_tokens: prompt + completion tokens
- usage_unavailable: True when the model response did not include a usage block
  (MUST NOT be silently treated as 0; recorded honestly for traceability)
- degrade_reason: llm_unavailable|embedding_unavailable|concurrent_exceeded|
                  budget_exceeded|rate_limited|rag_failed|rules_fallback
- budget_exceeded: separate boolean (was previously conflated with degraded)
- error_code: stable error code (e.g. HTTP status, library exception class)
- text_count: number of texts in an embedding batch
- text_chars: total characters across the embedding batch

Backwards compatible: all new columns are nullable or have safe defaults.
Existing rows remain valid; only Round 2 code paths populate the new fields.
"""
from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage_logs", sa.Column("session_id", sa.String(128)))
    op.add_column("ai_usage_logs", sa.Column("capability", sa.String(64)))
    op.add_column("ai_usage_logs", sa.Column("provider", sa.String(64)))
    op.add_column("ai_usage_logs", sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"))
    op.add_column(
        "ai_usage_logs",
        sa.Column("usage_unavailable", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("ai_usage_logs", sa.Column("degrade_reason", sa.String(64)))
    op.add_column(
        "ai_usage_logs",
        sa.Column("budget_exceeded", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("ai_usage_logs", sa.Column("error_code", sa.String(64)))
    op.add_column("ai_usage_logs", sa.Column("text_count", sa.Integer))
    op.add_column("ai_usage_logs", sa.Column("text_chars", sa.Integer))

    op.create_index("ix_ai_usage_logs_session_created", "ai_usage_logs", ["session_id", "created_at"])
    op.create_index("ix_ai_usage_logs_capability_created", "ai_usage_logs", ["capability", "created_at"])
    op.create_index("ix_ai_usage_logs_provider_created", "ai_usage_logs", ["provider", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_logs_provider_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_capability_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_session_created", table_name="ai_usage_logs")
    op.drop_column("ai_usage_logs", "text_chars")
    op.drop_column("ai_usage_logs", "text_count")
    op.drop_column("ai_usage_logs", "error_code")
    op.drop_column("ai_usage_logs", "budget_exceeded")
    op.drop_column("ai_usage_logs", "degrade_reason")
    op.drop_column("ai_usage_logs", "usage_unavailable")
    op.drop_column("ai_usage_logs", "total_tokens")
    op.drop_column("ai_usage_logs", "provider")
    op.drop_column("ai_usage_logs", "capability")
    op.drop_column("ai_usage_logs", "session_id")
