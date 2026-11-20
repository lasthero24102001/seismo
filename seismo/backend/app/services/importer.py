"""Импорт бюллетеней: проверка файлов → план (предпросмотр) → фиксация в одной транзакции."""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ImportBatch, ImportFile, ImportIssue, SeismicEvent, Station
from .parsing import NUM_FIELDS, TIME_FIELDS, IssueDraft, ParseError, ParsedRow, parse_file, record_hash

ALLOWED_EXT = {".xlsx": "xlsx", ".pdf": "pdf"}
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")


class UploadRejected(Exception):
    pass


# ───────────────────────── проверка и сохранение загрузки ─────────────────────────

def suggest_stations(codes: list[str], filename: str) -> list[str]:
    """Подсказка станции по имени файла (agalik → AGAL). Только подсказка: пользователь подтверждает сам."""
    words = {w.upper() for w in re.findall(r"[A-Za-z]{3,8}", Path(filename).stem)}
    out = [c for c in sorted(codes) if len(c) >= 3 and any(w.startswith(c.upper()) or (len(w) >= 4 and c.upper().startswith(w))
                                                           for w in words)]
    return out[:5]


def guess_station(codes: list[str], filename: str) -> str | None:
    """Уверенное совпадение имени файла со станцией: единственный кандидат и код не короче 4 символов
    (agalik → AGAL). Короткие коды (NAN, NUR…) только предлагаются, но сами не подставляются."""
    sug = suggest_stations(codes, filename)
    return sug[0] if len(sug) == 1 and len(sug[0]) >= 4 else None


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    return re.sub(r"[^\w.\- ()А-Яа-яЁё]", "_", base)[:200] or "file"


def detect_type(filename: str, head: bytes) -> str:
    ext = Path(filename).suffix.lower()
    ft = ALLOWED_EXT.get(ext)
    if not ft:
        raise UploadRejected(f"Недопустимый формат «{ext or 'без расширения'}». Разрешены: .xlsx, .pdf")
    if ft == "pdf" and not head.startswith(b"%PDF"):
        raise UploadRejected("Файл не является PDF (неверная сигнатура)")
    if ft == "xlsx" and not head.startswith(b"PK"):
        raise UploadRejected("Файл не является .xlsx (неверная сигнатура)")
    return ft


def station_token(filename: str) -> str | None:
    m = re.match(r"^([A-Za-z][A-Za-z0-9]{1,7})(?=[^A-Za-z0-9]|$)", Path(filename).stem)
    return m.group(1).upper() if m else None


# ───────────────────────── план импорта одного файла ─────────────────────────

@dataclass
class PlannedRow:
    row: ParsedRow
    station_code: str
    hash: str
    status: str  # new | dup_in_file | dup_in_db | dup_sheet | error
    flags: list[str] = field(default_factory=list)


@dataclass
class FilePlan:
    file: ImportFile
    station_code: str | None
    new_station: bool
    method: str | None
    rows: list[PlannedRow]
    issues: list[IssueDraft]
    service_rows: int
    fatal: str | None = None

    @property
    def counts(self) -> dict:
        c = Counter(p.status for p in self.rows)
        return {"total": len(self.rows), "new": c["new"], "dup_in_file": c["dup_in_file"],
                "dup_in_db": c["dup_in_db"], "dup_sheet": c["dup_sheet"], "error": c["error"],
                "flagged": sum(1 for p in self.rows if p.status == "new" and p.flags),
                "service": self.service_rows}


def _station_lookup(db: Session) -> dict[str, Station]:
    m: dict[str, Station] = {}
    for st in db.scalars(select(Station)):
        m[st.code.upper()] = st
        for a in st.aliases or []:
            m[a.upper()] = st
    return m


