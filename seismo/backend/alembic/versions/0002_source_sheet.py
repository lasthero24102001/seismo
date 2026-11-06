"""лист-источник записи (для многолистовых Excel-файлов)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seismic_events", sa.Column("source_sheet", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("seismic_events", "source_sheet")
