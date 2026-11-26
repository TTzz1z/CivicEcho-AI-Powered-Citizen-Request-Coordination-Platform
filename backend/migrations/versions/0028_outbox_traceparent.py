"""Persist trace context for asynchronous notification delivery."""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_outbox", sa.Column("traceparent", sa.String(55), nullable=True))


def downgrade():
    op.drop_column("notification_outbox", "traceparent")
