import collections
import io
from decimal import Decimal

from app.db import SessionLocal
from app.models import AuditLog, ImportIssue, SeismicEvent
from app.services.parsing import NUM_FIELDS, parse_excel, record_hash

from .conftest import SAMPLES, STATIONS, login, sample_files

# ожидаемые значения получены независимым анализом исходных Excel (docs/ANALYSIS.md)
EXPECT = {  # код: (строк данных, уникальных)
    "ZAMN": (185, 163), "BAYS": (272, 259), "KOYT": (77, 71), "KULK": (0, 0),
    "PSK": (104, 99), "SHRN": (421, 416), "SOKH": (196, 189), "TVKS": (44, 37)}


def test_preview_does_not_write_events(admin):
    r = admin.post("/api/imports/preview", files=sample_files())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "preview" and body["files_count"] == 8
    with SessionLocal() as db:
        assert db.query(SeismicEvent).count() == 0
    by = {f["station_code"]: f for f in body["files"]}
    assert set(by) == set(STATIONS)
    for code, (total, uniq) in EXPECT.items():
        f = by[code]
        assert f["rows_total"] == total and f["rows_imported"] == uniq, code
        assert f["rows_total"] == f["rows_imported"] + f["rows_duplicate"] + f["rows_error"]
    assert by["PSK"]["rows_flagged"] == 99          # все уникальные записи PSK помечены
    assert by["ZAMN"]["rows_flagged"] >= 1          # A(P)=3380.57
    assert by["PSK"]["parse_method"] == "excel"
    assert by["PSK"]["preview"]["rows"][0]["station"] == "PSK"  # PSKM → PSK


def test_commit_all_8_files_no_loss(loaded):
    client, body = loaded
    assert body["status"] == "committed"
    assert body["rows_total"] == 1299 and body["rows_imported"] == 1234 and body["rows_error"] == 0
    assert body["rows_duplicate"] == 65
    st = {s["code"]: s for s in client.get("/api/stations").json()}
    for code, (_, uniq) in EXPECT.items():
        assert st[code]["events_count"] == uniq, code
    # каждая пропущенная копия и служебная строка — в журнале импорта
    with SessionLocal() as db:
        assert db.query(ImportIssue).filter_by(code="duplicate_in_file").count() == 65
        assert db.query(ImportIssue).filter_by(code="note_row").count() == 1
        assert db.query(ImportIssue).filter_by(code="empty_rows").count() == 1  # пустые строки — одной сводной записью
        assert db.query(AuditLog).filter_by(action="import_commit").count() == 1


def test_values_identical_to_source(loaded):
    """Каждая уникальная запись источника есть в БД с теми же значениями (время, магнитуды, числа)."""
    with SessionLocal() as db:
        in_db = {(e.station.code, e.record_hash): e for e in db.query(SeismicEvent).all()}
        checked = 0
        for code in STATIONS:
            for r in parse_excel(SAMPLES / f"{code}_22_10_2026.xlsx").rows:
                if r.kind != "data":
                    continue
                e = in_db[(code, record_hash(code, r))]
                assert e.event_date == r.event_date and e.p_time == r.p_time
                assert e.s_time == r.s_time and e.origin_time == r.origin_time
                assert (e.p_phase, e.s_phase) == (r.p_phase, r.s_phase)
                for f in NUM_FIELDS:
                    assert getattr(e, f) == r.nums[f], (code, r.source_row, f)
                checked += 1
        assert checked == 1299
        # точность: время хранится с десятыми долями, исходные строки сохранены
        e = db.query(SeismicEvent).filter_by(source_no=1).join(SeismicEvent.station).filter_by(code="ZAMN").one()
        assert str(e.p_time) == "00:26:09.400000" and e.raw[4] == "00:26:09,4" and e.mb == Decimal("3.9")


def test_reimport_is_idempotent(loaded):
    client, _ = loaded
    r = client.post("/api/imports/preview", files=sample_files())
    assert r.json()["rows_imported"] == 0
    r = client.post(f"/api/imports/{r.json()['id']}/commit").json()
    assert r["rows_imported"] == 0 and r["rows_duplicate"] == 1299
    assert client.get("/api/events?page_size=1").json()["total"] == 1234


def test_near_duplicates_flagged_not_dropped(loaded):
    client, _ = loaded
    # ZAMN 01.10.2026 01:04:16,7 — две записи с разным S → обе сохранены и помечены
    items = client.get("/api/events?stations=ZAMN&date_from=2026-10-01&date_to=2026-10-01&page_size=100").json()["items"]
    pair = [i for i in items if i["p_time"] == "01:04:16.7"]
    assert len(pair) == 2 and all("near_duplicate" in i["review_reasons"] for i in pair)


def test_rejects_bad_files(admin):
    r = admin.post("/api/imports/preview", files=[("files", ("data.txt", b"hello", "text/plain"))])
    assert r.status_code == 415
    r = admin.post("/api/imports/preview", files=[("files", ("fake.xlsx", b"not a zip at all", "x"))])
    assert r.status_code == 415
    r = admin.post("/api/imports/preview", files=[("files", ("x.pdf", b"PK\x03\x04", "x"))])
    assert r.status_code == 415
    # корректная сигнатура, но битое содержимое → файл отмечен ошибкой, без падения
    r = admin.post("/api/imports/preview", files=[("files", ("ZAMN_bad.xlsx", b"PK\x03\x04broken", "x"))])
    assert r.status_code == 200 and r.json()["files"][0]["status"] == "failed"


def test_commit_is_atomic(admin, monkeypatch):
    from app.services import importer
    real, calls = importer.pg_insert, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("сбой диска")
        return real(*a, **k)

    monkeypatch.setattr(importer, "pg_insert", flaky)
    pid = admin.post("/api/imports/preview", files=sample_files()).json()["id"]
    r = admin.post(f"/api/imports/{pid}/commit")
    assert r.status_code == 500
    with SessionLocal() as db:
        assert db.query(SeismicEvent).count() == 0  # ни одной записи — откат целиком
    assert admin.get(f"/api/imports/{pid}").json()["status"] == "failed"
    monkeypatch.undo()


def test_unknown_station_is_created(admin):
    import openpyxl
    wb = openpyxl.load_workbook(SAMPLES / "TVKS_22_10_2026.xlsx")
    ws = wb.active
    for row in ws.iter_rows(min_row=3):
        row[1].value = "NEWS"
    buf = io.BytesIO(); wb.save(buf)
    r = admin.post("/api/imports/preview", files=[("files", ("bulletin_oct.xlsx", buf.getvalue(), "x"))]).json()
    assert r["files"][0]["station_code"] == "NEWS"
    admin.post(f"/api/imports/{r['id']}/commit")
    assert "NEWS" in [s["code"] for s in admin.get("/api/stations").json()]


def test_manual_edit_delete_and_audit(loaded):
    client, _ = loaded
    ev = client.get("/api/events?stations=PSK&page_size=1").json()["items"][0]
    assert ev["needs_review"] is True
    r = client.patch(f"/api/events/{ev['id']}", json={"mb": "4.5", "needs_review": False, "review_comment": "проверено"})
    assert r.status_code == 200 and r.json()["mb"] == 4.5 and r.json()["needs_review"] is False
    assert client.patch(f"/api/events/{ev['id']}", json={"r_km": -5}).status_code == 422
    assert client.delete(f"/api/events/{ev['id']}").status_code == 204
    assert client.get(f"/api/events/{ev['id']}").status_code == 404
    acts = {a["action"] for a in client.get("/api/admin/audit").json()["items"]}
    assert {"event_updated", "event_deleted", "import_commit", "login"} <= acts
