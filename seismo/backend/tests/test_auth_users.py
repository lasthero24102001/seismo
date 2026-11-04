from .conftest import login, sample_files


def test_protected_routes_require_login(client):
    for url in ["/api/events", "/api/stations", "/api/dashboard", "/api/reports?year=2026", "/api/users"]:
        assert client.get(url).status_code == 401


def test_login_logout_and_wrong_password(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
    login(client)
    assert client.get("/api/auth/me").json()["role"] == "admin"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_password_is_hashed_argon2(client):
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        h = db.query(User).filter_by(username="admin").one().password_hash
    assert h.startswith("$argon2") and "AdminPass123" not in h


def test_user_management_and_roles(admin):
    r = admin.post("/api/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"})
    assert r.status_code == 201
    assert admin.post("/api/users", json={"username": "VIEWER1", "password": "Viewer1234"}).status_code == 409
    assert admin.post("/api/users", json={"username": "x", "password": "short"}).status_code == 422
    op = admin.post("/api/users", json={"username": "oper1", "password": "Operator123", "role": "operator"}).json()
    uid = r.json()["id"]
    # viewer: читает, но не импортирует/не правит/не управляет пользователями
    admin.post("/api/auth/logout")
    login(admin, "viewer1", "Viewer1234")
    assert admin.get("/api/stations").status_code == 200
    assert admin.get("/api/users").status_code == 403
    assert admin.post("/api/imports/preview", files=sample_files(["KULK"])).status_code == 403
    assert admin.delete("/api/events/1").status_code == 403
    admin.post("/api/auth/logout")
    login(admin, "oper1", "Operator123")
    assert admin.post("/api/imports/preview", files=sample_files(["KULK"])).status_code == 200
    assert admin.get("/api/users").status_code == 403
    admin.post("/api/auth/logout")
    login(admin)
    # нельзя удалить себя / последнего админа
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.delete(f"/api/users/{me}").status_code == 400
    assert admin.patch(f"/api/users/{me}", json={"role": "viewer"}).status_code == 400
    assert admin.delete(f"/api/users/{uid}").status_code == 204
    # отключённый пользователь не может войти
    admin.patch(f"/api/users/{op['id']}", json={"is_active": False})
    admin.post("/api/auth/logout")
    assert admin.post("/api/auth/login", json={"username": "oper1", "password": "Operator123"}).status_code == 401
