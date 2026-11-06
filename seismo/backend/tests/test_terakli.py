"""terakli.xlsx: 10 листов; янв–апр с УЗБЕКСКИМИ заголовками и без колонки «Станция», май–окт — русские (Vp, Vs, Vp/Vs)."""
import io

import openpyxl

from app.services.parsing import parse_excel, record_hash

from .conftest import SAMPLES

FILE = SAMPLES / "terakli.xlsx"
SHEETS = ["yanvar (2026)", "fevral (2026)", "mart (2026)", "aprel (2026)", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr"]


def upload(content=None, name="terakli.xlsx"):
    return ("files", (name, content or FILE.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))


def load(admin):
    r = admin.post("/api/imports/preview", files=[upload()]).json()
    admin.post(f"/api/imports/{r['id']}/commit")
    return r


def test_all_sheets_read_station_inferred(admin):
    f = admin.post("/api/imports/preview", files=[upload()]).json()["files"][0]
    assert sorted(f["preview"]["sheets"]) == sorted(SHEETS)                       # раньше янв–апр молча пропускались
    assert f["station_code"] == "TRKL" and f["rows_error"] == 0   # станция берётся из листов, где она указана
    assert f["period_start"] == "2025-04-25" and f["period_end"] == "2026-10-31"   # 2 строки листа aprel с опечаткой в годе


def test_every_month_in_report_matches_source(admin):
    load(admin)
    pf = parse_excel(FILE)
    expected, first_sheet = {}, {}
    for r in pf.rows:                      # правило из ТЗ: событие (дата+P) с другого листа — дубль, берётся первая версия
        if r.kind != "data":
            continue
        key = (r.event_date, r.p_time)
        if first_sheet.setdefault(key, r.sheet) != r.sheet:
            continue
        if r.event_date.year == 2026:
            expected.setdefault(r.event_date.month, set()).add(record_hash("TRKL", r))
    for month in range(1, 11):
        d0, d1 = f"2026-{month:02d}-01", f"2026-{month:02d}-31" if month in (1, 3, 5, 7, 8, 10) else f"2026-{month:02d}-30"
        if month == 2:
            d1 = "2026-02-28"
        rep = admin.get("/api/reports", params={"date_from": d0, "date_to": d1, "stations": "TRKL"}).json()
        assert rep["total"] == len(expected[month]) > 0, month    # каждый месяц: ровно столько, сколько в исходнике


def test_velocities_for_vp_vs_headers_and_null_for_first_sheets(admin):
    load(admin)
    may = admin.get("/api/events", params={"stations": "TRKL", "date_from": "2026-05-01", "date_to": "2026-05-01",
                                           "sort": "p_time", "order": "asc"}).json()["items"][0]
    assert abs(may["ep_vp_vs"] - 1.7515432) < 1e-6 and may["ep_vp"] is not None and may["ep_vs"] is not None
    jan = admin.get("/api/events", params={"stations": "TRKL", "date_from": "2026-01-01", "date_to": "2026-01-01",
                                           "sort": "p_time", "order": "asc"}).json()["items"][0]
    assert jan["ep_vp_vs"] is None and jan["s_minus_p"] == 45.5 and jan["r_km"] == 435
    assert not any(x.startswith("missing:") for x in jan["review_reasons"])   # отсутствие колонок не помечает строки


def test_semicolon_typos_recovered(admin):
    load(admin)
    ev = admin.get("/api/events", params={"stations": "TRKL", "date_from": "2026-01-05", "date_to": "2026-01-05"}).json()["items"]
    e = next(x for x in ev if x["p_time"] == "09:12:40.0")
    assert e["origin_time"] == "09:12:37.0"      # «09:12;37» → 09:12:37


def test_manual_station_when_not_in_file(admin):
    wb = openpyxl.load_workbook(FILE)
    for ws in wb.worksheets:                      # убираем станцию отовсюду
        hdr = next((i for i, r in enumerate(ws.iter_rows(max_row=3, values_only=True), 1) if r and r[1] in ("Станция",)), None)
        if hdr:
            for row in ws.iter_rows(min_row=3):
                try:
                    row[1].value = None
                except AttributeError:   # объединённая ячейка
                    pass
    buf = io.BytesIO(); wb.save(buf)
    r = admin.post("/api/imports/preview", files=[upload(buf.getvalue())]).json()
    f = r["files"][0]
    assert f["station_code"] is None and f["status"] == "failed"      # автоопределение невозможно → понятная ошибка
    r2 = admin.patch(f"/api/imports/{r['id']}/files/{f['id']}", json={"station_code": "trkl"}).json()
    f2 = r2["files"][0]
    assert f2["station_code"] == "TRKL" and f2["station_hint"] == "TRKL" and f2["rows_imported"] > 2500
    assert admin.patch(f"/api/imports/{r['id']}/files/{f['id']}", json={"station_code": "bad code!"}).status_code == 422
    done = admin.post(f"/api/imports/{r['id']}/commit").json()
    st = {s["code"]: s for s in admin.get("/api/stations").json()}["TRKL"]
    assert st["events_count"] == done["rows_imported"] and st["first_date"] == "2025-04-25"
    # после коммита менять станцию нельзя
    assert admin.patch(f"/api/imports/{r['id']}/files/{f['id']}", json={"station_code": "SHRN"}).status_code == 409


def test_year_typo_is_flagged_not_hidden(admin):
    """aprel (2026), стр. 242–243: дата 25.04.2025 среди 24–26.04.2026 — не исправляем, но помечаем."""
    load(admin)
    ev = admin.get("/api/events", params={"stations": "TRKL", "date_from": "2025-01-01", "date_to": "2025-12-31"}).json()["items"]
    assert len(ev) == 2 and all("date_outlier" in e["review_reasons"] and e["needs_review"] for e in ev)
    assert all(e["event_date"] == "2025-04-25" for e in ev)             # значение не менялось
    r = admin.get("/api/reports", params={"date_from": "2026-04-01", "date_to": "2026-04-30", "stations": "TRKL"}).json()
    assert r["total"] == 295                                             # остальные 295 записей апреля на месте
