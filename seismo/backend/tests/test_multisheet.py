"""Многолистовой файл koytosh.xlsx (реальный): сводный лист + дубли месяцев + разные раскладки."""
import collections
from datetime import date

from app.db import SessionLocal
from app.models import SeismicEvent
from app.services.parsing import NUM_FIELDS, parse_excel, record_hash

from .conftest import SAMPLES, login

FILE = SAMPLES / "koytosh.xlsx"


def upload(client, path=FILE, name="koytosh.xlsx"):
    return ("files", (name, path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))


def source_keys():
    """Независимо от импортёра: все различные (дата, время P) во всех листах."""
    pf = parse_excel(FILE)
    return {(r.event_date, r.p_time) for r in pf.rows if r.kind == "data"}, pf


def test_all_sheets_read_and_station_detected(admin):
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    f = r["files"][0]
    assert f["station_code"] == "KOYT"                  # из колонки «Станция» (имя файла — koytosh)
    assert f["rows_error"] == 0                         # даты «01,02,2026» и шаблонные строки APREL — не ошибки
    assert sorted(f["preview"]["sheets"]) == sorted(["Yanvar", "FEVRAL", "APREL", "MAY", "IYUN", "IYUL", "avgust"])
    assert f["period_start"] == "2026-01-01" and f["period_end"] == "2026-08-31"


def test_no_event_lost_and_cross_sheet_dedup(admin):
    keys, pf = source_keys()
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    f = r["files"][0]
    data_rows = [x for x in pf.rows if x.kind == "data"]
    assert f["rows_total"] == len(data_rows) == f["rows_imported"] + f["rows_duplicate"] + f["rows_error"]
    admin.post(f"/api/imports/{r['id']}/commit")
    with SessionLocal() as db:
        evs = db.query(SeismicEvent).all()
        assert {(e.event_date, e.p_time.replace(microsecond=e.p_time.microsecond)) for e in evs} >= \
               {(d, t.replace(microsecond=t.microsecond)) for d, t in keys}   # ни одно событие не потеряно
        # месячные листы FEVRAL/APREL/MAY/IYUN целиком дублируют Yanvar → событий с этих листов в базе нет
        by_sheet = collections.Counter(e.source_sheet for e in evs)
    assert by_sheet["FEVRAL"] == by_sheet["APREL"] == by_sheet["MAY"] == by_sheet["IYUN"] == 0 or \
        sum(by_sheet[s] for s in ("FEVRAL", "APREL", "MAY", "IYUN")) < 20   # допустимо лишь несколько событий-расхождений
    assert by_sheet["Yanvar"] > 1300 and by_sheet["IYUL"] > 150 and by_sheet["avgust"] == 147


def test_august_report_works(admin):
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    admin.post(f"/api/imports/{r['id']}/commit")
    rep = admin.get("/api/reports", params={"date_from": "2026-08-01", "date_to": "2026-08-31", "stations": "KOYT"}).json()
    assert rep["total"] == 147 and rep["message"] is None   # ровно строки листа avgust
    ev = rep["events"][0]
    assert ev["event_date"] == "2026-08-01" and ev["s_minus_p"] == 10.2 and ev["mb"] == 2.1 and ev["ep_vp_vs"] is None


def test_no_garbage_in_ep_columns_and_flags_not_noisy(admin):
    """Регрессия: числа из боковой таблицы статистики не должны попадать в Ep Vp/Vs; отсутствующие колонки не помечают все строки."""
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    admin.post(f"/api/imports/{r['id']}/commit")
    with SessionLocal() as db:
        assert db.query(SeismicEvent).filter(SeismicEvent.ep_vp_vs.isnot(None)).count() == 0
        assert db.query(SeismicEvent).filter(SeismicEvent.ep_vp.isnot(None)).count() == 0
        total = db.query(SeismicEvent).count()
        flagged = db.query(SeismicEvent).filter(SeismicEvent.needs_review).count()
    assert 0 < flagged < total * 0.25      # помечены только реальные проблемы, а не все строки (раньше 929 из 929)


def test_sp_time_format_and_excel_errors(admin):
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    admin.post(f"/api/imports/{r['id']}/commit")
    jan = admin.get("/api/events", params={"stations": "KOYT", "date_from": "2026-01-01", "date_to": "2026-01-01",
                                           "sort": "p_time", "order": "asc"}).json()["items"][0]
    assert jan["s_minus_p"] == 45.5                      # «00:00:45,5» → 45.5 секунд
    apr = admin.get("/api/events", params={"stations": "KOYT", "date_from": "2026-04-01", "date_to": "2026-04-01"}).json()["items"][0]
    assert apr["s_minus_p"] is None and "excel_error:s_minus_p" in apr["review_reasons"]   # #VALUE! → NULL + пометка


def test_source_typos_flagged_not_guessed(admin):
    r = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    admin.post(f"/api/imports/{r['id']}/commit")
    ev = admin.get("/api/events", params={"stations": "KOYT", "date_from": "2026-02-22", "date_to": "2026-02-22",
                                          "needs_review": True}).json()["items"]
    bad = [e for e in ev if e["origin_time"] is None]          # время очага «10:1:44,4» — не угадываем
    assert bad and "parse:origin_time" in bad[0]["review_reasons"]


def test_koyt_two_files_coexist_and_rollback(admin):
    from .conftest import sample_files
    admin.post(f"/api/imports/{admin.post('/api/imports/preview', files=sample_files(['KOYT'])).json()['id']}/commit")
    b = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    done = admin.post(f"/api/imports/{b['id']}/commit").json()
    n_new = done["rows_imported"]
    st = {s["code"]: s for s in admin.get("/api/stations").json()}["KOYT"]
    assert st["events_count"] == 71 + n_new and st["first_date"] == "2026-01-01" and st["last_date"] == "2026-10-22"
    # откат только второго импорта — октябрьские данные на месте
    rb = admin.post(f"/api/imports/{b['id']}/rollback").json()
    assert rb["deleted"] == n_new
    st = {s["code"]: s for s in admin.get("/api/stations").json()}["KOYT"]
    assert st["events_count"] == 71 and st["first_date"] == "2026-10-01"
    assert admin.post(f"/api/imports/{b['id']}/rollback").status_code == 409     # повторный откат запрещён
    # после отката файл можно импортировать заново (хеши освобождены)
    b2 = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    assert b2["rows_imported"] == n_new


def test_rollback_needs_write_role(admin):
    admin.post("/api/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"})
    b = admin.post("/api/imports/preview", files=[upload(admin)]).json()
    admin.post(f"/api/imports/{b['id']}/commit")
    admin.post("/api/auth/logout"); login(admin, "viewer1", "Viewer1234")
    assert admin.post(f"/api/imports/{b['id']}/rollback").status_code == 403
