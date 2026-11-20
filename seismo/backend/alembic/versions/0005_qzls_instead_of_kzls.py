"""исправление списка станций: QZLS вместо KZLS

В миграции 0004 по ошибке была добавлена KZLS; правильный код — QZLS.
KZLS удаляется только если на ней нет записей (данные не теряются). Идемпотентно.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ADD, REMOVE = "QZLS", "KZLS"
_NO_EVENTS = "id NOT IN (SELECT station_id FROM seismic_events)"


def swap(conn, add: str, remove: str) -> None:
    conn.execute(sa.text("INSERT INTO stations (code) VALUES (:c) ON CONFLICT (code) DO NOTHING"), {"c": add})
    conn.execute(sa.text(f"DELETE FROM stations WHERE code = :c AND {_NO_EVENTS}"), {"c": remove})


def upgrade() -> None:
    swap(op.get_bind(), ADD, REMOVE)


def downgrade() -> None:
    swap(op.get_bind(), REMOVE, ADD)
