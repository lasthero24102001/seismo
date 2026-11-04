from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import current_user
from ..models import SeismicEvent, Station, User
from ..services.exporter import build_workbook
from ..services.queries import EventFilter, apply_filters, to_event_out
from .events import XLSX

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _resolve(db: Session, year: int | None, date_from: date | None, date_to: date | None, stations: str | None):
    if year and not date_from and not date_to:
        date_from, date_to = date(year, 1, 1), date(year, 12, 31)
    if not date_from or not date_to:
        raise HTTPException(422, "Укажите год либо начальную и конечную даты")
    if date_from > date_to:
        raise HTTPException(422, "Начальная дата позже конечной")
    codes = [c.strip().upper() for c in stations.split(",") if c.strip()] if stations else []
    sts = list(db.scalars(select(Station).where(Station.code.in_(codes) if codes else Station.is_active)
                          .order_by(Station.code)))
    if codes and len(sts) != len(set(codes)):
        unknown = sorted(set(codes) - {s.code for s in sts})
        raise HTTPException(422, f"Неизвестные станции: {', '.join(unknown)}")
    return date_from, date_to, sts


def _title(year: int | None, d0: date, d1: date) -> str:
    return f"Сейсмологический отчёт за {d0:%d.%m.%Y} – {d1:%d.%m.%Y}"


def _query(sts: list[Station], d0: date, d1: date):
    f = EventFilter(stations=[s.code for s in sts], date_from=d0, date_to=d1)
    return apply_filters(select(SeismicEvent), f).order_by(
        SeismicEvent.event_date, SeismicEvent.p_time, Station.code, SeismicEvent.id), f


@router.get("")
def report(year: int | None = Query(None, ge=1900, le=2200), date_from: date | None = None, date_to: date | None = None,
           stations: str | None = None, limit: int = Query(5000, ge=1, le=50000),
           db: Session = Depends(get_db), _: User = Depends(current_user)):
    d0, d1, sts = _resolve(db, year, date_from, date_to, stations)
    stmt, f = _query(sts, d0, d1)
    counts = dict(db.execute(apply_filters(select(Station.code, func.count(SeismicEvent.id)), f).group_by(Station.code)).all())
    total = sum(counts.values())
    events = db.scalars(stmt.limit(limit)).unique().all() if total else []
    return {
        "title": _title(year, d0, d1),
        "period": {"year": year, "date_from": d0, "date_to": d1},
        "generated_at": datetime.now(), "total": total, "truncated": total > len(events),
        "stations": [{"code": s.code, "name": s.name, "count": counts.get(s.code, 0)} for s in sts],
        "events": [to_event_out(e) for e in events],
        "message": None if total else "За выбранный период данных по выбранным станциям нет",
    }


@router.get("/export.xlsx")
def export(request: Request, year: int | None = Query(None, ge=1900, le=2200), date_from: date | None = None,
           date_to: date | None = None, stations: str | None = None,
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    d0, d1, sts = _resolve(db, year, date_from, date_to, stations)
    stmt, _ = _query(sts, d0, d1)
    events = db.scalars(stmt).unique().all()
    content = build_workbook(_title(year, d0, d1), d0, d1, [(s.code, s.name) for s in sts], events)
    audit.log(db, "report_export", user, request, details={
        "from": str(d0), "to": str(d1), "stations": [s.code for s in sts], "rows": len(events)})
    db.commit()
    name = f"seismic_report_{d0:%Y%m%d}_{d1:%Y%m%d}.xlsx"
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
