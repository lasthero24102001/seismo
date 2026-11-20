"""Редактирование записей (исправление ошибок Excel): времена P/S/очага, значения, станция, история, пересчёт проверок."""
import io

import openpyxl

from app.db import SessionLocal
from app.models import SeismicEvent

from .conftest import login


def first(client, **params):
    return client.get("/api/events", params={"page_size": 1, **params}).json()["items"][0]


def clean_event(client):
    """Любая запись SOKH без пометок."""
    items = client.get("/api/events", params={"stations": "SOKH", "needs_review": False, "page_size": 5}).json()["items"]
    return items[0]


def test_fix_wrong_s_time_flag_set_then_cleared_automatically(loaded):
    c, _ = loaded
    e = clean_event(c)
    assert e["needs_review"] is False
    # в Excel ошиблись: время S раньше времени P → запись помечается
    bad = c.patch(f"/api/events/{e['id']}", json={"s_time": "00:00:01,0"}).json()
    assert bad["needs_review"] is True and "time_order" in bad["review_reasons"]
    # исправляем время S обратно (запятая как в Excel) → пометка снимается САМА
    fixed = c.patch(f"/api/events/{e['id']}", json={"s_time": e["s_time"].replace(".", ",")}).json()
    assert fixed["s_time"] == e["s_time"] and fixed["needs_review"] is False and fixed["review_reasons"] == []


def test_editing_p_origin_times_and_values(loaded):
    c, _ = loaded
    e = clean_event(c)
    r = c.patch(f"/api/events/{e['id']}", json={"p_time": "01:02:03,4", "origin_time": "01:01:30,0", "mb": "3,7",
                                                "r_km": "123,5", "p_phase": " Pn "}).json()
    assert r["p_time"] == "01:02:03.4" and r["origin_time"] == "01:01:30.0"
    assert r["mb"] == 3.7 and r["r_km"] == 123.5 and r["p_phase"] == "Pn"          # запятая, пробелы — как в Excel
    # исходная строка из файла остаётся нетронутой
    full = c.get(f"/api/events/{e['id']}").json()
    assert full["raw"] and full["updated_at"] is not None


def test_fixing_the_anomalous_value_removes_its_flag(loaded):
    c, _ = loaded
    e = next(x for x in c.get("/api/events", params={"stations": "ZAMN", "needs_review": True, "page_size": 20}).json()["items"]
             if "amp_range" in x["review_reasons"])                       # ZAMN: A(P)=3380.57
    assert e["amp_p"] > 1000
    r = c.patch(f"/api/events/{e['id']}", json={"amp_p": "3,38"}).json()
    assert "amp_range" not in r["review_reasons"] and r["amp_p"] == 3.38
    if r["review_reasons"] == []:
        assert r["needs_review"] is False


def test_context_flags_survive_unrelated_edit(loaded):
    c, _ = loaded
    pair = [x for x in c.get("/api/events", params={"stations": "ZAMN", "date_from": "2026-10-01", "date_to": "2026-10-01",
                                                    "page_size": 100}).json()["items"] if "near_duplicate" in x["review_reasons"]][0]
    r = c.patch(f"/api/events/{pair['id']}", json={"mb": pair["mb"]}).json()     # ничего не меняем
    assert "near_duplicate" in r["review_reasons"]
    r = c.patch(f"/api/events/{pair['id']}", json={"ml": "2,0"}).json()          # правим несвязанное поле
    assert "near_duplicate" in r["review_reasons"]


def test_explicit_review_status(loaded):
    c, _ = loaded
    e = clean_event(c)
    r = c.patch(f"/api/events/{e['id']}", json={"needs_review": True, "review_comment": "уточнить у оператора"}).json()
    assert r["needs_review"] is True and r["review_reasons"] == ["manual"] and r["review_comment"] == "уточнить у оператора"
    r = c.patch(f"/api/events/{e['id']}", json={"needs_review": False}).json()
    assert r["needs_review"] is False and r["review_reasons"] == []
    psk = first(c, stations="PSK", needs_review=True)
    r = c.patch(f"/api/events/{psk['id']}", json={"needs_review": False}).json()   # «Проверено» вручную
    assert r["needs_review"] is False and r["review_reasons"] == []


