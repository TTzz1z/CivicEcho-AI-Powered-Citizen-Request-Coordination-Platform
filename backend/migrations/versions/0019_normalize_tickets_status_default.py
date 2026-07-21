"""Normalize tickets.status server_default to English 'pending'.

Revision ID: 0019
Revises: 0018_kb_issuing_authority

Background:
- 0001 created tickets.status with server_default="待受理" (Chinese).
- 0002 added a CHECK constraint requiring English status values
  ('pending','accepted','assigned','processing','resolved','closed','rejected')
  and migrated existing rows to English, but did NOT change the server_default.
- As a result, the column has a Chinese default that would violate the CHECK
  constraint if any INSERT ever relied on it.

This migration:
1. Alters tickets.status server_default to 'pending'.
2. Defensively maps any stray Chinese status values to English
   (idempotent — no-op if already clean).

Backwards compatible: no application code change required.
"""
from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018_kb_issuing_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Normalize any stray Chinese status values to English (idempotent).
    op.execute("""
        UPDATE tickets SET status = CASE status
          WHEN '待受理' THEN 'pending'
          WHEN '受理中' THEN 'accepted'
          WHEN '处理中' THEN 'processing'
          WHEN '已办结' THEN 'closed'
          WHEN '已关闭' THEN 'closed'
          WHEN '不予受理' THEN 'rejected'
          ELSE status END
    """)
    # 2) Fix server_default to English 'pending'.
    op.alter_column(
        "tickets", "status",
        existing_type=sa.String(32),
        existing_nullable=False,
        server_default="pending",
    )


def downgrade() -> None:
    # Restore the previous (buggy) Chinese default. We deliberately keep this
    # for symmetry, but it should never be exercised in production.
    op.alter_column(
        "tickets", "status",
        existing_type=sa.String(32),
        existing_nullable=False,
        server_default="待受理",
    )
