"""станция файла, заданная вручную при импорте

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
    op.add_column("import_files", sa.Column("station_hint", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("import_files", "station_hint")
