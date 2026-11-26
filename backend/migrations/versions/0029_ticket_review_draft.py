"""Isolate unpublished ticket replies and index expired notification deliveries."""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("review_draft", sa.JSON(), nullable=True))
    op.execute("""
        UPDATE tickets
        SET review_draft = json_build_object(
                'resolution_summary', resolution_summary,
                'resolution_measures', resolution_measures,
                'resolution_outcome', resolution_outcome,
                'public_reply', public_reply,
                'internal_note', internal_note),
            resolution_summary = NULL, resolution_measures = NULL,
            resolution_outcome = NULL, public_reply = NULL, internal_note = NULL
        WHERE collaboration_status = 'awaiting_review'
          AND status IN ('assigned', 'processing')
          AND resolution_summary IS NOT NULL AND resolution_measures IS NOT NULL
          AND resolution_outcome IS NOT NULL AND public_reply IS NOT NULL
    """)
    op.execute("""
        UPDATE tickets
        SET status = 'processing', version = version + 1
        WHERE status = 'assigned' AND collaboration_status = 'awaiting_review'
    """)
    op.execute("""
        UPDATE ticket_status_history SET visibility = 'internal'
        WHERE operation_type = 'submit_for_review' AND visibility = 'public'
    """)
    op.create_index("ix_outbox_status_created", "notification_outbox", ["status", "created_at"])


def downgrade():
    op.drop_index("ix_outbox_status_created", table_name="notification_outbox")
    op.execute("""
        UPDATE tickets
        SET resolution_summary = review_draft ->> 'resolution_summary',
            resolution_measures = review_draft ->> 'resolution_measures',
            resolution_outcome = review_draft ->> 'resolution_outcome',
            public_reply = review_draft ->> 'public_reply',
            internal_note = review_draft ->> 'internal_note'
        WHERE collaboration_status = 'awaiting_review' AND review_draft IS NOT NULL
    """)
    op.drop_column("tickets", "review_draft")