def plan_file(db: Session, f: ImportFile) -> FilePlan:
    cfg = get_settings()
    issues: list[IssueDraft] = []
    try:
        parsed = parse_file(Path(f.stored_path), f.file_type, cfg.ocr_enabled, cfg.ocr_lang)
    except ParseError as e:
        return FilePlan(f, None, False, None, [], [IssueDraft("error", "file_unreadable", str(e))], 0, str(e))
    except Exception as e:  # noqa: BLE001
        msg = f"Неожиданная ошибка чтения файла: {e}"
        return FilePlan(f, None, False, None, [], [IssueDraft("error", "file_unreadable", msg)], 0, msg)

    issues.extend(parsed.issues)
    lookup = _station_lookup(db)
    data_rows = [r for r in parsed.rows if r.kind in ("data", "invalid")]

    # ── определение станции файла: имя файла и/или колонка «Станция»
    col_counter = Counter(r.station_raw.upper() for r in data_rows if r.station_raw)
    col_major = col_counter.most_common(1)[0][0] if col_counter else None
    file_tok = station_token(f.original_name)
    by_name = lookup.get(file_tok) if file_tok else None
    by_col = lookup.get(col_major) if col_major else None
    new_station = False

    if f.station_hint:  # станция задана пользователем — приоритет над автоопределением
        hint = lookup.get(f.station_hint.upper())
        code, new_station = (hint.code, False) if hint else (f.station_hint.upper(), True)
        issues.append(IssueDraft("info", "station_manual", f"Станция файла задана вручную: {code}"))
        if new_station:
            issues.append(IssueDraft("warning", "new_station",
                                     f"Станция {code} отсутствует в справочнике — будет создана при импорте"))
    elif by_name:
        code = by_name.code
        if by_col and by_col.code != code:
            issues.append(IssueDraft("warning", "station_conflict",
                                     f"Имя файла указывает на {code}, колонка «Станция» — на {by_col.code}. "
                                     f"Записи отнесены к {code} и помечены для проверки"))
    elif by_col:
        code = by_col.code
    elif col_major and CODE_RE.match(col_major):
        code, new_station = col_major, True
        issues.append(IssueDraft("warning", "new_station",
                                 f"Станция {code} отсутствует в справочнике — будет создана при импорте"))
    elif not data_rows and file_tok and CODE_RE.match(file_tok):
        code, new_station = file_tok, True
        issues.append(IssueDraft("warning", "new_station",
                                 f"Станция {code} (по имени файла) отсутствует в справочнике — будет создана"))
    elif (guess := guess_station(sorted({st.code for st in lookup.values()}), f.original_name)):
        code = guess
        issues.append(IssueDraft("warning", "station_guessed",
                                 f"Станция определена по названию файла «{Path(f.original_name).stem[:40]}» → {code}. "
                                 f"Проверьте; если это не та станция — задайте нужную вручную"))
    else:
        n_rows = sum(1 for r in data_rows if r.event_date or r.p_time)
        msg = ("Не удалось определить станцию ни по имени файла, ни по колонке «Станция»"
               + (f". В файле найдено строк с данными: {n_rows} — укажите станцию вручную, и они будут проверены" if n_rows else ""))
        return FilePlan(f, None, False, parsed.method, [], issues + [IssueDraft("error", "no_station", msg)], 0, msg)

    # алиас: код в данных отличается от кода станции, но известен как её алиас
    for raw_code in col_counter:
        st = lookup.get(raw_code)
        if st and st.code == code and raw_code != code:
            issues.append(IssueDraft("info", "station_alias",
                                     f"В данных код «{raw_code}» — это алиас станции {code}"))

    # ── записи, уже существующие в БД
    existing: set[str] = set()
    st_obj = lookup.get(code)
    if st_obj:
        existing = set(db.scalars(select(SeismicEvent.record_hash).where(SeismicEvent.station_id == st_obj.id)))

    planned: list[PlannedRow] = []
    seen: dict[str, tuple] = {}          # хеш содержимого → (лист, строка)
    key_first: dict[tuple, ParsedRow] = {}  # (дата, время P) → первая запись (для дублей между листами)
    empties: Counter = Counter()
    multi = len(parsed.sheets) > 1
    where = lambda r: f"Лист «{r.sheet}», " if multi and r.sheet else ""  # noqa: E731
    service = 0
    for r in parsed.rows:
        if r.kind == "empty":
            service += 1
            empties[r.sheet] += 1
            continue
        if r.kind == "note":
            service += 1
            issues.append(IssueDraft("info", "note_row", f"{where(r)}служебная строка, не запись: «{r.raw[2]}»",
                                     r.source_row, r.raw))
            continue
        if r.kind == "invalid":
            issues.append(IssueDraft("error", "row_invalid", f"{where(r)}строка не сохранена: {r.error}",
                                     r.source_row, r.raw))
            planned.append(PlannedRow(r, code, "", "error"))
            continue
        flags = list(r.flags)
        if r.station_raw and lookup.get(r.station_raw.upper()) is not (lookup.get(code) or None) \
                and r.station_raw.upper() != code:
            flags.append("station_mismatch")
        h = record_hash(code, r)
        key = (r.event_date, r.p_time)
        first = key_first.get(key) if r.p_time is not None else None
        if h in seen:
            sh, rw = seen[h]
            issues.append(IssueDraft("warning", "duplicate_in_file",
                                     f"{where(r)}точная копия записи ({'лист «' + sh + '», ' if multi and sh else ''}"
                                     f"строка {rw}) — не сохранена повторно", r.source_row, r.raw))
            planned.append(PlannedRow(r, code, h, "dup_in_file", flags))
        elif h in existing:
            issues.append(IssueDraft("warning", "duplicate_in_db",
                                     f"{where(r)}запись уже есть в базе — повторный импорт пропущен",
                                     r.source_row, r.raw))
            planned.append(PlannedRow(r, code, h, "dup_in_db", flags))
            seen[h] = (r.sheet, r.source_row)
        elif first is not None and first.sheet != r.sheet:
            diff = [n for n in (*TIME_FIELDS, *NUM_FIELDS)
                    if (first.nums.get(n) if n in NUM_FIELDS else getattr(first, n)) !=
                    (r.nums.get(n) if n in NUM_FIELDS else getattr(r, n))]
            issues.append(IssueDraft(
                "warning", "duplicate_other_sheet",
                f"{where(r)}это же событие (дата + время P) уже взято с листа «{first.sheet}», строка {first.source_row}; "
                f"сохранена первая версия" + (f", в этой версии отличаются: {', '.join(diff)}" if diff else ""),
                r.source_row, r.raw))
            planned.append(PlannedRow(r, code, h, "dup_sheet", flags))
        else:
            planned.append(PlannedRow(r, code, h, "new", flags))
        seen.setdefault(h, (r.sheet, r.source_row))
        if r.p_time is not None:
            key_first.setdefault(key, r)
    for sh, n in empties.items():
        issues.append(IssueDraft("info", "empty_rows",
                                 f"{'Лист «' + sh + '»: ' if multi and sh else ''}пустых и шаблонных строк без данных "
                                 f"(только номер, формулы без значений) пропущено: {n}"))
    for sh in parsed.sheets:  # сводка по каждому листу
        st = Counter(p.status for p in planned if p.row.sheet == sh)
        if multi or st:
            issues.append(IssueDraft("info", "sheet_summary",
                                     f"Лист «{sh}»: строк {sum(st.values())} · новых {st['new']} · "
                                     f"дубликатов {st['dup_in_file'] + st['dup_in_db'] + st['dup_sheet']} · "
                                     f"ошибок {st['error']}"))

    # ── возможные дубли: тот же момент вступления P, но другое содержимое
    groups: dict[tuple, list[PlannedRow]] = defaultdict(list)
    for p in planned:
        if p.status == "new":
            groups[(p.row.event_date, p.row.p_time)].append(p)
    db_keys: set[tuple] = set()
    if st_obj and groups:
        dates = {k[0] for k in groups}
        db_keys = {(d, t) for d, t in db.execute(
            select(SeismicEvent.event_date, SeismicEvent.p_time)
            .where(SeismicEvent.station_id == st_obj.id, SeismicEvent.event_date.in_(dates)))}
    for key, items in groups.items():
        if key[1] is not None and (len(items) > 1 or key in db_keys):
            for p in items:
                p.flags.append("near_duplicate")
    for p in planned:
        p.flags = list(dict.fromkeys(p.flags))

    return FilePlan(f, code, new_station, parsed.method, planned, issues, service)


