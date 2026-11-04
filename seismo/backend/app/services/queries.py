"""Общие фильтры для таблицы событий, отчётов и экспорта."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, Query
from sqlalchemy import Select, extract, or_
from sqlalchemy.orm import Session

from ..models import SeismicEvent, Station

SORTABLE = {
    "station": Station.code, "date": SeismicEvent.event_date, "p_time": SeismicEvent.p_time,
    "s_time": SeismicEvent.s_time, "origin_time": SeismicEvent.origin_time, "s_minus_p": SeismicEvent.s_minus_p,
    "r_km": SeismicEvent.r_km, "amp_p": SeismicEvent.amp_p, "amp_s": SeismicEvent.amp_s, "mb": SeismicEvent.mb,
    "ml": SeismicEvent.ml, "ep_vp": SeismicEvent.ep_vp, "ep_vs": SeismicEvent.ep_vs,
    "ep_vp_vs": SeismicEvent.ep_vp_vs, "no": SeismicEvent.source_no,
}


@dataclass
class EventFilter:
    stations: list[str] | None = None
    q: str | None = None
    year: int | None = None
    month: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    mb_min: Decimal | None = None
    mb_max: Decimal | None = None
    ml_min: Decimal | None = None
    ml_max: Decimal | None = None
    r_min: Decimal | None = None
    r_max: Decimal | None = None
    needs_review: bool | None = None


def event_filter(
    stations: str | None = Query(None, description="коды через запятую"),
    q: str | None = Query(None, max_length=32),
    year: int | None = Query(None, ge=1900, le=2200), month: int | None = Query(None, ge=1, le=12),
    date_from: date | None = None, date_to: date | None = None,
    mb_min: Decimal | None = None, mb_max: Decimal | None = None,
    ml_min: Decimal | None = None, ml_max: Decimal | None = None,
    r_min: Decimal | None = None, r_max: Decimal | None = None,
    needs_review: bool | None = None,
) -> EventFilter:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Начальная дата позже конечной")
    codes = [c.strip().upper() for c in stations.split(",") if c.strip()] if stations else None
    return EventFilter(codes, q, year, month, date_from, date_to, mb_min, mb_max, ml_min, ml_max,
                       r_min, r_max, needs_review)


def apply_filters(stmt: Select, f: EventFilter) -> Select:
    stmt = stmt.join(Station, Station.id == SeismicEvent.station_id)
    if f.stations:
        stmt = stmt.where(Station.code.in_(f.stations))
    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.where(or_(Station.code.ilike(like), Station.name.ilike(like)))
    if f.year:
        stmt = stmt.where(extract("year", SeismicEvent.event_date) == f.year)
    if f.month:
        stmt = stmt.where(extract("month", SeismicEvent.event_date) == f.month)
    if f.date_from:
        stmt = stmt.where(SeismicEvent.event_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(SeismicEvent.event_date <= f.date_to)
    for col, lo, hi in ((SeismicEvent.mb, f.mb_min, f.mb_max), (SeismicEvent.ml, f.ml_min, f.ml_max),
                        (SeismicEvent.r_km, f.r_min, f.r_max)):
        if lo is not None:
            stmt = stmt.where(col >= lo)
        if hi is not None:
            stmt = stmt.where(col <= hi)
    if f.needs_review is not None:
        stmt = stmt.where(SeismicEvent.needs_review == f.needs_review)
    return stmt


def to_event_out(e: SeismicEvent) -> dict:
    d = {c: getattr(e, c) for c in (
        "id", "source_no", "event_date", "p_phase", "p_time", "s_phase", "s_time", "origin_time", "s_minus_p",
        "r_km", "amp_p", "amp_s", "mb", "ml", "ep_vp", "ep_vs", "ep_vp_vs", "needs_review", "review_reasons",
        "review_comment")}
    d["station_code"], d["station_name"] = e.station.code, e.station.name
    return d
