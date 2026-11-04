"""Экспорт в настоящий .xlsx (openpyxl): «Общий отчёт» + отдельный лист на каждую станцию."""
from __future__ import annotations

import io
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from ..models import SeismicEvent
from .reasons import reason_text

# (заголовок, ширина-минимум, формат числа)
COLS = [
    ("Станция", 10, None), ("Дата", 12, "DD.MM.YYYY"),
    ("Фаза", 7, None), ("Время ч:м:с", 13, "HH:MM:SS.0"),
    ("Фаза", 7, None), ("Время ч:м:с", 13, "HH:MM:SS.0"),
    ("Время в очаге", 14, "HH:MM:SS.0"), ("S-P", 9, "0.00"), ("R км", 9, "0.0"),
    ("P", 12, "#,##0.00"), ("S", 12, "#,##0.00"), ("Mb", 7, "0.0"), ("ML", 7, "0.0"),
    ("Ep Vp", 8, "0.00"), ("Ep Vs", 8, "0.00"), ("Ep Vp/Vs", 10, "0.00"), ("Проверка", 40, None),
]
NAVY, GREY, WARN = "1F3A5F", "EEF2F7", "FFF4CE"
thin = Side(style="thin", color="C9D1DC")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _num(v):
    return None if v is None else float(v)


def _row(e: SeismicEvent) -> list:
    return [e.station.code, e.event_date, e.p_phase, e.p_time, e.s_phase, e.s_time, e.origin_time,
            _num(e.s_minus_p), _num(e.r_km), _num(e.amp_p), _num(e.amp_s), _num(e.mb), _num(e.ml),
            _num(e.ep_vp), _num(e.ep_vs), _num(e.ep_vp_vs),
            "; ".join(reason_text(r) for r in e.review_reasons) if e.needs_review else None]


def _sheet(ws, title: str, subtitle: str, period: str, generated: str, events: list[SeismicEvent]) -> None:
    n = len(COLS)
    last = get_column_letter(n)
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A2"], ws["A3"], ws["A4"] = title, subtitle, f"Отчётный период: {period}", \
        f"Дата формирования: {generated}    Записей: {len(events)}"
    ws["A1"].font = Font(size=15, bold=True, color=NAVY)
    ws["A2"].font = Font(size=11, color="44546A")
    for c in ("A3", "A4"):
        ws[c].font = Font(size=10, color="44546A")
    ws.row_dimensions[1].height = 24

    h1, h2 = 6, 7
    fill = PatternFill("solid", fgColor=NAVY)
    hfont = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, (name, _, _) in enumerate(COLS, start=1):
        for r in (h1, h2):
            c = ws.cell(row=r, column=i)
            c.fill, c.font, c.alignment, c.border = fill, hfont, center, BORDER
        ws.cell(row=h2, column=i, value=name)
    for rng, text in (("C6:D6", "P волна"), ("E6:F6", "S волна"), ("J6:K6", "A в мк/с")):
        ws.merge_cells(rng)
        ws[rng.split(":")[0]] = text
    for col in (1, 2, 7, 8, 9, 12, 13, 14, 15, 16, 17):  # одиночные колонки: объединяем две строки шапки
        ws.merge_cells(start_row=h1, end_row=h2, start_column=col, end_column=col)
        ws.cell(row=h1, column=col, value=COLS[col - 1][0])
    ws.merge_cells("A1:Q1")

    if not events:
        ws.cell(row=h2 + 1, column=1, value="Нет данных за выбранный период").font = Font(italic=True, color="7F7F7F")
    widths = [c[1] for c in COLS]
    warn = PatternFill("solid", fgColor=WARN)
    zebra = PatternFill("solid", fgColor=GREY)
    for ridx, e in enumerate(events, start=h2 + 1):
        vals = _row(e)
        for cidx, v in enumerate(vals, start=1):
            c = ws.cell(row=ridx, column=cidx, value=v)
            c.border = BORDER
            fmt = COLS[cidx - 1][2]
            if fmt:
                c.number_format = fmt
            if isinstance(v, (int, float)) or fmt:
                c.alignment = Alignment(horizontal="right")
            if e.needs_review:
                c.fill = warn
            elif (ridx - h2) % 2 == 0:
                c.fill = zebra
            if v is not None:
                ln = len(f"{v:,.2f}") if isinstance(v, float) else len(str(v))
                widths[cidx - 1] = min(max(widths[cidx - 1], ln + 2), 70)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=h2 + 1, column=1)
    ws.auto_filter.ref = f"A{h2}:{last}{max(h2 + len(events), h2 + 1)}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"{h1}:{h2}"


def build_workbook(title: str, date_from: date | None, date_to: date | None,
                   stations: list[tuple[str, str | None]], events: list[SeismicEvent]) -> bytes:
    """stations: [(код, название)] — для каждой создаётся лист; events — все записи отчёта."""
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")
    period = f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}" if date_from and date_to else "весь доступный период"
    wb = Workbook()
    ws = wb.active
    ws.title = "Общий отчёт"
    names = ", ".join(f"{c}" + (f" ({n})" if n else "") for c, n in stations)
    _sheet(ws, title, f"Станции: {names}", period, generated, events)
    by = {}
    for e in events:
        by.setdefault(e.station.code, []).append(e)
    for code, name in stations:
        w = wb.create_sheet(code[:31])
        _sheet(w, f"{title} — {code}" + (f" ({name})" if name else ""), f"Станция: {code}", period, generated,
               by.get(code, []))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