# ───────────────────────── предпросмотр ─────────────────────────

def create_preview(db: Session, user_id: int | None, uploads: list[tuple[str, bytes]]) -> ImportBatch:
    """uploads: [(имя, содержимое)]. Файлы сохраняются на диск, парсятся, статистика пишется в БД."""
    cfg = get_settings()
    batch = ImportBatch(created_by=user_id, status="preview", files_count=len(uploads))
    db.add(batch)
    db.flush()
    folder = Path(cfg.upload_dir) / f"batch_{batch.id}"
    folder.mkdir(parents=True, exist_ok=True)

    for name, content in uploads:
        ft = detect_type(name, content[:8])
        path = folder / f"{uuid.uuid4().hex[:8]}_{safe_name(name)}"
        path.write_bytes(content)
        f = ImportFile(batch_id=batch.id, original_name=safe_name(name), stored_path=str(path),
                       sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), file_type=ft)
        db.add(f)
    db.flush()
    refresh_preview(db, batch)
    return batch


def _apply_plan_stats(f: ImportFile, plan: FilePlan) -> None:
    c = plan.counts
    f.station_code = plan.station_code
    f.parse_method = plan.method
    f.rows_total = c["total"]
    f.rows_imported = c["new"]
    f.rows_duplicate = c["dup_in_file"] + c["dup_in_db"] + c["dup_sheet"]
    f.rows_error = c["error"]
    f.rows_flagged = c["flagged"]
    dates = [p.row.event_date for p in plan.rows if p.row.event_date]
    f.period_start, f.period_end = (min(dates), max(dates)) if dates else (None, None)
    f.message = plan.fatal


