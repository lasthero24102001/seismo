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
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

NUM_FIELDS = ["s_minus_p", "r_km", "amp_p", "amp_s", "mb", "ml", "ep_vp", "ep_vs", "ep_vp_vs"]
TIME_FIELDS = ["p_time", "s_time", "origin_time"]
# порядок колонок исходного бюллетеня (A..Q)
COLUMNS = ["no", "station", "date", "p_phase", "p_time", "s_phase", "s_time", "origin_time",
           "s_minus_p", "r_km", "amp_p", "amp_s", "mb", "ml", "ep_vp", "ep_vs", "ep_vp_vs"]
N_COLS = len(COLUMNS)

TIME_RE = re.compile(r"^(\d{1,2})[:;](\d{2})[:;](\d{2})(?:[,.](\d{1,6}))?$")  # «;» вместо «:» — частая опечатка
DATE_RE = re.compile(r"^(\d{1,2})[.,](\d{1,2})[.,](\d{4})$")


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
    sheet: str | None = None
    note: str | None = None  # пояснение к записи (сохраняется как комментарий)


@dataclass
class ParsedFile:
    rows: list[ParsedRow]
    issues: list[IssueDraft]
    method: str  # excel | pdf_table | pdf_text | pdf_ocr
    sheets: list[str] = field(default_factory=list)


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


def _is_xl_error(v) -> bool:
    return isinstance(v, str) and v.strip().startswith("#")


def _secs_decimal(t: time) -> Decimal:
    whole = t.hour * 3600 + t.minute * 60 + t.second
    frac = f"{t.microsecond:06d}".rstrip("0") or "0"
    return Decimal(f"{whole}.{frac}")


