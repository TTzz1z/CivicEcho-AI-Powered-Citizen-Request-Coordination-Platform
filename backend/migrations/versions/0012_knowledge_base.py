"""Knowledge base tables.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"


def upgrade():
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("doc_number", sa.String(200)),
        sa.Column("department_id", sa.BigInteger, sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("kb_type", sa.String(64), nullable=False, server_default="policy"),
        sa.Column("domain", sa.String(200)),
        sa.Column("region", sa.String(200)),
        sa.Column("audience", sa.String(200)),
        sa.Column("file_type", sa.String(32), nullable=False, server_default="text"),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="PUBLIC"),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_version_id", sa.BigInteger, sa.ForeignKey("kb_documents.id", ondelete="SET NULL")),
        sa.Column("replaces_doc_id", sa.BigInteger, sa.ForeignKey("kb_documents.id", ondelete="SET NULL")),
        sa.Column("source_url", sa.String(1000)),
        sa.Column("keywords", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("parse_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploaded_by_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_comment", sa.Text),
        sa.Column("raw_content", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_docs_status_visibility", "kb_documents", ["status", "visibility"])
    op.create_index("ix_kb_docs_dept_status", "kb_documents", ["department_id", "status"])
    op.create_index("ix_kb_docs_type_domain", "kb_documents", ["kb_type", "domain"])

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("document_id", sa.BigInteger, sa.ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.Text),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_chunks_doc_idx", "kb_chunks", ["document_id", "chunk_index"])

    op.create_table(
        "kb_feedback",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("answer_text", sa.Text),
        sa.Column("document_ids", sa.String(500)),
        sa.Column("feedback_type", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("route", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_feedback_type_time", "kb_feedback", ["feedback_type", "created_at"])


def downgrade():
    op.drop_table("kb_feedback")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
