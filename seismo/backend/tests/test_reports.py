import io
from collections import defaultdict
from datetime import date

import openpyxl

from app.services.parsing import parse_excel, record_hash

from .conftest import SAMPLES, STATIONS


def source_unique(date_from=None, date_to=None, codes=STATIONS):
    out = {}
    for c in codes:
        for r in parse_excel(SAMPLES / f"{c}_22_10_2026.xlsx").rows:
            if r.kind == "data" and (not date_from or date_from <= r.event_date <= date_to):
                out[(c, record_hash(c, r))] = r
    return out


def test_report_full_period_all_stations(loaded):
    c, _ = loaded
    r = c.get("/api/reports", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}).json()
    assert r["total"] == 1234 == len(r["events"]) and not r["truncated"] and r["message"] is None
    assert [s["code"] for s in r["stations"]] == sorted(STATIONS)
    assert {s["code"]: s["count"] for s in r["stations"]}["KULK"] == 0
    assert r["period"]["date_from"] == "2026-10-01" and r["title"]
    assert c.get("/api/reports", params={"year": 2026}).json()["total"] == 1234


def test_report_other_year_empty_notice(loaded):
    c, _ = loaded
    r = c.get("/api/reports", params={"year": 2025, "date_from": "2025-10-01", "date_to": "2025-12-31"}).json()
    assert r["total"] == 0 and r["events"] == [] and "нет" in r["message"]


def test_report_period_matches_source_exactly(loaded):
    c, _ = loaded
    d0, d1 = date(2026, 10, 5), date(2026, 10, 12)
    exp = source_unique(d0, d1)
    r = c.get("/api/reports", params={"date_from": d0, "date_to": d1}).json()
    assert r["total"] == len(exp)
    assert all("2026-10-05" <= e["event_date"] <= "2026-10-12" for e in r["events"])


def test_report_selected_stations_and_validation(loaded):
    c, _ = loaded
    r = c.get("/api/reports", params={"year": 2026, "stations": "zamn,SHRN"}).json()
    assert {e["station_code"] for e in r["events"]} == {"ZAMN", "SHRN"} and r["total"] == 163 + 416
    assert c.get("/api/reports", params={"year": 2026, "stations": "NOPE"}).status_code == 422
    assert c.get("/api/reports", params={"date_from": "2026-10-10", "date_to": "2026-10-01"}).status_code == 422
    assert c.get("/api/reports").status_code == 422


def test_same_event_on_different_stations_not_merged(loaded):
    c, _ = loaded
    ev = c.get("/api/reports", params={"date_from": "2026-10-01", "date_to": "2026-10-01"}).json()["events"]
    by = defaultdict(set)
    for e in ev:
        by[e["origin_time"]].add(e["station_code"])
    assert any(len(v) >= 2 for v in by.values())  # одно событие, несколько станций — все записи на месте


def test_events_table_filters_sort_pagination(loaded):
    c, _ = loaded
    p1 = c.get("/api/events", params={"page_size": 100, "page": 1}).json()
    p2 = c.get("/api/events", params={"page_size": 100, "page": 2}).json()
    assert p1["total"] == 1234 and len(p1["items"]) == 100
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    mb = [i["mb"] for i in c.get("/api/events", params={"sort": "mb", "order": "desc", "page_size": 50}).json()["items"]]
    assert mb == sorted(mb, reverse=True)
    f = c.get("/api/events", params={"mb_min": 5, "mb_max": 6, "stations": "SHRN", "page_size": 500}).json()
    assert f["total"] > 0 and all(5 <= i["mb"] <= 6 and i["station_code"] == "SHRN" for i in f["items"])
    f = c.get("/api/events", params={"r_min": 100, "r_max": 200, "page_size": 500}).json()
    assert all(100 <= i["r_km"] <= 200 for i in f["items"])
    assert c.get("/api/events", params={"year": 2026, "month": 10, "page_size": 1}).json()["total"] == 1234
    assert c.get("/api/events", params={"year": 2026, "month": 9, "page_size": 1}).json()["total"] == 0
    assert c.get("/api/events", params={"q": "sok", "page_size": 1}).json()["total"] == 189
    assert c.get("/api/events", params={"needs_review": True, "stations": "PSK", "page_size": 1}).json()["total"] == 99
    assert c.get("/api/events", params={"sort": "hack; drop"}).status_code == 422


