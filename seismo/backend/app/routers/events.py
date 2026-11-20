from datetime import date, datetime, time, timezone
from decimal import Decimal
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import can_write, current_user
from ..models import AuditLog, ImportFile, SeismicEvent, Station, User
from ..schemas import EventDetail, EventUpdate, Page
from ..services.exporter import build_workbook
from ..services.parsing import NUM_FIELDS, ParsedRow, validate_row
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


# Проверки, которые можно пересчитать по самим значениям записи после правки
VALUE_CHECKS = {"time_order", "sp_mismatch", "mag_range", "amp_range", "vel_range", "vpvs_range", "dist_range",
                "date_future"}


def _fmt(v):
    """Значение для журнала изменений в читаемом виде."""
    if v is None:
        return None
    if isinstance(v, time):
        return f"{v:%H:%M:%S}.{v.microsecond // 100000}"
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def recompute_reasons(e: SeismicEvent, old: list[str], changed: set[str]) -> list[str]:
    """Причины пометки после правки: проверки по значениям пересчитываются заново; «значение отсутствует/не распознано»
    снимается, если поле теперь заполнено; контекстные пометки (OCR, дубль, выброс даты) сохраняются, пока не изменено
    то, на чём они основаны. Новые «значение отсутствует» не добавляются."""
    row = ParsedRow(source_row=0, raw=[], event_date=e.event_date, p_phase=e.p_phase, s_phase=e.s_phase,
                    p_time=e.p_time, s_time=e.s_time, origin_time=e.origin_time,
                    nums={f: getattr(e, f) for f in NUM_FIELDS})
    validate_row(row)
    keep = []
    for r in old:
        if r in VALUE_CHECKS:
            continue
        kind, _, fld = r.partition(":")
        if kind in ("missing", "parse", "excel_error") and fld and getattr(e, fld, None) is not None:
            continue
        if r == "date_outlier" and "event_date" in changed:
            continue
        if r == "near_duplicate" and {"event_date", "p_time"} & changed:
            continue
        keep.append(r)
    return list(dict.fromkeys(keep + [x for x in row.flags if x in VALUE_CHECKS]))


@router.patch("/{event_id}", response_model=EventDetail)
def update_event(event_id: int, data: EventUpdate, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(can_write)):
    e = _get(db, event_id)
    old_needs, old_reasons = e.needs_review, list(e.review_reasons or [])
    sent = data.model_fields_set
    changes: dict = {}
    for field in sent - {"needs_review", "station_code", "review_comment"}:
        new = getattr(data, field)
        if isinstance(new, str):
            new = new.strip() or None
        if field == "event_date" and new is None:
            raise HTTPException(422, "Дата не может быть пустой")
        if getattr(e, field) != new:
            changes[field] = [_fmt(getattr(e, field)), _fmt(new)]
            setattr(e, field, new)
    if data.station_code:
        code = data.station_code.strip().upper()
        st = next((x for x in db.scalars(select(Station)) if code == x.code.upper() or code in (x.aliases or [])), None)
        if st is None:
            raise HTTPException(422, f"Станция «{code}» не найдена в справочнике")
        if st.id != e.station_id:
            changes["station"] = [e.station.code, st.code]
            e.station_id, e.station = st.id, st
    if "review_comment" in sent and (data.review_comment or None) != e.review_comment:
        changes["review_comment"] = [e.review_comment, data.review_comment or None]
        e.review_comment = data.review_comment or None

    reasons = recompute_reasons(e, old_reasons, set(changes)) if (set(changes) - {"review_comment"}) else old_reasons
    if data.needs_review is not None:                    # статус задан пользователем явно
        needs = data.needs_review
        reasons = (reasons or ["manual"]) if needs else []
    else:                                                # иначе — по результату проверок
        needs = bool(reasons)
    e.needs_review, e.review_reasons = needs, reasons
    if (needs, reasons) != (old_needs, old_reasons):
        changes["needs_review"] = [old_needs, needs]
        changes["review_reasons"] = [old_reasons, reasons]

    if changes:
        e.updated_at, e.updated_by = datetime.now(timezone.utc), user.id
        audit.log(db, "event_updated", user, request, "event", e.id, changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "В выбранной станции уже есть точно такая же запись")
    return get_event(event_id, db, user)


@router.get("/{event_id}/history")
def event_history(event_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Кто, когда и что менял в записи (было → стало)."""
    _get(db, event_id)
    rows = db.scalars(select(AuditLog).where(
        AuditLog.entity_type == "event", AuditLog.entity_id == str(event_id), AuditLog.action == "event_updated")
        .order_by(AuditLog.id.desc()).limit(50)).all()
    return [{"id": a.id, "created_at": a.created_at, "username": a.username, "changes": a.details or {}} for a in rows]


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(can_write)):
    e = _get(db, event_id)
    audit.log(db, "event_deleted", user, request, "event", e.id,
              {"station": e.station.code, "date": str(e.event_date), "p_time": str(e.p_time), "raw": e.raw})
    db.delete(e)
    db.commit()
