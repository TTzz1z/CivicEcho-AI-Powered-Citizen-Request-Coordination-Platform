"""Track ownership and expiry of an in-progress knowledge base index build."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kb_documents", sa.Column("index_lease_token", sa.String(64), nullable=True))
    op.add_column("kb_documents", sa.Column("index_lease_until", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("kb_documents", "index_lease_until")
    op.drop_column("kb_documents", "index_lease_token")
