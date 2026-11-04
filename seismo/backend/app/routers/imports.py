import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import can_write, current_user
from ..models import ImportBatch, ImportFile, ImportIssue, User
from ..services import importer
from ..services.parsing import NUM_FIELDS

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _file_out(f: ImportFile) -> dict:
    return {c: getattr(f, c) for c in (
        "id", "original_name", "file_type", "size_bytes", "station_code", "parse_method", "period_start",
        "period_end", "rows_total", "rows_imported", "rows_duplicate", "rows_error", "rows_flagged", "status",
        "message", "sha256")}


def _batch_out(db: Session, b: ImportBatch, rows: bool = False) -> dict:
    issues_by_file = {}
    for fid, sev, n in db.execute(select(ImportIssue.file_id, ImportIssue.severity, func.count())
                                  .where(ImportIssue.batch_id == b.id).group_by(ImportIssue.file_id, ImportIssue.severity)):
        issues_by_file.setdefault(fid, {})[sev] = n
    previews = importer.batch_rows_preview(db, b) if rows and b.status == "preview" else {}
    user = db.get(User, b.created_by) if b.created_by else None
    return {
        "id": b.id, "status": b.status, "created_at": b.created_at, "committed_at": b.committed_at,
        "created_by": user.username if user else None, "files_count": b.files_count,
        "rows_total": b.rows_total, "rows_imported": b.rows_imported, "rows_duplicate": b.rows_duplicate,
        "rows_error": b.rows_error, "rows_flagged": b.rows_flagged,
        "files": [{**_file_out(f), "issue_counts": issues_by_file.get(f.id, {}),
                   **({"preview": previews.get(f.id)} if rows else {})} for f in b.files],
    }


@router.post("/preview")
async def preview(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                  user: User = Depends(can_write)):
    cfg = get_settings()
    if not files:
        raise HTTPException(422, "Файлы не выбраны")
    limit = cfg.max_upload_mb * 1024 * 1024
    uploads = []
    for uf in files:
        content = await uf.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, f"Файл «{uf.filename}» превышает {cfg.max_upload_mb} МБ")
        if not content:
            raise HTTPException(422, f"Файл «{uf.filename}» пуст")
        try:
            importer.detect_type(uf.filename or "", content[:8])
        except importer.UploadRejected as e:
            raise HTTPException(415, f"«{uf.filename}»: {e}")
        uploads.append((uf.filename or "file", content))
    try:
        batch = importer.create_preview(db, user.id, uploads)
        audit.log(db, "import_preview", user, request, "import_batch", batch.id, {"files": [u[0] for u in uploads]})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _batch_out(db, db.get(ImportBatch, batch.id), rows=True)


@router.post("/{batch_id}/commit")
def commit(batch_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(can_write)):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Пакет импорта не найден")
    try:
        importer.commit_batch(db, batch)
        audit.log(db, "import_commit", user, request, "import_batch", batch.id,
                  {"imported": batch.rows_imported, "duplicates": batch.rows_duplicate, "errors": batch.rows_error})
        db.commit()  # вся транзакция целиком
    except importer.CommitError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        b = db.get(ImportBatch, batch_id)
        b.status = "failed"
        audit.log(db, "import_failed", user, request, "import_batch", batch_id, {"error": str(e)[:500]})
        db.commit()
        raise HTTPException(500, f"Импорт отменён, данные не изменены: {e}")
    return _batch_out(db, db.get(ImportBatch, batch_id))


@router.delete("/{batch_id}", status_code=204)
def cancel(batch_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(can_write)):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Пакет импорта не найден")
    if batch.status != "preview":
        raise HTTPException(409, "Отменить можно только пакет в статусе предпросмотра")
    shutil.rmtree(Path(get_settings().upload_dir) / f"batch_{batch.id}", ignore_errors=True)
    batch.status = "cancelled"
    audit.log(db, "import_cancelled", user, request, "import_batch", batch.id)
    db.commit()


@router.get("")
def history(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(current_user)):
    batches = db.scalars(select(ImportBatch).where(ImportBatch.status.in_(["committed", "failed"]))
                         .order_by(ImportBatch.id.desc()).limit(limit)).all()
    return [_batch_out(db, b) for b in batches]


@router.get("/{batch_id}")
def detail(batch_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    b = db.get(ImportBatch, batch_id)
    if not b:
        raise HTTPException(404, "Пакет импорта не найден")
    return _batch_out(db, b, rows=True)


@router.get("/{batch_id}/issues")
def issues(batch_id: int, file_id: int | None = None, severity: str | None = Query(None, pattern="^(error|warning|info)$"),
           page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
           db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(ImportIssue).where(ImportIssue.batch_id == batch_id)
    if file_id:
        stmt = stmt.where(ImportIssue.file_id == file_id)
    if severity:
        stmt = stmt.where(ImportIssue.severity == severity)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ImportIssue.id).limit(page_size).offset((page - 1) * page_size)).all()
    return {"total": total, "items": [{c: getattr(i, c) for c in ("id", "file_id", "row_number", "severity", "code",
                                                                  "message", "raw")} for i in items]}
