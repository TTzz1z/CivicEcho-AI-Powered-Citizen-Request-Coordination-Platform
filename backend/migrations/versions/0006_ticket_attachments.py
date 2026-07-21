"""phase 3 ticket attachment metadata

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("uploader_role", sa.String(32), nullable=False),
        sa.Column("uploader_department_id", sa.BigInteger(), sa.ForeignKey("departments.id", ondelete="SET NULL")),
        sa.Column("attachment_type", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_provider", sa.String(32), nullable=False, server_default="s3"),
        sa.Column("storage_bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("scan_status", sa.String(16), nullable=False),
        sa.Column("scan_engine", sa.String(64)),
        sa.Column("scan_detail", sa.String(500)),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("delete_reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "attachment_type IN ('citizen_material','site_photo','official_document','processing_proof','other')",
            name="ck_ticket_attachments_type",
        ),
        sa.CheckConstraint("visibility IN ('public','internal')", name="ck_ticket_attachments_visibility"),
        sa.CheckConstraint("scan_status IN ('clean','skipped')", name="ck_ticket_attachments_scan_status"),
        sa.CheckConstraint("size_bytes > 0", name="ck_ticket_attachments_size"),
        sa.UniqueConstraint("object_key", name="uq_ticket_attachments_object_key"),
    )
    op.create_index("ix_ticket_attachments_ticket_created", "ticket_attachments", ["ticket_id", "created_at"])
    op.create_index("ix_ticket_attachments_uploader", "ticket_attachments", ["uploader_user_id", "created_at"])
    op.create_index("ix_ticket_attachments_scan_status", "ticket_attachments", ["scan_status"])


def downgrade() -> None:
    op.drop_index("ix_ticket_attachments_scan_status", table_name="ticket_attachments")
    op.drop_index("ix_ticket_attachments_uploader", table_name="ticket_attachments")
    op.drop_index("ix_ticket_attachments_ticket_created", table_name="ticket_attachments")
    op.drop_table("ticket_attachments")
