from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import ImportBatch, ImportFile, SeismicEvent, Station, User
from ..services.queries import to_event_out

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(date_from: date | None = None, date_to: date | None = None, exclude_flagged: bool = True,
              db: Session = Depends(get_db), _: User = Depends(current_user)):
    E = SeismicEvent
    today = date.today()
    cnt = lambda *w: db.scalar(select(func.count(E.id)).where(*w)) or 0  # noqa: E731
    lo, hi = db.execute(select(func.min(E.event_date), func.max(E.event_date))).one()
    d0, d1 = date_from or lo, date_to or hi
    period = [E.event_date >= d0, E.event_date <= d1] if d0 and d1 else [E.id < 0]
    mag_filter = period + ([E.needs_review.is_(False)] if exclude_flagged else [])

    by_month = db.execute(select(func.to_char(E.event_date, "YYYY-MM").label("m"), func.count())
                          .group_by("m").order_by("m")).all()
    by_station = db.execute(select(Station.code, func.count(E.id)).join(E, E.station_id == Station.id)
                            .where(*period).group_by(Station.code).order_by(func.count(E.id).desc())).all()
    daily = db.execute(select(E.event_date, func.count()).where(*period).group_by(E.event_date)
                       .order_by(E.event_date)).all()
    mags = db.execute(select(E.event_date, func.avg(E.mb), func.avg(E.ml), func.max(E.mb), func.max(E.ml),
                             func.count(E.mb)).where(*mag_filter).group_by(E.event_date)
                      .order_by(E.event_date)).all()
    recent_imports = db.execute(
        select(ImportFile, ImportBatch.committed_at).join(ImportBatch, ImportBatch.id == ImportFile.batch_id)
        .where(ImportFile.status == "imported").order_by(ImportFile.id.desc()).limit(8)).all()
    recent_events = db.scalars(select(E).order_by(E.event_date.desc(), E.p_time.desc().nulls_last(), E.id.desc())
                               .limit(10)).unique().all()
    r1 = lambda v: None if v is None else round(float(v), 2)  # noqa: E731
    return {
        "totals": {
            "events": cnt(), "stations_with_data": db.scalar(select(func.count(func.distinct(E.station_id)))) or 0,
            "stations_total": db.scalar(select(func.count(Station.id))) or 0,
            "events_month": cnt(func.date_trunc("month", E.event_date) == date(today.year, today.month, 1)),
            "events_year": cnt(func.extract("year", E.event_date) == today.year),
            "flagged": cnt(E.needs_review), "today": today, "first_date": lo, "last_date": hi,
            "events_in_period": cnt(*period),
        },
        "period": {"date_from": d0, "date_to": d1}, "exclude_flagged": exclude_flagged,
        "by_month": [{"month": m, "count": n} for m, n in by_month],
        "by_station": [{"station": c, "count": n} for c, n in by_station],
        "daily": [{"date": d, "count": n} for d, n in daily],
        "magnitude": [{"date": d, "mb_avg": r1(a), "ml_avg": r1(b), "mb_max": r1(c), "ml_max": r1(e), "n": n}
                      for d, a, b, c, e, n in mags],
        "recent_imports": [{"file": f.original_name, "station": f.station_code, "rows_imported": f.rows_imported,
                            "rows_duplicate": f.rows_duplicate, "rows_flagged": f.rows_flagged,
                            "imported_at": at} for f, at in recent_imports],
        "recent_events": [to_event_out(e) for e in recent_events],
    }
