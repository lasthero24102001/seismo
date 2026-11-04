from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("role in ('admin','operator','viewer')", name="ck_users_role"),)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 токена
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str | None] = mapped_column(String(128))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list, server_default=text("'{}'"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview|committed|failed|cancelled
    files_count: Mapped[int] = mapped_column(Integer, default=0)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    rows_flagged: Mapped[int] = mapped_column(Integer, default=0)
    files: Mapped[list["ImportFile"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class ImportFile(Base):
    __tablename__ = "import_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"))
    station_code: Mapped[str | None] = mapped_column(String(16))
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_type: Mapped[str] = mapped_column(String(8))  # xlsx|pdf
    parse_method: Mapped[str | None] = mapped_column(String(16))  # excel|pdf_table|pdf_text|pdf_ocr
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    rows_flagged: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview|imported|failed
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    batch: Mapped[ImportBatch] = relationship(back_populates="files")


class ImportIssue(Base):
    __tablename__ = "import_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("import_files.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(8))  # error|warning|info
    code: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    raw: Mapped[list | dict | None] = mapped_column(JSONB)


class SeismicEvent(Base):
    __tablename__ = "seismic_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id", ondelete="RESTRICT"))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("import_files.id", ondelete="SET NULL"))
    source_no: Mapped[int | None] = mapped_column(Integer)
    source_row: Mapped[int | None] = mapped_column(Integer)
    event_date: Mapped[date] = mapped_column(Date)
    p_phase: Mapped[str | None] = mapped_column(String(8))
    p_time: Mapped[time | None] = mapped_column(TIME(precision=1))
    s_phase: Mapped[str | None] = mapped_column(String(8))
    s_time: Mapped[time | None] = mapped_column(TIME(precision=1))
    origin_time: Mapped[time | None] = mapped_column(TIME(precision=1))
    s_minus_p: Mapped[Decimal | None] = mapped_column(Numeric)
    r_km: Mapped[Decimal | None] = mapped_column(Numeric)
    amp_p: Mapped[Decimal | None] = mapped_column(Numeric)
    amp_s: Mapped[Decimal | None] = mapped_column(Numeric)
    mb: Mapped[Decimal | None] = mapped_column(Numeric)
    ml: Mapped[Decimal | None] = mapped_column(Numeric)
    ep_vp: Mapped[Decimal | None] = mapped_column(Numeric)
    ep_vs: Mapped[Decimal | None] = mapped_column(Numeric)
    ep_vp_vs: Mapped[Decimal | None] = mapped_column(Numeric)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    review_reasons: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default=text("'{}'"))
    review_comment: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[list | dict | None] = mapped_column(JSONB)
    record_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    station: Mapped[Station] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("station_id", "record_hash", name="uq_event_station_hash"),
        CheckConstraint("r_km is null or r_km >= 0", name="ck_event_r_nonneg"),
        CheckConstraint("s_minus_p is null or s_minus_p >= 0", name="ck_event_sp_nonneg"),
        CheckConstraint("amp_p is null or amp_p >= 0", name="ck_event_ap_nonneg"),
        CheckConstraint("amp_s is null or amp_s >= 0", name="ck_event_as_nonneg"),
        Index("ix_event_date", "event_date"),
        Index("ix_event_station_date", "station_id", "event_date"),
        Index("ix_event_mb", "mb"),
        Index("ix_event_ml", "ml"),
        Index("ix_event_r", "r_km"),
        Index("ix_event_review", "needs_review", postgresql_where=text("needs_review")),
        Index("ix_event_key", "station_id", "event_date", "p_time"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