def test_dashboard_from_postgres(loaded):
    c, _ = loaded
    d = c.get("/api/dashboard").json()
    t = d["totals"]
    assert t["events"] == 1234 and t["stations_with_data"] == 7 and t["stations_total"] == 8
    today = date.fromisoformat(t["today"])
    assert t["events_year"] == c.get("/api/events", params={"year": today.year, "page_size": 1}).json()["total"]
    assert t["events_month"] == c.get("/api/events", params={"year": today.year, "month": today.month, "page_size": 1}).json()["total"]
    assert sum(m["count"] for m in d["by_month"]) == 1234 and d["by_month"][0]["month"] == "2026-10"
    assert sum(s["count"] for s in d["by_station"]) == 1234
    assert max(m["mb_max"] for m in d["magnitude"] if m["mb_max"] is not None) < 9.5  # аномальные PSK исключены
    d2 = c.get("/api/dashboard", params={"exclude_flagged": False}).json()
    assert max(m["mb_max"] for m in d2["magnitude"] if m["mb_max"] is not None) > 9.5
    d3 = c.get("/api/dashboard", params={"date_from": "2026-10-01", "date_to": "2026-10-02"}).json()
    assert d3["totals"]["events_in_period"] == len(source_unique(date(2026, 10, 1), date(2026, 10, 2)))
    assert len(d["recent_events"]) == 10 and len(d["recent_imports"]) == 8


def test_excel_export_structure_and_precision(loaded):
    c, _ = loaded
    r = c.get("/api/reports/export.xlsx", params={"date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert r.content[:2] == b"PK"  # настоящий xlsx (zip)
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Общий отчёт"] + sorted(STATIONS)
    ws = wb["Общий отчёт"]
    assert "01.10.2026" in ws["A3"].value and "Дата формирования" in ws["A4"].value
    assert ws.freeze_panes == "A8" and ws.auto_filter.ref.startswith("A7:Q")
    assert ws.max_row - 7 == 1234
    assert ws.cell(8, 2).number_format == "DD.MM.YYYY" and ws.cell(8, 4).number_format == "HH:MM:SS.0"
    assert ws.column_dimensions["A"].width >= 10 and ws.column_dimensions["Q"].width >= 40
    assert wb["KULK"]["A8"].value == "Нет данных за выбранный период"
    for code in STATIONS:
        n = sum(1 for _ in wb[code].iter_rows(min_row=8)) if code != "KULK" else 0
        assert n == {"ZAMN": 163, "BAYS": 259, "KOYT": 71, "KULK": 0, "PSK": 99, "SHRN": 416, "SOKH": 189, "TVKS": 37}[code]
    # точность: значения листа == значения в API
    api = c.get("/api/reports", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}).json()["events"]
    for i, e in enumerate(api[:300], start=8):
        row = [x.value for x in ws[i]]
        assert row[0] == e["station_code"] and row[1].date().isoformat() == e["event_date"] if hasattr(row[1], "date") else True
        assert row[7] == e["s_minus_p"] and row[8] == e["r_km"] and row[11] == e["mb"] and row[12] == e["ml"]
        assert row[3].strftime("%H:%M:%S") == e["p_time"][:8]
    # отдельные листы: только своя станция
    assert {r[0].value for r in wb["SHRN"].iter_rows(min_row=8)} == {"SHRN"}


def test_export_single_station_and_filtered(loaded):
    c, _ = loaded
    r = c.get("/api/reports/export.xlsx", params={"year": 2026, "stations": "KOYT"})
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Общий отчёт", "KOYT"] and wb["KOYT"].max_row - 7 == 71
    r = c.get("/api/events/export.xlsx", params={"stations": "SOKH", "mb_min": 4})
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Общий отчёт", "SOKH"]
    assert all(row[11].value >= 4 for row in wb["Общий отчёт"].iter_rows(min_row=8))
    assert c.get("/api/reports/export.xlsx").status_code == 422