def refresh_preview(db: Session, batch: ImportBatch) -> list[FilePlan]:
    db.execute(delete(ImportIssue).where(ImportIssue.batch_id == batch.id))
    plans = []
    for f in batch.files:
        plan = plan_file(db, f)
        _apply_plan_stats(f, plan)
        f.status = "failed" if plan.fatal else "preview"
        same = db.scalar(select(ImportFile.id).where(ImportFile.sha256 == f.sha256, ImportFile.status == "imported",
                                                     ImportFile.id != f.id).limit(1))
        if same:
            plan.issues.append(IssueDraft("warning", "file_already_imported",
                                          "Файл с таким же содержимым уже импортировался ранее — "
                                          "повторяющиеся записи будут пропущены"))
        for i in plan.issues:
            db.add(ImportIssue(batch_id=batch.id, file_id=f.id, row_number=i.row_number,
                               severity=i.severity, code=i.code, message=i.message, raw=i.raw))
        plans.append(plan)
    batch.rows_total = sum(f.rows_total for f in batch.files)
    batch.rows_imported = sum(f.rows_imported for f in batch.files)
    batch.rows_duplicate = sum(f.rows_duplicate for f in batch.files)
    batch.rows_error = sum(f.rows_error for f in batch.files)
    batch.rows_flagged = sum(f.rows_flagged for f in batch.files)
    db.flush()
    return plans


# ───────────────────────── фиксация ─────────────────────────

class CommitError(Exception):
    pass


