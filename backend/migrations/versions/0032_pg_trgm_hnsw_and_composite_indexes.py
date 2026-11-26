"""Enable pg_trgm, add HNSW/trigram/composite indexes, and drop legacy Rasa tables."""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS keys CASCADE")

    op.create_index(
        "ix_kb_chunks_embedding_hnsw",
        "kb_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_kb_chunks_content_trgm",
        "kb_chunks",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_tickets_dept_status_created",
        "tickets",
        ["assigned_department_id", "status", "created_at"],
    )
    op.create_index(
        "ix_tickets_assignee_status_created",
        "tickets",
        ["assigned_user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_tickets_status_updated",
        "tickets",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_tickets_collab_status_created",
        "tickets",
        ["collaboration_status", "status", "created_at"],
    )
    op.create_index(
        "ix_tickets_status_paused_resolve_due",
        "tickets",
        ["status", "sla_paused_at", "resolve_due_at"],
    )
    op.create_index(
        "ix_notifications_recipient_created_id",
        "notifications",
        ["recipient_user_id", "created_at", "id"],
    )


def downgrade():
    op.drop_index("ix_notifications_recipient_created_id", table_name="notifications")
    op.drop_index("ix_tickets_status_paused_resolve_due", table_name="tickets")
    op.drop_index("ix_tickets_collab_status_created", table_name="tickets")
    op.drop_index("ix_tickets_status_updated", table_name="tickets")
    op.drop_index("ix_tickets_assignee_status_created", table_name="tickets")
    op.drop_index("ix_tickets_dept_status_created", table_name="tickets")
    op.drop_index("ix_kb_chunks_content_trgm", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_embedding_hnsw", table_name="kb_chunks")
