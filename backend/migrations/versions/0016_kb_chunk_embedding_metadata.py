"""Add embedding metadata columns to kb_chunks for traceability (P0-D).

Revision ID: 0016
Revises: 0015

Adds embedding_model, embedding_provider, embedding_dimension, embedding_fallback
to kb_chunks so each chunk records exactly which model/provider/dimension produced
its vector and whether a fallback path was used. Historical rows remain valid
(columns are nullable or have safe defaults); only newly-indexed chunks populate them.
"""
from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_chunks", sa.Column("embedding_model", sa.String(128)))
    op.add_column("kb_chunks", sa.Column("embedding_provider", sa.String(64)))
    op.add_column("kb_chunks", sa.Column("embedding_dimension", sa.Integer))
    op.add_column(
        "kb_chunks",
        sa.Column("embedding_fallback", sa.String(32), nullable=False, server_default="none"),
    )
    op.create_index(
        "ix_kb_chunks_embedding_model", "kb_chunks", ["embedding_model"]
    )


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_embedding_model", table_name="kb_chunks")
    op.drop_column("kb_chunks", "embedding_fallback")
    op.drop_column("kb_chunks", "embedding_dimension")
    op.drop_column("kb_chunks", "embedding_provider")
    op.drop_column("kb_chunks", "embedding_model")