def commit_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    """Всё или ничего: вызывающий код делает commit()/rollback() для всей транзакции."""
    from datetime import datetime, timezone

    if batch.status != "preview":
        raise CommitError("Пакет уже обработан")
    plans = refresh_preview(db, batch)  # свежее состояние БД (защита от гонок/повторов)
    if all(p.fatal for p in plans):
        raise CommitError("Импортировать нечего: у файлов не определена станция или они не читаются. "
                          "Укажите станцию файла в предпросмотре")
    imported_total = 0
    for plan in plans:
        f = plan.file
        if plan.fatal:
            f.status = "failed"
            continue
        st = _station_lookup(db).get(plan.station_code)
        if st is None:
            st = Station(code=plan.station_code, aliases=[])
            db.add(st)
            db.flush()
        rows = [p for p in plan.rows if p.status == "new"]
        inserted_hashes: set[str] = set()
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            values = [{
                "station_id": st.id, "file_id": f.id, "source_no": p.row.source_no, "source_row": p.row.source_row,
                "source_sheet": p.row.sheet,
                "event_date": p.row.event_date, "p_phase": p.row.p_phase, "p_time": p.row.p_time,
                "s_phase": p.row.s_phase, "s_time": p.row.s_time, "origin_time": p.row.origin_time,
                **{k: p.row.nums.get(k) for k in NUM_FIELDS},
                "needs_review": bool(p.flags), "review_reasons": p.flags, "review_comment": p.row.note, "raw": p.row.raw, "record_hash": p.hash,
            } for p in chunk]
            stmt = pg_insert(SeismicEvent).values(values).on_conflict_do_nothing(
                index_elements=["station_id", "record_hash"]).returning(SeismicEvent.record_hash)
            inserted_hashes.update(db.scalars(stmt))
        skipped = len(rows) - len(inserted_hashes)
        if skipped:  # состояние гонки: кто-то успел вставить ту же запись
            f.rows_imported = len(inserted_hashes)
            f.rows_duplicate += skipped
        f.station_id = st.id
        f.status = "imported"
        imported_total += f.rows_imported
    batch.rows_imported = sum(f.rows_imported for f in batch.files)
    batch.rows_duplicate = sum(f.rows_duplicate for f in batch.files)
    batch.status = "committed"
    batch.committed_at = datetime.now(timezone.utc)
    db.flush()
    return batch


def batch_rows_preview(db: Session, batch: ImportBatch, limit: int = 3000) -> dict[int, dict]:
    """Строки для предпросмотра (до `limit` на файл)."""
    out: dict[int, dict] = {}
    for f in batch.files:
        plan = plan_file(db, f)
        rows = []
        for p in plan.rows[:limit]:
            r = p.row
            rows.append({
                "source_row": r.source_row, "source_no": r.source_no, "sheet": r.sheet, "status": p.status, "flags": p.flags,
                "error": r.error, "station": p.station_code, "event_date": r.event_date,
                "p_phase": r.p_phase, "p_time": r.p_time, "s_phase": r.s_phase, "s_time": r.s_time,
                "origin_time": r.origin_time, **{k: r.nums.get(k) for k in NUM_FIELDS}, "raw": r.raw,
            })
        out[f.id] = {"rows": rows, "truncated": len(plan.rows) > limit,
                     "sheets": sorted({p.row.sheet for p in plan.rows if p.row.sheet})}
    return out


def rollback_batch(db: Session, batch: ImportBatch) -> int:
    """Удаляет все записи, добавленные этим импортом, и помечает пакет «откачен».
    Вызывающий код делает commit(). Возвращает число удалённых записей."""
    if batch.status != "committed":
        raise CommitError("Откатить можно только выполненный импорт")
    ids = [f.id for f in batch.files]
    n = db.execute(delete(SeismicEvent).where(SeismicEvent.file_id.in_(ids))).rowcount or 0
    for f in batch.files:
        f.status = "rolled_back"
    batch.status = "rolled_back"
    return n
