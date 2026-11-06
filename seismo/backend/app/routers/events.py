from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import can_write, current_user
from ..models import ImportFile, SeismicEvent, Station, User
from ..schemas import EventDetail, EventUpdate, Page
from ..services.exporter import build_workbook
from ..services.queries import SORTABLE, EventFilter, apply_filters, event_filter, to_event_out

router = APIRouter(prefix="/api/events", tags=["events"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("", response_model=Page)
def list_events(f: EventFilter = Depends(event_filter), page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=500), sort: str = "date", order: str = Query("desc", pattern="^(asc|desc)$"),
                db: Session = Depends(get_db), _: User = Depends(current_user)):
    if sort not in SORTABLE:
        raise HTTPException(422, f"Сортировка по «{sort}» недоступна")
    total = db.scalar(apply_filters(select(func.count(SeismicEvent.id)), f)) or 0
    col = SORTABLE[sort]
    primary = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    stmt = apply_filters(select(SeismicEvent), f).order_by(
        primary, SeismicEvent.event_date.desc() if order == "desc" else SeismicEvent.event_date.asc(),
        SeismicEvent.p_time.desc() if order == "desc" else SeismicEvent.p_time.asc(), SeismicEvent.id)
    rows = db.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).unique().all()
    return {"items": [to_event_out(e) for e in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/export.xlsx")
def export_events(request: Request, f: EventFilter = Depends(event_filter), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    events = db.scalars(apply_filters(select(SeismicEvent), f).order_by(
        SeismicEvent.event_date, SeismicEvent.p_time, Station.code, SeismicEvent.id)).unique().all()
    codes = sorted({e.station.code for e in events})
    names = {s.code: s.name for s in db.scalars(select(Station))}
    stations = [(c, names.get(c)) for c in (f.stations or codes) if c in names] or [(c, names.get(c)) for c in codes]
    bytes_ = build_workbook("Выгрузка сейсмологических записей", f.date_from, f.date_to, stations, events)
    audit.log(db, "events_export", user, request, details={"rows": len(events)})
    db.commit()
    name = f"seismic_events_{datetime.now(timezone.utc):%Y%m%d_%H%M}.xlsx"
    return Response(bytes_, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _get(db: Session, event_id: int) -> SeismicEvent:
    e = db.get(SeismicEvent, event_id)
    if not e:
        raise HTTPException(404, "Запись не найдена")
    return e


@router.get("/{event_id}", response_model=EventDetail)
def get_event(event_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    e = _get(db, event_id)
    d = to_event_out(e)
    d.update(file_id=e.file_id, source_row=e.source_row, source_sheet=e.source_sheet, raw=e.raw, record_hash=e.record_hash,
             created_at=e.created_at, updated_at=e.updated_at,
             file_name=db.scalar(select(ImportFile.original_name).where(ImportFile.id == e.file_id)) if e.file_id else None)
    return d


@router.patch("/{event_id}", response_model=EventDetail)
def update_event(event_id: int, data: EventUpdate, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(can_write)):
    e = _get(db, event_id)
    changes = {}
    for field in data.model_fields_set:
        new = getattr(data, field)
        if field == "event_date" and new is None:
            raise HTTPException(422, "Дата не может быть пустой")
        if getattr(e, field) != new:
            changes[field] = [str(getattr(e, field)), str(new)]
            setattr(e, field, new)
    if "needs_review" in changes and not e.needs_review:
        e.review_reasons = []
    elif e.needs_review and not e.review_reasons:
        e.review_reasons = ["manual"]
    if changes:
        e.updated_at, e.updated_by = datetime.now(timezone.utc), user.id
        audit.log(db, "event_updated", user, request, "event", e.id, changes)
    db.commit()
    return get_event(event_id, db, user)


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(can_write)):
    e = _get(db, event_id)
    audit.log(db, "event_deleted", user, request, "event", e.id,
              {"station": e.station.code, "date": str(e.event_date), "p_time": str(e.p_time), "raw": e.raw})
    db.delete(e)
    db.commit()
