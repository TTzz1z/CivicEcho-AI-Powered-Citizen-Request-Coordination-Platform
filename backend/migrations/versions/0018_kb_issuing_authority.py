"""Add issuing_authority column to kb_documents.

Revision ID: 0018_kb_issuing_authority
Revises: 0017

Adds:
- issuing_authority: 发布单位（例如"市城市管理行政执法局"），可选字段，
  用于在 citations 中返回完整的发布单位信息，与 doc_number 互补。
  回退顺序：issuing_authority -> published_department_name -> department_name。

Backwards compatible: nullable column; existing rows remain valid.
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_kb_issuing_authority"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_documents", sa.Column("issuing_authority", sa.String(200)))


def downgrade() -> None:
    op.drop_column("kb_documents", "issuing_authority")
