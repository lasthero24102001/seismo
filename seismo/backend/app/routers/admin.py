import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import admin_only, current_user
from ..models import AuditLog, User
from ..services.reasons import REASON_LABELS, reason_text

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/meta/review-reasons")
def reasons(_: User = Depends(current_user)):
    return {"labels": REASON_LABELS}


@router.get("/meta/reason/{code}")
def reason(code: str, _: User = Depends(current_user)):
    return {"code": code, "text": reason_text(code)}


@router.get("/admin/audit")
def audit_log(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), action: str | None = None,
              db: Session = Depends(get_db), _: User = Depends(admin_only)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return {"total": total, "items": [{c: getattr(a, c) for c in (
        "id", "created_at", "username", "action", "entity_type", "entity_id", "details", "ip")} for a in items]}


def _bdir() -> Path:
    p = Path(get_settings().backup_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.get("/admin/backups")
def list_backups(_: User = Depends(admin_only)):
    return [{"name": f.name, "size": f.stat().st_size,
             "created_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)}
            for f in sorted(_bdir().glob("*.dump"), reverse=True)]


@router.post("/admin/backups", status_code=201)
def create_backup(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    url = make_url(get_settings().database_url)
    name = f"seismo_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.dump"
    cmd = ["pg_dump", "-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "",
           "-d", url.database or "", "-Fc", "-f", str(_bdir() / name)]
    try:
        r = subprocess.run(cmd, env={**os.environ, "PGPASSWORD": url.password or ""}, capture_output=True, text=True,
                           timeout=600)
    except FileNotFoundError:
        raise HTTPException(500, "pg_dump не найден в окружении backend")
    if r.returncode != 0:
        raise HTTPException(500, f"Ошибка резервного копирования: {r.stderr.strip()[:300]}")
    audit.log(db, "backup_created", user, request, details={"file": name})
    db.commit()
    return {"name": name}


@router.get("/admin/backups/{name}")
def download_backup(name: str, _: User = Depends(admin_only)):
    if not re.fullmatch(r"seismo_\d{8}_\d{6}\.dump", name):
        raise HTTPException(404, "Файл не найден")
    p = _bdir() / name
    if not p.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(p, filename=name, media_type="application/octet-stream")
