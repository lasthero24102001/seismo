import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import admin_only, can_write, current_user
from ..models import SeismicEvent, Station, User
from ..schemas import StationCreate, StationOut, StationStats, StationUpdate

router = APIRouter(prefix="/api/stations", tags=["stations"])


def _clean_aliases(aliases: list[str] | None) -> list[str]:
    return sorted({a.strip().upper() for a in (aliases or []) if a.strip()})


def _ensure_free(db: Session, codes: list[str], exclude_id: int | None = None) -> None:
    for st in db.scalars(select(Station)):
        if st.id == exclude_id:
            continue
        taken = {st.code.upper(), *(a.upper() for a in st.aliases or [])}
        clash = taken.intersection(codes)
        if clash:
            raise HTTPException(409, f"Код/алиас {', '.join(sorted(clash))} уже используется станцией {st.code}")


@router.get("", response_model=list[StationStats])
def list_stations(db: Session = Depends(get_db), _: User = Depends(current_user)):
    agg = {r.station_id: r for r in db.execute(
        select(SeismicEvent.station_id, func.count().label("n"),
               func.count().filter(SeismicEvent.needs_review).label("fl"),
               func.min(SeismicEvent.event_date).label("d0"), func.max(SeismicEvent.event_date).label("d1"))
        .group_by(SeismicEvent.station_id))}
    out = []
    for st in db.scalars(select(Station).order_by(Station.code)):
        a = agg.get(st.id)
        out.append(StationStats(id=st.id, code=st.code, name=st.name, aliases=st.aliases, is_active=st.is_active,
                                events_count=a.n if a else 0, flagged_count=a.fl if a else 0,
                                first_date=a.d0 if a else None, last_date=a.d1 if a else None))
    return out


@router.post("", response_model=StationOut, status_code=201)
def create_station(data: StationCreate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(can_write)):
    code = data.code.upper()
    aliases = _clean_aliases(data.aliases)
    _ensure_free(db, [code, *aliases])
    st = Station(code=code, name=(data.name or None), aliases=aliases)
    db.add(st)
    db.flush()
    audit.log(db, "station_created", user, request, "station", st.id, {"code": code})
    db.commit()
    return st


class StationBulk(BaseModel):
    codes: str = Field(min_length=1, max_length=5000, description="коды через запятую, пробел или перевод строки")


@router.post("/bulk")
def bulk_create(data: StationBulk, request: Request, db: Session = Depends(get_db), user: User = Depends(can_write)):
    """Добавить несколько станций списком. Существующие пропускаются, некорректные коды возвращаются в ответе."""
    taken: dict[str, str] = {}
    for st in db.scalars(select(Station)):
        taken[st.code.upper()] = st.code
        for a in st.aliases or []:
            taken[a.upper()] = st.code
    created, skipped, invalid, seen = [], [], [], set()
    for tok in (t for t in re.split(r"[\s,;]+", data.codes.upper()) if t):
        if tok in seen:
            continue
        seen.add(tok)
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", tok):
            invalid.append(tok)
        elif tok in taken:
            skipped.append({"code": tok, "station": taken[tok]})
        else:
            db.add(Station(code=tok, aliases=[]))
            taken[tok] = tok
            created.append(tok)
    if created:
        audit.log(db, "stations_bulk_created", user, request, details={"codes": created})
    db.commit()
    return {"created": created, "skipped": skipped, "invalid": invalid}


@router.patch("/{station_id}", response_model=StationOut)
def update_station(station_id: int, data: StationUpdate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(can_write)):
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(404, "Станция не найдена")
    ch = {}
    if "name" in data.model_fields_set:
        st.name = (data.name or "").strip() or None
        ch["name"] = st.name
    if data.aliases is not None:
        al = _clean_aliases(data.aliases)
        _ensure_free(db, al, exclude_id=st.id)
        st.aliases, ch["aliases"] = al, al
    if data.is_active is not None:
        st.is_active, ch["is_active"] = data.is_active, data.is_active
    audit.log(db, "station_updated", user, request, "station", st.id, ch)
    db.commit()
    return st


@router.delete("/{station_id}", status_code=204)
def delete_station(station_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    st = db.get(Station, station_id)
    if not st:
        raise HTTPException(404, "Станция не найдена")
    try:
        audit.log(db, "station_deleted", user, request, "station", st.id, {"code": st.code})
        db.delete(st)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "У станции есть события — удаление невозможно. Деактивируйте станцию")