def test_history_shows_old_and_new(loaded):
    c, _ = loaded
    e = clean_event(c)
    c.patch(f"/api/events/{e['id']}", json={"origin_time": "02:00:00,0"})
    c.patch(f"/api/events/{e['id']}", json={"origin_time": "03:00:00,0", "mb": "4,4"})
    h = c.get(f"/api/events/{e['id']}/history").json()
    assert len(h) == 2 and h[0]["username"] == "admin"
    assert h[0]["changes"]["origin_time"] == ["02:00:00.0", "03:00:00.0"]       # было → стало
    assert h[1]["changes"]["origin_time"][1] == "02:00:00.0"
    assert c.get("/api/events/99999999/history").status_code == 404


def test_move_event_to_another_station(loaded):
    c, _ = loaded
    e = clean_event(c)
    before = {s["code"]: s["events_count"] for s in c.get("/api/stations").json()}
    r = c.patch(f"/api/events/{e['id']}", json={"station_code": "tvks"}).json()
    assert r["station_code"] == "TVKS"
    after = {s["code"]: s["events_count"] for s in c.get("/api/stations").json()}
    assert after["SOKH"] == before["SOKH"] - 1 and after["TVKS"] == before["TVKS"] + 1
    assert c.patch(f"/api/events/{e['id']}", json={"station_code": "NOPE"}).status_code == 422
    assert c.patch(f"/api/events/{e['id']}", json={"station_code": "PSKM"}).json()["station_code"] == "PSK"   # алиас


def test_invalid_input_rejected_and_nothing_changes(loaded):
    c, _ = loaded
    e = clean_event(c)
    for bad in ({"p_time": "25:61:00"}, {"mb": "abc"}, {"event_date": None}, {"amp_p": -1}, {"s_minus_p": "-3"}):
        assert c.patch(f"/api/events/{e['id']}", json=bad).status_code == 422, bad
    assert c.get(f"/api/events/{e['id']}").json()["p_time"] == e["p_time"]
    r = c.patch(f"/api/events/{e['id']}", json={"s_minus_p": None}).json()      # очистить значение можно
    assert r["s_minus_p"] is None


def test_edits_visible_in_report_and_excel(loaded):
    c, _ = loaded
    e = clean_event(c)
    c.patch(f"/api/events/{e['id']}", json={"s_time": "12:34:56,7", "mb": "5,5"})
    rep = c.get("/api/reports", params={"year": 2026, "stations": "SOKH"}).json()
    got = next(x for x in rep["events"] if x["id"] == e["id"])
    assert got["s_time"] == "12:34:56.7" and got["mb"] == 5.5
    wb = openpyxl.load_workbook(io.BytesIO(c.get("/api/reports/export.xlsx", params={"year": 2026, "stations": "SOKH"}).content))
    vals = [(row[5].value, row[11].value) for row in wb["SOKH"].iter_rows(min_row=8)]
    assert any(v[0] is not None and v[0].strftime("%H:%M:%S") == "12:34:56" and v[1] == 5.5 for v in vals)


def test_viewer_cannot_edit(loaded):
    c, _ = loaded
    e = clean_event(c)
    c.post("/api/users", json={"username": "viewer9", "password": "Viewer1234", "role": "viewer"})
    c.post("/api/auth/logout"); login(c, "viewer9", "Viewer1234")
    assert c.patch(f"/api/events/{e['id']}", json={"mb": "1,0"}).status_code == 403
    assert c.get(f"/api/events/{e['id']}/history").status_code == 200          # читать историю можно
