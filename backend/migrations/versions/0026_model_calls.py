"""Persist shared model admission across backend processes."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
    )
    op.create_index("ix_model_calls_created_at", "model_calls", ["created_at"])


def downgrade():
    op.drop_table("model_calls")
