"""Add token_version to users for immediate JWT revocation on logout or credential changes."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("users", "token_version")
