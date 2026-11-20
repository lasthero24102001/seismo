"""agalik.xlsx (станция AGAL): нет колонки «Станция»; на части листа дата проставлена ОДИН РАЗ на сутки."""
import openpyxl

from app.db import SessionLocal
from app.models import SeismicEvent
from app.services.parsing import parse_excel

from .conftest import SAMPLES

FILE = SAMPLES / "agalik.xlsx"
NAME = "agalik проверить еще раз что то не так с файлом.xlsx"       # имя как у пользователя
UNRESOLVED = {938, 1082, 1083, 1084, 1085, 1086, 1087}               # сутки определить нельзя — не угадываем


def upload():
    return ("files", (NAME, FILE.read_bytes(), "x"))


def expected_dates():
    """Независимое от импортёра восстановление: дата явной строки либо ближайшей выше."""
    ws = openpyxl.load_workbook(FILE, data_only=True).worksheets[0]
    out, cur = {}, None
    for i, r in enumerate(ws.iter_rows(min_row=3, values_only=True), 3):
        v = r[1]
        if v:
            d, m, y = str(v).replace(",", ".").split(".") if not hasattr(v, "year") else (v.day, v.month, v.year)
            cur = f"{int(y)}-{int(m):02d}-{int(d):02d}"
            out[i] = (cur, True)
        elif r[0] is not None:
            out[i] = (cur, False)
    return out


def test_station_guessed_from_filename_and_data_reach_the_report(admin):
    """Сценарий пользователя: файл agalik.xlsx → станция AGAL определяется сама → импорт → данные в отчёте по AGAL."""
    admin.post("/api/stations/bulk", json={"codes": "AGAL"})
    r = admin.post("/api/imports/preview", files=[("files", ("agalik.xlsx", FILE.read_bytes(), "x"))]).json()
    f = r["files"][0]
    assert f["station_code"] == "AGAL" and f["status"] == "preview" and f["rows_total"] == 2463
    iss = admin.get(f"/api/imports/{r['id']}/issues", params={"file_id": f["id"], "page_size": 50}).json()["items"]
    assert any(i["code"] == "station_guessed" and "AGAL" in i["message"] for i in iss)    # пользователь видит, откуда станция
    done = admin.post(f"/api/imports/{r['id']}/commit").json()
    assert done["rows_imported"] > 2000
    rep = admin.get("/api/reports", params={"year": 2026, "stations": "AGAL"}).json()       # то, что не находил пользователь
    assert rep["total"] == done["rows_imported"] > 0 and rep["message"] is None


def test_short_code_only_suggested_not_assigned(admin):
    admin.post("/api/stations/bulk", json={"codes": "NAN"})
    f = admin.post("/api/imports/preview", files=[("files", ("nanosec.xlsx", FILE.read_bytes(), "x"))]).json()["files"][0]
    assert f["station_code"] is None and f["status"] == "failed" and f["station_suggestions"] == ["NAN"]
    assert "2463" in f["message"]                                        # видно, что строки в файле найдены


def test_cannot_commit_when_nothing_importable(admin):
    f = admin.post("/api/imports/preview", files=[("files", ("qqq_unknown.xlsx", FILE.read_bytes(), "x"))]).json()
    assert f["files"][0]["status"] == "failed"
    r = admin.post(f"/api/imports/{f['id']}/commit")
    assert r.status_code == 409 and "Импортировать нечего" in r.json()["detail"]
    assert admin.get("/api/dashboard").json()["totals"]["events"] == 0   # в базу ничего не попало


def test_full_import_with_manual_station_and_date_restoration(admin):
    admin.post("/api/stations/bulk", json={"codes": "AGAL"})
    r = admin.post("/api/imports/preview", files=[upload()]).json()
    r2 = admin.patch(f"/api/imports/{r['id']}/files/{r['files'][0]['id']}", json={"station_code": "AGAL"}).json()
    f = r2["files"][0]
    assert f["station_code"] == "AGAL" and f["rows_total"] == 2463 and f["rows_error"] == len(UNRESOLVED)
    admin.post(f"/api/imports/{r['id']}/commit")

    exp = expected_dates()
    with SessionLocal() as db:
        evs = {e.source_row: e for e in db.query(SeismicEvent).filter(SeismicEvent.source_row.isnot(None))}
    assert not (UNRESOLVED & set(evs))                                   # неопределимые строки не импортированы
    checked = 0
    for row, (d, explicit) in exp.items():
        if row in UNRESOLVED or row not in evs:                          # (часть строк — дубликаты по содержимому)
            continue
        assert evs[row].event_date.isoformat() == d, row                 # дата восстановлена верно
        assert (evs[row].review_comment is None) == explicit, row        # у восстановленных есть пояснение
        checked += 1
    assert checked > 2000


def test_lost_day_boundary_chain_is_flagged(admin):
    """Стр. 847: явная дата 05.04, но время «откатилось» (23:18 → 08:00) — граница суток потеряна. Цепочка 847–857 помечена."""
    admin.post("/api/stations/bulk", json={"codes": "AGAL"})
    r = admin.post("/api/imports/preview", files=[upload()]).json()
    admin.patch(f"/api/imports/{r['id']}/files/{r['files'][0]['id']}", json={"station_code": "AGAL"})
    admin.post(f"/api/imports/{r['id']}/commit")
    with SessionLocal() as db:
        flagged = {e.source_row for e in db.query(SeismicEvent).filter(SeismicEvent.review_reasons.any("date_time_order"))}
    assert flagged == set(range(847, 858))
    # журнал: понятные ошибки по нерешённым строкам
    issues = admin.get(f"/api/imports/{r['id']}/issues", params={"severity": "error", "page_size": 50}).json()["items"]
    assert {i["row_number"] for i in issues} == UNRESOLVED and any("смена суток" in i["message"] for i in issues)


# ── правило на синтетических данных
def make_sheet(tmp_path, rows):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["№", "Станция", "Дата", "P волна", None, "S волна", None, "Время в очаге", "S-P", "R км", "A в мк/с", None, "Mb", "ML"])
    ws.append([None, None, None, "Фаза", "Время ч.м.с.", "Фаза", "Время ч.м.с.", None, None, None, "P", "S", None, None])
    for i, (d, p) in enumerate(rows, 1):
        ws.append([i, "AGAL", d, "Pg", p, "Sg", "23:59:59,0", "00:00:01,0", 10, 100, 1, 1, 3, 3])
    path = tmp_path / "t.xlsx"; wb.save(path)
    return parse_excel(path)


def test_date_restoration_rules(tmp_path):
    pf = make_sheet(tmp_path, [("01.04.2026", "10:00:00,0"), (None, "11:00:00,0"), (None, "11:30:00,0"),
                               (None, "09:00:00,0"), ("02.04.2026", "01:00:00,0"), (None, "02:00:00,0")])
    k = [(r.kind, str(r.event_date)) for r in pf.rows]
    assert k[1] == ("data", "2026-04-01") and k[2] == ("data", "2026-04-01")   # время растёт → те же сутки
    assert k[3][0] == "invalid"                                                # время назад → не угадываем
    assert k[4] == ("data", "2026-04-02") and k[5] == ("data", "2026-04-02")
    assert pf.rows[1].note and pf.rows[0].note is None


def test_no_date_at_top_stays_error(tmp_path):
    pf = make_sheet(tmp_path, [(None, "10:00:00,0"), ("01.04.2026", "11:00:00,0")])
    assert pf.rows[0].kind == "invalid" and "дата отсутствует" in pf.rows[0].error
