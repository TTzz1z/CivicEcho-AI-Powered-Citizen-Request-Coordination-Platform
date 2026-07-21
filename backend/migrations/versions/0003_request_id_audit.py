"""add request id to audit log

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("request_id", sa.String(64)))
    op.create_index("ix_audit_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_request_id", table_name="audit_logs")
    op.drop_column("audit_logs", "request_id")