def parse_sp(v) -> Decimal | None:
    """S-P в источнике бывает числом (47,75), временем (00:00:45,5 → 45.5 с) или ошибкой Excel (#VALUE!)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return _secs_decimal(v.time())
    if isinstance(v, time):
        return _secs_decimal(v)
    s = _text(v)
    if s is None:
        return None
    if s.startswith("#"):
        raise ValueError(f"ошибка Excel {s}")
    if ":" in s or ";" in s:
        return _secs_decimal(parse_time(s))
    return parse_decimal(s)


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


def _zeroish(v) -> bool:
    if v is None:
        return True
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == 0
    if isinstance(v, time):
        return v == time(0, 0, 0)
    if isinstance(v, str):
        t = v.strip()
        return t == "" or t.startswith("#") or t in ("0", "00:00:00", "0:00:00")
    return False


def parse_cells(cells: list, source_row: int, ocr: bool = False, station_required: bool = True,
                allow_missing_date: bool = False) -> ParsedRow:
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
        if all(_zeroish(c[f]) for f in TIME_FIELDS):
            row.kind = "empty"  # остаток формулы: нет даты и ни одного времени — не запись
            return row
        if not (allow_missing_date and _text(c["date"]) is None):   # пустую дату решает вызывающий код (см. _fill_missing_dates)
            row.error = "дата отсутствует"
    if row.station_raw is None and station_required:
        row.error = (row.error + "; " if row.error else "") + "станция отсутствует"
    if row.error:
        row.kind = "invalid"
        return row

    for f in TIME_FIELDS:
        try:
            setattr(row, f, parse_time(c[f]))
        except ValueError:
            row.flags.append(f"{'excel_error' if _is_xl_error(c[f]) else 'parse'}:{f}")
    for f in NUM_FIELDS:
        try:
            row.nums[f] = parse_sp(c[f]) if f == "s_minus_p" else parse_decimal(c[f])
        except ValueError as e:
            row.nums[f] = None
            row.flags.append(f"{'excel_error' if _is_xl_error(c[f]) or 'ошибка Excel' in str(e) else 'parse'}:{f}")
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
        if val is None and not any(x in fl for x in (f"parse:{f}", f"excel_error:{f}")):
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
    if row.event_date and row.event_date > date.today() + timedelta(days=1):
        fl.append("date_future")
    if n.get("r_km") is not None and n["r_km"] > 3000:
        fl.append("dist_range")
    row.flags = list(dict.fromkeys(fl))


# ───────────────────────── Excel ─────────────────────────
# Колонки сопоставляются по ЗАГОЛОВКАМ (а не по позициям), листов может быть несколько,
# раскладка листов может отличаться (нет «Станции», нет Ep Vp…, боковые таблицы статистики и т.п.).

_LOOK = str.maketrans("АВЕКМНОРСТХаекмнортсхв", "ABEKMHOPCTXaekmhoptcxb")  # кириллица-двойники → латиница


def _hn(v) -> str:
    """Нормализация заголовка: двойники кириллица/латиница, регистр, пробелы, точки, запятые, апострофы."""
    s = str(v if v is not None else "").translate(_LOOK).lower()
    return re.sub(r"[\s.:,\u00a0'`´’ʻʼ‘]+", "", s)


# Заголовки бывают русскими и узбекскими (латиница): «Дата» / «Sana», «P волна» / «P to'lqin» и т.д.
_H_SINGLE = {
    "no": {_hn("No"), "№", "n"},
    "station": {_hn("Станция"), "stansiya", "station"},
    "date": {_hn("Дата"), "sana", "date"},
    "s_minus_p": {_hn("S-P")},
    "r_km": {_hn("R км"), "rkm"},
    "mb": {_hn("Mb")}, "ml": {_hn("ML")},
    "ep_vp": {_hn("Ep Vp"), "vp"}, "ep_vs": {_hn("Ep Vs"), "vs"}, "ep_vp_vs": {_hn("Ep Vp/Vs"), "vp/vs"},
}
_ORIGIN_PREFIX = (_hn("Время в оч"), "ochoqdagi", "origin")
_G_P = {_hn("P волна"), "ptolqin"}
_G_S = {_hn("S волна"), "stolqin"}
_G_A_PREFIX = (_hn("A в мк/с"), "amplituda", "amplitude")
_SUB_PHASE = {_hn("Фаза"), "faza", "phase"}
_SUB_TIME_PREFIX = (_hn("Время"), "vaqt", "time")


def _map_columns(h1: list, h2: list) -> dict[str, int]:
    """Двухстрочная шапка → {поле: индекс колонки}. Неизвестные колонки игнорируются."""
    cols: dict[str, int] = {}
    group = None
    for i in range(max(len(h1), len(h2))):
        t = _hn(h1[i]) if i < len(h1) else ""
        sub = _hn(h2[i]) if i < len(h2) else ""
        if t:
            group = t
        elif not sub:
            group = None
        field = None
        if not sub:
            field = next((k for k, names in _H_SINGLE.items() if t in names), None)
            if field is None and t.startswith(_ORIGIN_PREFIX):
                field = "origin_time"
        elif group in _G_P or group in _G_S:
            pre = "p" if group in _G_P else "s"
            field = f"{pre}_phase" if sub in _SUB_PHASE else f"{pre}_time" if sub.startswith(_SUB_TIME_PREFIX) else None
        elif group and group.startswith(_G_A_PREFIX):
            field = {"p": "amp_p", "s": "amp_s"}.get(sub)
        if field and field not in cols:
            cols[field] = i
    return cols


_NOTE_DATE = ("Дата в файле не указана: взята из ближайшей строки выше "
              "(на этом листе дата проставлена один раз на сутки; порядок времён подтверждает ту же дату)")


def _fill_missing_dates(rows: list[ParsedRow]) -> tuple[int, int]:
    """Некоторые листы пишут дату один раз в первой строке суток, у остальных строк ячейка пуста.
    Дата восстанавливается из ближайшей строки выше ТОЛЬКО если время P не идёт назад (то есть сутки не сменились).
    Если цепочка начинается со строки, где время уже «откатилось» при той же дате (потеряна граница суток),
    строки цепочки помечаются `date_time_order`. Иначе строка остаётся ошибкой. Возвращает (восстановлено, не удалось)."""
    prev: ParsedRow | None = None
    anchor: ParsedRow | None = None   # явная строка, у которой время откатилось при той же дате
    anchor_flagged = False
    filled = unresolved = 0
    for r in rows:
        if r.kind != "data":
            continue
        if r.event_date is not None:
            anchor = r if (prev is not None and prev.event_date == r.event_date and prev.p_time and r.p_time
                           and r.p_time < prev.p_time) else None
            anchor_flagged = False
            prev = r
            continue
        if prev is None or prev.p_time is None or r.p_time is None or r.p_time < prev.p_time:
            r.kind, r.error = "invalid", "дата отсутствует" + (
                " (время раньше предыдущей записи — смена суток не определена)" if prev is not None else "")
            unresolved += 1
            continue
        r.event_date, r.note = prev.event_date, _NOTE_DATE
        if anchor is not None:
            if not anchor_flagged:
                anchor.flags.append("date_time_order")
                anchor_flagged = True
            r.flags.append("date_time_order")
        validate_row(r)
        r.flags = list(dict.fromkeys(r.flags))
        prev = r
        filled += 1
    return filled, unresolved


def _flag_date_outliers(data_rows: list[ParsedRow], max_gap: int = 45) -> int:
    """Лист идёт по времени. Строки режутся на серии: новая серия начинается, когда дата скачет более чем на
    `max_gap` дней. Малая серия, оторванная от основной хронологии (напр. 12 строк «07.01.2026» посреди августа,
    блок «01,03,2025» в начале марта, «27.02.2027…2041»), — вероятная опечатка в дате. Значение НЕ исправляется,
    записи помечаются для проверки."""
    dated = [r for r in data_rows if r.event_date]
    n = len(dated)
    if n < 20:
        return 0
    ords = [r.event_date.toordinal() for r in dated]
    segs, start = [], 0
    for i in range(1, n):
        if abs(ords[i] - ords[i - 1]) > max_gap:
            segs.append((start, i))
            start = i
    segs.append((start, n))
    if len(segs) == 1 or len(segs) > max(3, n // 10):   # нет разрывов / лист не хронологический — не применимо
        return 0
    small = max(30, int(0.05 * n))
    big = [(s_, e_) for s_, e_ in segs if e_ - s_ > small]
    if not big:
        return 0
    lo = min(min(ords[s_:e_]) for s_, e_ in big) - max_gap     # диапазон основной хронологии листа ± допуск
    hi = max(max(ords[s_:e_]) for s_, e_ in big) + max_gap
    flagged = 0
    for s_, e_ in segs:
        if e_ - s_ <= small:
            for i in range(s_, e_):
                if not lo <= ords[i] <= hi:   # малая серия внутри диапазона (напр. хвост 28.02) — не выброс
                    dated[i].flags.append("date_outlier")
                    flagged += 1
    return flagged


_CHECKED = ["p_phase", "p_time", "s_phase", "s_time", "origin_time", *NUM_FIELDS]
_ERR_PREFIXES = ("missing:", "parse:", "excel_error:")


def parse_excel(path: Path) -> ParsedFile:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"Не удаётся открыть Excel-файл: {e}") from e

    rows: list[ParsedRow] = []
    issues: list[IssueDraft] = []
    used: list[str] = []
    for ws in wb.worksheets:
        data = list(ws.iter_rows(values_only=True))
        hi = next((i for i, r in enumerate(data[:15]) if any(_hn(c) in _H_SINGLE["date"] for c in r)), None)
        if hi is None:
            if any(c is not None for r in data for c in r):
                issues.append(IssueDraft("warning", "sheet_skipped",
                                         f"Лист «{ws.title}» пропущен: не найдена шапка таблицы (колонка «Дата»)"))
            continue
        nxt = data[hi + 1] if hi + 1 < len(data) else ()
        has_sub = any(_hn(c) in _SUB_PHASE for c in nxt)
        cols = _map_columns(list(data[hi]), list(nxt) if has_sub else [])
        if "date" not in cols or "p_time" not in cols:
            issues.append(IssueDraft("warning", "sheet_skipped",
                                     f"Лист «{ws.title}» пропущен: в шапке нет колонок «Дата» и «P волна / Время»"))
            continue
        used.append(ws.title)
        start = hi + (2 if has_sub else 1)
        order = [cols.get(f) for f in COLUMNS]
        sheet_rows: list[ParsedRow] = []
        comma_dates = semicolons = 0
        for ri in range(start, len(data)):
            src = data[ri]
            canon = [src[ix] if ix is not None and ix < len(src) else None for ix in order]
            pr = parse_cells(canon, ri + 1, station_required=False, allow_missing_date=True)  # пустые «Станция»/«Дата» решаем ниже
            pr.raw = [_jsonable(c) for c in src]  # исходная строка целиком, со всеми колонками листа
            pr.sheet = ws.title
            if pr.kind == "data" and isinstance(canon[2], str) and "," in canon[2]:
                comma_dates += 1
            if pr.kind == "data" and any(isinstance(canon[COLUMNS.index(f)], str) and ";" in canon[COLUMNS.index(f)]
                                         for f in (*TIME_FIELDS, "s_minus_p")):
                semicolons += 1
            sheet_rows.append(pr)

        n_filled, n_unres = _fill_missing_dates(sheet_rows)
        if n_filled:
            issues.append(IssueDraft("warning", "date_inferred",
                                     f"Лист «{ws.title}»: у {n_filled} строк ячейка «Дата» пуста — дата взята из ближайшей строки выше "
                                     f"(дата проставлена один раз на сутки, порядок времён это подтверждает). Пояснение — в комментарии записи"))
        data_rows = [r for r in sheet_rows if r.kind == "data"]
        absent = [f for f in _CHECKED if f not in cols]
        dead = list(absent)
        for f in _CHECKED:
            if f in cols and data_rows:
                getter = (lambda r, f=f: r.nums.get(f)) if f in NUM_FIELDS else (lambda r, f=f: getattr(r, f))
                if all(getter(r) is None for r in data_rows):
                    dead.append(f)
        for r in sheet_rows:  # «мёртвые» колонки не помечают каждую строку: один вывод на лист
            if r.flags:
                r.flags = [x for x in r.flags if not (x.startswith(_ERR_PREFIXES) and x.split(":", 1)[1] in dead)]
        label = lambda fs: ", ".join(_FIELD_RU.get(f, f) for f in fs)  # noqa: E731
        if absent:
            issues.append(IssueDraft("info", "columns_absent",
                                     f"Лист «{ws.title}»: в таблице нет колонок {label(absent)} — значения не заполняются (NULL)"))
        empty_cols = [f for f in dead if f not in absent]
        if empty_cols:
            issues.append(IssueDraft("warning", "columns_empty",
                                     f"Лист «{ws.title}»: колонки {label(empty_cols)} пусты или содержат только ошибки "
                                     f"Excel (#VALUE! и т.п.) во всех {len(data_rows)} строках — значения не импортированы (NULL)"))
        if comma_dates:
            issues.append(IssueDraft("info", "date_separator",
                                     f"Лист «{ws.title}»: {comma_dates} дат записаны как дд,мм,гггг — приведены к дд.мм.гггг"))
        n_out = _flag_date_outliers(data_rows)
        if n_out:
            issues.append(IssueDraft("warning", "date_outliers",
                                     f"Лист «{ws.title}»: {n_out} зап. с датой, резко выбивающейся из соседних строк "
                                     f"(возможна опечатка в годе/месяце) — помечены для проверки, дата не менялась"))
        if semicolons:
            issues.append(IssueDraft("info", "time_separator",
                                     f"Лист «{ws.title}»: в {semicolons} строках время записано с «;» вместо «:» "
                                     f"(например 09:12;37) — приведено к чч:мм:сс, проверьте при необходимости"))
        rows.extend(sheet_rows)

    if not used:
        raise ParseError("Не найдено ни одного листа с таблицей бюллетеня (нужна шапка с колонкой «Дата»)")
    return ParsedFile(rows=rows, issues=issues, method="excel", sheets=used)


_FIELD_RU = {"p_phase": "фаза P", "p_time": "время P", "s_phase": "фаза S", "s_time": "время S",
             "origin_time": "время в очаге", "s_minus_p": "S-P", "r_km": "R км", "amp_p": "A(P)", "amp_s": "A(S)",
             "mb": "Mb", "ml": "ML", "ep_vp": "Ep Vp", "ep_vs": "Ep Vs", "ep_vp_vs": "Ep Vp/Vs"}


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
