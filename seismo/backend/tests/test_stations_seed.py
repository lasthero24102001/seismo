import importlib.util

from sqlalchemy import text

from app.db import engine

from .conftest import ROOT, login

WANTED = ["SNGR", "YANG", "TSHT", "SKHM", "NZB", "NAN", "NUR", "MAM", "KZLS", "FRSH", "DJAN", "BOLG", "AGAL", "BKHM"]


def load_migration():
    spec = importlib.util.spec_from_file_location("m0004", ROOT / "alembic/versions/0004_new_stations.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_migration_adds_exactly_requested_stations_idempotently(clean):
    m = load_migration()
    assert m.NEW_STATIONS == WANTED                                   # ровно список заказчика, без опечаток
    with engine.begin() as c:
        c.execute(text("DELETE FROM stations WHERE code = ANY(:w)"), {"w": WANTED})
        m.insert_stations(c)
        m.insert_stations(c)                                          # повторный запуск ничего не дублирует
        rows = c.execute(text("SELECT code, name, is_active, aliases FROM stations WHERE code = ANY(:w) ORDER BY code"),
                         {"w": WANTED}).all()
    assert sorted(r.code for r in rows) == sorted(WANTED)
    assert all(r.name is None and r.is_active and r.aliases == [] for r in rows)   # названия не выдуманы


def test_existing_stations_untouched_by_migration(clean):
    m = load_migration()
    with engine.begin() as c:
        c.execute(text("UPDATE stations SET name = 'Тест' WHERE code = 'BAYS'"))
        m.insert_stations(c)
        assert c.execute(text("SELECT name FROM stations WHERE code='BAYS'")).scalar() == "Тест"


def test_bulk_add_stations(admin):
    r = admin.post("/api/stations/bulk", json={"codes": "zz1, ZZ2;zz1 BAYS pskm 1BAD TOOLONGCODE\nZZ3"}).json()
    assert r["created"] == ["ZZ1", "ZZ2", "ZZ3"]
    assert r["skipped"] == [{"code": "BAYS", "station": "BAYS"}, {"code": "PSKM", "station": "PSK"}]   # в т.ч. по алиасу
    assert r["invalid"] == ["1BAD", "TOOLONGCODE"]
    codes = [s["code"] for s in admin.get("/api/stations").json()]
    assert {"ZZ1", "ZZ2", "ZZ3"} <= set(codes)
    assert admin.post("/api/stations/bulk", json={"codes": "ZZ1 ZZ2"}).json()["created"] == []         # повтор — ничего нового
    assert admin.post("/api/stations/bulk", json={"codes": ""}).status_code == 422


def test_bulk_add_needs_write_role(admin):
    admin.post("/api/users", json={"username": "viewer7", "password": "Viewer1234", "role": "viewer"})
    admin.post("/api/auth/logout"); login(admin, "viewer7", "Viewer1234")
    assert admin.post("/api/stations/bulk", json={"codes": "QQ1"}).status_code == 403


FINAL = ["SNGR", "YANG", "TSHT", "SKHM", "NZB", "NUR", "NAN", "MAM", "QZLS", "FRSH", "DJAN", "BOLG", "AGAL", "BKHM"]


def load_0005():
    spec = importlib.util.spec_from_file_location("m0005", ROOT / "alembic/versions/0005_qzls_instead_of_kzls.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def codes(c):
    return {r[0] for r in c.execute(text("SELECT code FROM stations"))}


def test_qzls_replaces_kzls_final_list_matches_request(clean):
    m4, m5 = load_migration(), load_0005()
    with engine.begin() as c:
        c.execute(text("DELETE FROM stations WHERE code = ANY(:w) OR code IN ('QZLS','KZLS')"), {"w": WANTED})
        m4.insert_stations(c)                                         # состояние после 0004: есть KZLS, нет QZLS
        assert "KZLS" in codes(c) and "QZLS" not in codes(c)
        m5.swap(c, m5.ADD, m5.REMOVE)
        m5.swap(c, m5.ADD, m5.REMOVE)                                 # идемпотентно
        now = codes(c)
    assert "QZLS" in now and "KZLS" not in now
    assert set(FINAL) <= now and len(FINAL) == 14                      # весь заказанный список на месте


def test_kzls_with_data_is_not_deleted(clean):
    m4, m5 = load_migration(), load_0005()
    with engine.begin() as c:
        c.execute(text("DELETE FROM stations WHERE code IN ('QZLS','KZLS')"))
        m4.insert_stations(c)
        sid = c.execute(text("SELECT id FROM stations WHERE code='KZLS'")).scalar()
        c.execute(text("INSERT INTO seismic_events (station_id, event_date, record_hash) VALUES (:s, '2026-10-01', 'x')"), {"s": sid})
        m5.swap(c, m5.ADD, m5.REMOVE)
        assert {"KZLS", "QZLS"} <= codes(c)                            # со станцией есть данные — не удаляем, QZLS добавлена
        c.execute(text("DELETE FROM seismic_events"))


def load_0005():
    spec = importlib.util.spec_from_file_location("m0005", ROOT / "alembic/versions/0005_qzls_instead_of_kzls.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_qzls_replaces_unused_kzls(clean):
    m = load_0005()
    with engine.begin() as c:
        c.execute(text("INSERT INTO stations (code) VALUES ('KZLS') ON CONFLICT (code) DO NOTHING"))
        m.swap(c, m.ADD, m.REMOVE); m.swap(c, m.ADD, m.REMOVE)           # идемпотентно
        codes = {r[0] for r in c.execute(text("SELECT code FROM stations"))}
    assert "QZLS" in codes and "KZLS" not in codes


def test_kzls_with_data_is_kept(clean):
    m = load_0005()
    with engine.begin() as c:
        c.execute(text("INSERT INTO stations (code) VALUES ('KZLS') ON CONFLICT (code) DO NOTHING"))
        c.execute(text("INSERT INTO seismic_events (station_id, event_date, record_hash) "
                       "SELECT id, '2026-01-01', 'h-kzls' FROM stations WHERE code='KZLS'"))
        m.swap(c, m.ADD, m.REMOVE)
        codes = {r[0] for r in c.execute(text("SELECT code FROM stations"))}
    assert {"QZLS", "KZLS"} <= codes                                     # станция с данными не удаляется
