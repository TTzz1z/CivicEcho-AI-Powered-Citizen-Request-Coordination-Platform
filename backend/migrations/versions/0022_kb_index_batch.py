"""Atomic KB index batches: keep live chunks until rebuild succeeds.

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column("active_index_batch", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "kb_chunks",
        sa.Column("index_batch_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_kb_chunks_doc_batch",
        "kb_chunks",
        ["document_id", "index_batch_id"],
    )
    op.create_index(
        "ix_kb_docs_active_index_batch",
        "kb_documents",
        ["active_index_batch"],
    )
    # Backfill: existing chunks become the live batch for each document.
    op.execute(
        """
        UPDATE kb_documents d
        SET active_index_batch = 'legacy-' || d.id::text
        WHERE EXISTS (SELECT 1 FROM kb_chunks c WHERE c.document_id = d.id)
          AND d.active_index_batch IS NULL
        """
    )
    op.execute(
        """
        UPDATE kb_chunks c
        SET index_batch_id = 'legacy-' || c.document_id::text
        WHERE c.index_batch_id IS NULL
          AND EXISTS (
            SELECT 1 FROM kb_documents d
            WHERE d.id = c.document_id AND d.active_index_batch = 'legacy-' || c.document_id::text
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_kb_docs_active_index_batch", table_name="kb_documents")
    op.drop_index("ix_kb_chunks_doc_batch", table_name="kb_chunks")
    op.drop_column("kb_chunks", "index_batch_id")
    op.drop_column("kb_documents", "active_index_batch")
