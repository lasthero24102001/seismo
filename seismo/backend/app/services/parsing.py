"""Чтение бюллетеней (Excel, PDF, OCR) и приведение записей к единому формату.

Принципы:
* исходные значения никогда не пересчитываются и не округляются;
* всё, что не удалось разобрать, не теряется: значение становится NULL + пометка
  `needs_review`, а строка целиком сохраняется в `raw`;
* строки, которые нельзя сохранить как событие (нет станции/даты), попадают в журнал
  импорта с исходным содержимым.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

NUM_FIELDS = ["s_minus_p", "r_km", "amp_p", "amp_s", "mb", "ml", "ep_vp", "ep_vs", "ep_vp_vs"]
TIME_FIELDS = ["p_time", "s_time", "origin_time"]
# порядок колонок исходного бюллетеня (A..Q)
COLUMNS = ["no", "station", "date", "p_phase", "p_time", "s_phase", "s_time", "origin_time",
           "s_minus_p", "r_km", "amp_p", "amp_s", "mb", "ml", "ep_vp", "ep_vs", "ep_vp_vs"]
N_COLS = len(COLUMNS)

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{1,6}))?$")
DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


class ParseError(Exception):
    """Файл невозможно прочитать / неожиданная структура."""


@dataclass
class IssueDraft:
    severity: str  # error|warning|info
    code: str
    message: str
    row_number: int | None = None
    raw: list | None = None


@dataclass
class ParsedRow:
    source_row: int
    raw: list
    kind: str = "data"  # data | empty | note | invalid
    error: str | None = None
    source_no: int | None = None
    station_raw: str | None = None
    event_date: date | None = None
    p_phase: str | None = None
    s_phase: str | None = None
    p_time: time | None = None
    s_time: time | None = None
    origin_time: time | None = None
    nums: dict[str, Decimal | None] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


@dataclass
class ParsedFile:
    rows: list[ParsedRow]
    issues: list[IssueDraft]
    method: str  # excel | pdf_table | pdf_text | pdf_ocr


# ───────────────────────── нормализация значений ─────────────────────────

def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    return s or None


def parse_decimal(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("bool")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("not finite")
        return Decimal(repr(v))
    s = _text(v)
    if s is None:
        return None
    s = s.replace(" ", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"не число: {v!r}") from e
    if not d.is_finite():
        raise ValueError("not finite")
    return d


def parse_time(v) -> time | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    s = _text(v)
    if s is None:
        return None
    m = TIME_RE.match(s)
    if not m:
        raise ValueError(f"не время: {v!r}")
    h, mi, sec, frac = int(m[1]), int(m[2]), int(m[3]), m[4]
    us = int(frac.ljust(6, "0")) if frac else 0
    return time(h, mi, sec, us)  # ValueError при выходе за диапазон


def parse_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    if s is None:
        return None
    m = DATE_RE.match(s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return date.fromisoformat(s)
    raise ValueError(f"не дата: {v!r}")


def secs(t: time) -> float:
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6


def _norm_time(t: time | None) -> str:
    return "" if t is None else f"{t.hour:02}:{t.minute:02}:{t.second:02}.{t.microsecond // 100000}"


def _norm_dec(d: Decimal | None) -> str:
    if d is None:
        return ""
    d = d.normalize()
    return "0" if d == 0 else format(d, "f")


def record_hash(station_code: str, r: ParsedRow) -> str:
    """Хеш содержимого записи (без поля No) — ключ защиты от повторного импорта.
    Не зависит от формата источника (Excel/PDF) и от записи 4 / 4.0."""
    parts = [station_code, r.event_date.isoformat() if r.event_date else "", r.p_phase or "",
             _norm_time(r.p_time), r.s_phase or "", _norm_time(r.s_time), _norm_time(r.origin_time)]
    parts += [_norm_dec(r.nums.get(f)) for f in NUM_FIELDS]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ───────────────────────── разбор и проверка одной строки ─────────────────────────

def _jsonable(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def parse_cells(cells: list, source_row: int, ocr: bool = False) -> ParsedRow:
    cells = list(cells[:N_COLS]) + [None] * max(0, N_COLS - len(cells))
    row = ParsedRow(source_row=source_row, raw=[_jsonable(c) for c in cells])
    c = dict(zip(COLUMNS, cells))

    rest_empty = all(_text(c[k]) is None for k in COLUMNS[3:])
    if _text(c["station"]) is None and rest_empty:
        row.kind = "note" if _text(c["date"]) else "empty"
        return row

    row.station_raw = _text(c["station"])
    try:
        no = _text(c["no"])
        row.source_no = int(float(no)) if no is not None else None
    except ValueError:
        row.flags.append("parse:no")
    row.p_phase, row.s_phase = _text(c["p_phase"]), _text(c["s_phase"])

    try:
        row.event_date = parse_date(c["date"])
    except ValueError as e:
        row.event_date = None
        row.error = f"дата: {e}"
    if row.event_date is None and row.error is None:
        row.error = "дата отсутствует"
    if row.station_raw is None:
        row.error = (row.error + "; " if row.error else "") + "станция отсутствует"
    if row.error:
        row.kind = "invalid"
        return row

    for f in TIME_FIELDS:
        try:
            setattr(row, f, parse_time(c[f]))
        except ValueError:
            row.flags.append(f"parse:{f}")
    for f in NUM_FIELDS:
        try:
            row.nums[f] = parse_decimal(c[f])
        except ValueError:
            row.nums[f] = None
            row.flags.append(f"parse:{f}")
    if ocr:
        row.flags.append("ocr")
    validate_row(row)
    return row


def validate_row(row: ParsedRow) -> None:
    """Проверки правдоподобия. Значения НЕ меняются — только пометки для ручной проверки."""
    fl = row.flags
    n = row.nums

    for f in ("r_km", "s_minus_p", "amp_p", "amp_s"):  # нарушают CHECK в БД → NULL + пометка
        if n.get(f) is not None and n[f] < 0:
            n[f] = None
            fl.append(f"parse:{f}")

    for f in ("p_phase", "s_phase", "p_time", "s_time", "origin_time", *NUM_FIELDS):
        val = getattr(row, f, None) if f not in NUM_FIELDS else n.get(f)
        if val is None and f"parse:{f}" not in fl:
            fl.append(f"missing:{f}")

    p, s, o = row.p_time, row.s_time, row.origin_time
    if p and s:
        d = secs(s) - secs(p)
        if d < 0:
            fl.append("time_order")
        elif n.get("s_minus_p") is not None and abs(d - float(n["s_minus_p"])) > 0.25:
            fl.append("sp_mismatch")
    if o and p and secs(o) > secs(p) and secs(o) - secs(p) < 43200:
        fl.append("time_order")  # время в очаге позже прихода P (без перехода через полночь)

    for f in ("mb", "ml"):
        if n.get(f) is not None and (n[f] > Decimal("9.5") or n[f] < Decimal("-3")):
            fl.append("mag_range")
            break
    if any(n.get(f) is not None and n[f] > 1000 for f in ("amp_p", "amp_s")):
        fl.append("amp_range")
    vp, vs, vr = n.get("ep_vp"), n.get("ep_vs"), n.get("ep_vp_vs")
    if (vp is not None and not Decimal("1.0") <= vp <= Decimal("9.0")) or \
       (vs is not None and not Decimal("0.5") <= vs <= Decimal("5.5")):
        fl.append("vel_range")
    if vr is not None and not Decimal("1.5") <= vr <= Decimal("2.1"):
        fl.append("vpvs_range")
    if n.get("r_km") is not None and n["r_km"] > 3000:
        fl.append("dist_range")
    row.flags = list(dict.fromkeys(fl))


# ───────────────────────── Excel ─────────────────────────

def _norm_header(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def parse_excel(path: Path) -> ParsedFile:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"Не удаётся открыть Excel-файл: {e}") from e
    ws = wb["Бюллетень"] if "Бюллетень" in wb.sheetnames else wb.worksheets[0]
    all_rows = list(ws.iter_rows(values_only=True))

    header_idx = next((i for i, r in enumerate(all_rows[:15])
                       if len(r) > 2 and _norm_header(r[1]) == "станция" and _norm_header(r[2]) == "дата"), None)
    if header_idx is None:
        raise ParseError("Не найдена шапка таблицы (ожидаются колонки «Станция», «Дата»)")
    hdr = all_rows[header_idx]
    if len(hdr) < N_COLS or _norm_header(hdr[7]) != "время в очаге":
        raise ParseError(f"Неожиданная структура: ожидается {N_COLS} колонок бюллетеня, "
                         f"найдено {len(hdr)}")
    start = header_idx + 1
    if start < len(all_rows) and any(_norm_header(x) == "фаза" for x in all_rows[start]):
        start += 1

    rows, issues = [], []
    for idx in range(start, len(all_rows)):
        pr = parse_cells(list(all_rows[idx]), source_row=idx + 1)
        rows.append(pr)
    return ParsedFile(rows=rows, issues=issues, method="excel")


# ───────────────────────── PDF ─────────────────────────

_DATE_IN_LINE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")


def _rows_from_line(line: str, counter: int, ocr: bool, issues: list[IssueDraft]) -> ParsedRow | None:
    tokens = line.replace("\xa0", " ").split()
    if not tokens or not tokens[0].isdigit() or not _DATE_IN_LINE.search(line):
        return None
    if len(tokens) != N_COLS:
        issues.append(IssueDraft("error", "pdf_line_unparsed",
                                 f"Строка не разобрана: найдено {len(tokens)} полей вместо {N_COLS}",
                                 counter, [line]))
        return ParsedRow(source_row=counter, raw=[line], kind="invalid",
                         error=f"{len(tokens)} полей вместо {N_COLS}")
    return parse_cells(tokens, counter, ocr=ocr)


def _ocr_page(pdf_path: Path, page_index: int, lang: str) -> str:
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        img = pdf[page_index].render(scale=3).to_pil()
        try:
            return pytesseract.image_to_string(img, lang=lang, config="--psm 6")
        except pytesseract.TesseractError:
            return pytesseract.image_to_string(img, lang="eng", config="--psm 6")
    finally:
        pdf.close()


def parse_pdf(path: Path, ocr_enabled: bool = True, ocr_lang: str = "rus+eng") -> ParsedFile:
    import pdfplumber

    rows: list[ParsedRow] = []
    issues: list[IssueDraft] = []
    methods: set[str] = set()
    counter = 0
    try:
        pdf = pdfplumber.open(path)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"Не удаётся открыть PDF: {e}") from e
    with pdf:
        for pno, page in enumerate(pdf.pages):
            page_rows: list[ParsedRow] = []
            # 1) таблицы с линиями
            try:
                tables = page.extract_tables()
            except Exception:  # noqa: BLE001
                tables = []
            for tb in tables:
                for cells in tb:
                    clean = [_text(x.replace("\n", " ") if isinstance(x, str) else x) for x in cells]
                    first = next((x for x in clean if x is not None), None)
                    if first is None or not first.isdigit():
                        continue
                    compact = clean if len(clean) == N_COLS else [x for x in clean if x is not None]
                    counter += 1
                    if len(compact) == N_COLS:
                        page_rows.append(parse_cells(compact, counter))
                    else:
                        issues.append(IssueDraft("error", "pdf_row_unparsed",
                                                 f"Стр. {pno + 1}: строка таблицы содержит {len(compact)} полей "
                                                 f"вместо {N_COLS}", counter, clean))
                        page_rows.append(ParsedRow(counter, clean, "invalid", f"{len(compact)} полей"))
            if page_rows:
                methods.add("pdf_table")
            else:
                # 2) текстовый слой
                text = page.extract_text() or ""
                ocr_used = False
                if len(text.strip()) < 20 and ocr_enabled:
                    try:
                        text, ocr_used = _ocr_page(path, pno, ocr_lang), True
                    except Exception as e:  # noqa: BLE001
                        issues.append(IssueDraft("error", "ocr_failed", f"Стр. {pno + 1}: OCR недоступен: {e}"))
                elif len(text.strip()) < 20:
                    issues.append(IssueDraft("warning", "page_no_text",
                                             f"Стр. {pno + 1}: нет текстового слоя, OCR отключён"))
                for line in text.splitlines():
                    counter += 1
                    pr = _rows_from_line(line, counter, ocr_used, issues)
                    if pr is None:
                        counter -= 1
                        continue
                    page_rows.append(pr)
                if page_rows:
                    methods.add("pdf_ocr" if ocr_used else "pdf_text")
            rows.extend(page_rows)
    method = "pdf_ocr" if "pdf_ocr" in methods else "pdf_text" if "pdf_text" in methods else "pdf_table"
    return ParsedFile(rows=rows, issues=issues, method=method)


def parse_file(path: Path, file_type: str, ocr_enabled: bool = True, ocr_lang: str = "rus+eng") -> ParsedFile:
    if file_type == "xlsx":
        return parse_excel(path)
    if file_type == "pdf":
        return parse_pdf(path, ocr_enabled, ocr_lang)
    raise ParseError(f"Неподдерживаемый тип файла: {file_type}")
