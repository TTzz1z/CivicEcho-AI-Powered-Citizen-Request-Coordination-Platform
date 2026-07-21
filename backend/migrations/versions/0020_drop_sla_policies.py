"""Drop sla_policies table (R4: single SLA source of truth).

Revision ID: 0020
Revises: 0019

Background:
- The `sla_policies` table was created in 0010 with the intent of supporting
  admin-configurable SLA policies per (category, priority).
- In practice it was never wired up: `ticket_service.accept` reads SLA minutes
  from `categories.accept_sla_minutes` / `categories.resolve_sla_minutes`
  directly. The `sla_policies` table has been 0 rows since creation.
- Frontend never calls /admin/sla-policies.

R4 decision: keep a single SLA source of truth — the `categories` table.
This migration drops the unused `sla_policies` table and the corresponding
ORM model is removed in the same commit.

Rollback: downgrade recreates the table structure (empty).
"""
from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_sla_policies_category_priority", table_name="sla_policies")
    op.drop_table("sla_policies")


def downgrade() -> None:
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("category_id", sa.BigInteger(), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("priority", sa.String(24)),
        sa.Column("accept_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("resolve_minutes", sa.Integer(), nullable=False, server_default="2880"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sla_policies_category_priority", "sla_policies", ["category_id", "priority"])
