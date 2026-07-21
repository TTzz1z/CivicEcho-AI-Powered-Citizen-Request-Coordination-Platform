"""Knowledge base extensions: pgvector, file metadata, versions, evaluation.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Extend kb_documents ---
    op.add_column("kb_documents", sa.Column("storage_key", sa.String(500)))
    op.add_column("kb_documents", sa.Column("original_filename", sa.String(500)))
    op.add_column("kb_documents", sa.Column("mime_type", sa.String(200)))
    op.add_column("kb_documents", sa.Column("file_size_bytes", sa.BigInteger))
    op.add_column("kb_documents", sa.Column("ocr_status", sa.String(32), nullable=False, server_default="none"))
    op.add_column("kb_documents", sa.Column("ocr_quality", sa.Float))
    op.add_column("kb_documents", sa.Column("tags", sa.Text))
    op.add_column("kb_documents", sa.Column("meta_json", sa.Text))
    op.add_column("kb_documents", sa.Column("index_status", sa.String(32), nullable=False, server_default="pending"))
    op.add_column("kb_documents", sa.Column("embedding_model", sa.String(128)))
    op.add_column("kb_documents", sa.Column("chunking_version", sa.String(32), server_default="v1"))
    op.add_column("kb_documents", sa.Column("published_department_id", sa.BigInteger, sa.ForeignKey("departments.id", ondelete="SET NULL")))
    op.add_column("kb_documents", sa.Column("rejected_reason", sa.Text))
    op.add_column("kb_documents", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("kb_documents", sa.Column("published_by_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.create_index("ix_kb_docs_kb_type_status", "kb_documents", ["kb_type", "status"])
    op.create_index("ix_kb_docs_index_status", "kb_documents", ["index_status"])
    op.create_index("ix_kb_docs_replaces", "kb_documents", ["replaces_doc_id"])
    op.create_index("ix_kb_docs_published_dept", "kb_documents", ["published_department_id"])

    # --- Extend kb_chunks: replace TEXT embedding with vector column ---
    op.drop_column("kb_chunks", "embedding")
    # Use raw SQL to add vector column (pgvector type not in sa types)
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding vector(1024)")
    op.add_column("kb_chunks", sa.Column("chunk_hash", sa.String(64)))
    op.add_column("kb_chunks", sa.Column("keywords", sa.Text))
    op.add_column("kb_chunks", sa.Column("char_count", sa.Integer, nullable=False, server_default="0"))
    op.create_index("ix_kb_chunks_doc_idx_hash", "kb_chunks", ["document_id", "chunk_hash"])

    # --- Evaluation cases ---
    op.create_table(
        "kb_eval_cases",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("domain", sa.String(200)),
        sa.Column("scenario", sa.String(64), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("expected_answer_summary", sa.Text),
        sa.Column("expected_doc_ids", sa.String(500)),
        sa.Column("must_cite_doc_ids", sa.String(500)),
        sa.Column("must_not_cite_doc_ids", sa.String(500)),
        sa.Column("must_avoid_keywords", sa.Text),
        sa.Column("expected_role", sa.String(32), server_default="citizen"),
        sa.Column("expected_no_answer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_eval_cases_scenario", "kb_eval_cases", ["scenario", "is_active"])

    # --- Evaluation runs ---
    op.create_table(
        "kb_eval_runs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("kb_eval_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("answer_text", sa.Text),
        sa.Column("citations_json", sa.Text),
        sa.Column("no_evidence", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("retrieval_hit", sa.Boolean, server_default=sa.false()),
        sa.Column("citation_correct", sa.Boolean, server_default=sa.false()),
        sa.Column("answer_faithful", sa.Boolean, server_default=sa.false()),
        sa.Column("expired_policy_blocked", sa.Boolean, server_default=sa.false()),
        sa.Column("permission_isolated", sa.Boolean, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("provider", sa.String(64)),
        sa.Column("model_name", sa.String(128)),
        sa.Column("evaluator", sa.String(64), server_default="rules"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_eval_runs_case", "kb_eval_runs", ["case_id", "created_at"])

    # --- No-answer / unanswered questions ---
    op.create_table(
        "kb_no_answer_questions",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("role", sa.String(32)),
        sa.Column("route", sa.String(64)),
        sa.Column("retrieved_doc_ids", sa.String(500)),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("assigned_department_id", sa.BigInteger, sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("resolution_note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_kb_no_answer_status", "kb_no_answer_questions", ["status", "created_at"])


def downgrade():
    op.drop_table("kb_no_answer_questions")
    op.drop_table("kb_eval_runs")
    op.drop_table("kb_eval_cases")

    op.drop_index("ix_kb_chunks_doc_idx_hash", table_name="kb_chunks")
    op.drop_column("kb_chunks", "char_count")
    op.drop_column("kb_chunks", "keywords")
    op.drop_column("kb_chunks", "chunk_hash")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN embedding")
    op.add_column("kb_chunks", sa.Column("embedding", sa.Text))

    op.drop_index("ix_kb_docs_published_dept", table_name="kb_documents")
    op.drop_index("ix_kb_docs_replaces", table_name="kb_documents")
    op.drop_index("ix_kb_docs_index_status", table_name="kb_documents")
    op.drop_index("ix_kb_docs_kb_type_status", table_name="kb_documents")
    for col in (
        "published_by_user_id", "reviewed_at", "rejected_reason",
        "published_department_id", "chunking_version", "embedding_model",
        "index_status", "meta_json", "tags", "ocr_quality", "ocr_status",
        "file_size_bytes", "mime_type", "original_filename", "storage_key",
    ):
        op.drop_column("kb_documents", col)
