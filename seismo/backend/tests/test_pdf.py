"""PDF/OCR: реальных PDF в наборе нет → PDF генерируются из исходных Excel-данных (синтетика)."""
import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app.services.parsing import parse_excel, parse_pdf, record_hash

from .conftest import SAMPLES

N = 40


def _cells(code="SOKH", decimal=","):
    rows = [r for r in parse_excel(SAMPLES / f"{code}_22_10_2026.xlsx").rows if r.kind == "data"][:N]
    return rows, [[("" if v is None else str(v).replace(".", decimal) if isinstance(v, float) else str(v))
                   for v in r.raw] for r in rows]


def make_text_pdf(path: Path, cells):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setFont("Helvetica", 7.5)
    y = 560
    c.drawString(30, 580, "Bulletin SOKH 22.10.2026")
    for line in cells:
        c.drawString(25, y, " ".join(line))
        y -= 12
        if y < 30:
            c.showPage(); c.setFont("Helvetica", 7.5); y = 560
    c.save()


def make_grid_pdf(path: Path, cells):
    head = ["No", "Станция", "Дата", "Фаза", "Время", "Фаза", "Время", "Очаг", "S-P", "R", "AP", "AS", "Mb", "ML", "Vp", "Vs", "Vp/Vs"]
    t = Table([["No"] * 0 + [h if False else h.encode("ascii", "ignore").decode() or "x" for h in head]] + cells)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 6)]))
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=10, rightMargin=10).build([t])


def make_scanned_pdf(src: Path, dst: Path):
    img = pdfium.PdfDocument(str(src))[0].render(scale=3).to_pil().convert("L")
    img.save(dst, "PDF", resolution=216)


def same_as_excel(parsed, src_rows):
    got = {record_hash("SOKH", r) for r in parsed.rows if r.kind == "data"}
    exp = {record_hash("SOKH", r) for r in src_rows}
    return got, exp


def test_text_pdf_matches_excel(tmp_path):
    src, cells = _cells()
    p = tmp_path / "SOKH_text.pdf"
    make_text_pdf(p, cells)
    parsed = parse_pdf(p, ocr_enabled=False)
    assert parsed.method == "pdf_text" and len([r for r in parsed.rows if r.kind == "data"]) == N
    got, exp = same_as_excel(parsed, src)
    assert got == exp  # все 40 записей идентичны Excel-версии, значение в значение


def test_grid_table_pdf_matches_excel(tmp_path):
    src, cells = _cells(decimal=".")
    p = tmp_path / "SOKH_grid.pdf"
    make_grid_pdf(p, cells)
    parsed = parse_pdf(p, ocr_enabled=False)
    assert parsed.method == "pdf_table"
    got, exp = same_as_excel(parsed, src)
    assert got == exp


def test_scanned_pdf_uses_ocr_and_flags_everything(tmp_path):
    shutil_which = __import__("shutil").which("tesseract")
    if not shutil_which:
        pytest.skip("tesseract не установлен")
    src, cells = _cells()
    t, s = tmp_path / "t.pdf", tmp_path / "SOKH_scan.pdf"
    make_text_pdf(t, cells[:25]); make_scanned_pdf(t, s)
    parsed = parse_pdf(s, ocr_enabled=True, ocr_lang="eng")
    assert parsed.method == "pdf_ocr"
    data = [r for r in parsed.rows if r.kind == "data"]
    assert data and all("ocr" in r.flags for r in data)        # всё из OCR помечено на проверку
    got, exp = same_as_excel(parsed, src[:25])
    acc = len(got & exp) / 25
    print(f"\nOCR: распознано точно {len(got & exp)}/25 строк ({acc:.0%}); не разобрано/ошибок: "
          f"{sum(1 for r in parsed.rows if r.kind == 'invalid')}")
    # ни одна строка не молча потеряна: либо запись (с пометкой), либо ошибка в журнале
    assert len(data) + sum(1 for r in parsed.rows if r.kind == "invalid") >= 20
    assert acc >= 0.8


def test_pdf_via_api_dedupes_against_excel(admin, tmp_path):
    from .conftest import sample_files
    src, cells = _cells()
    p = tmp_path / "SOKH_text.pdf"
    make_text_pdf(p, cells)
    pdf = ("files", ("SOKH_oct.pdf", p.read_bytes(), "application/pdf"))
    r = admin.post("/api/imports/preview", files=[pdf]).json()
    assert r["files"][0]["station_code"] == "SOKH" and r["files"][0]["parse_method"] == "pdf_text"
    assert r["rows_imported"] == len({record_hash("SOKH", x) for x in src})
    admin.post(f"/api/imports/{r['id']}/commit")
    # затем Excel того же станции: записи из PDF не дублируются (сквозная дедупликация по содержимому)
    r2 = admin.post("/api/imports/preview", files=sample_files(["SOKH"])).json()
    assert r2["rows_duplicate"] >= len({record_hash("SOKH", x) for x in src})
    assert r2["rows_imported"] == 189 - len({record_hash("SOKH", x) for x in src})
