"""Store chunk provenance and reproducible evaluation measurements."""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("kb_chunks", sa.Column("source_metadata", sa.Text(), nullable=True))
    op.add_column("kb_eval_runs", sa.Column("metrics_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("kb_eval_runs", "metrics_json")
    op.drop_column("kb_chunks", "source_metadata")
