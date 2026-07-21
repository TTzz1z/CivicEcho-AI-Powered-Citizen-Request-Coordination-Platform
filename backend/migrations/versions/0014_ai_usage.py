"""AI usage audit logs and per-user budgets.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("role", sa.String(32)),
        sa.Column("route", sa.String(64)),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_tier", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rate_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estimated_cost_rmb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_usage_logs_created_at", "ai_usage_logs", ["created_at"])
    op.create_index("ix_ai_usage_logs_user_created", "ai_usage_logs", ["user_id", "created_at"])
    op.create_index("ix_ai_usage_logs_route_created", "ai_usage_logs", ["route", "created_at"])
    op.create_index("ix_ai_usage_logs_role_created", "ai_usage_logs", ["role", "created_at"])
    op.create_index("ix_ai_usage_logs_tier_created", "ai_usage_logs", ["model_tier", "created_at"])

    op.create_table(
        "ai_usage_budgets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True),
        sa.Column("role", sa.String(32)),
        sa.Column("daily_llm_call_limit", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("daily_token_limit", sa.Integer()),
        sa.Column("notes", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_usage_budgets_role", "ai_usage_budgets", ["role"])


def downgrade():
    op.drop_index("ix_ai_usage_budgets_role", table_name="ai_usage_budgets")
    op.drop_table("ai_usage_budgets")
    op.drop_index("ix_ai_usage_logs_tier_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_role_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_route_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_user_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_created_at", table_name="ai_usage_logs")
    op.drop_table("ai_usage_logs")
