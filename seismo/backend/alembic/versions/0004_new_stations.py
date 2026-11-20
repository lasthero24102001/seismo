"""новые станции: SNGR, YANG, TSHT, SKHM, NZB, NAN, NUR, MAM, KZLS, FRSH, DJAN, BOLG, AGAL, BKHM

Названия станций пока не заданы (заполняются в разделе «Сейсмостанции»).
Миграция идемпотентна: уже существующие станции не затрагиваются.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NEW_STATIONS = ["SNGR", "YANG", "TSHT", "SKHM", "NZB", "NAN", "NUR", "MAM", "KZLS", "FRSH", "DJAN", "BOLG", "AGAL", "BKHM"]


def insert_stations(conn) -> None:
    conn.execute(sa.text("INSERT INTO stations (code) VALUES (:c) ON CONFLICT (code) DO NOTHING"),
                 [{"c": c} for c in NEW_STATIONS])


def upgrade() -> None:
    insert_stations(op.get_bind())


def downgrade() -> None:
    # удаляются только станции без записей — данные не теряются
    op.get_bind().execute(
        sa.text("DELETE FROM stations WHERE code = ANY(:codes) AND id NOT IN (SELECT station_id FROM seismic_events)"),
        {"codes": NEW_STATIONS})
