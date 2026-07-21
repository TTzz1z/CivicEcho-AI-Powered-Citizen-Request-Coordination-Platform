"""Fix 3 KB schema drifts detected by alembic check.

Revision ID: 0021
Revises: 0020

Drifts (R5-1):
1. `ix_kb_chunks_embedding_model` index exists in DB but not in ORM
   (dropped from model in an earlier change without a migration) → DROP index.
2. `kb_eval_cases.expected_role` is nullable in DB but NOT NULL in ORM
   (Mapped[str], default='citizen') → ALTER COLUMN SET NOT NULL.
3. `kb_eval_runs.evaluator` is nullable in DB but NOT NULL in ORM
   (Mapped[str], default='rules') → ALTER COLUMN SET NOT NULL.

Safe: verified there are 0 NULL rows in either column before this migration.

The ORM models are the source of truth — we adjust the DB to match.
"""
from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Drop stale index on kb_chunks.embedding_model
    op.drop_index("ix_kb_chunks_embedding_model", table_name="kb_chunks")

    # 2) Backfill any potential NULLs (defensive; verified 0 rows today)
    op.execute("UPDATE kb_eval_cases SET expected_role = 'citizen' WHERE expected_role IS NULL")
    op.execute("UPDATE kb_eval_runs SET evaluator = 'rules' WHERE evaluator IS NULL")

    # 3) Enforce NOT NULL to match ORM
    op.alter_column(
        "kb_eval_cases", "expected_role",
        existing_type=sa.String(32),
        nullable=False,
        existing_server_default="citizen",
    )
    op.alter_column(
        "kb_eval_runs", "evaluator",
        existing_type=sa.String(64),
        nullable=False,
        existing_server_default="rules",
    )


def downgrade() -> None:
    # Reverse: relax NOT NULL back to nullable, recreate the index
    op.alter_column(
        "kb_eval_cases", "expected_role",
        existing_type=sa.String(32),
        nullable=True,
        existing_server_default="citizen",
    )
    op.alter_column(
        "kb_eval_runs", "evaluator",
        existing_type=sa.String(64),
        nullable=True,
        existing_server_default="rules",
    )
    op.create_index("ix_kb_chunks_embedding_model", "kb_chunks", ["embedding_model"])
