import os
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_DB = "postgresql+psycopg://seismo:seismo@localhost:5432/seismo_test"
os.environ["DATABASE_URL"] = TEST_DB
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="seismo_up_")
os.environ["BACKUP_DIR"] = tempfile.mkdtemp(prefix="seismo_bk_")
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "AdminPass123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT.parent / "samples"
STATIONS = ["ZAMN", "BAYS", "KOYT", "KULK", "PSK", "SHRN", "SOKH", "TVKS"]


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    env = {**os.environ}
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)


@pytest.fixture()
def clean():
    from app.db import engine
    with engine.begin() as c:
        c.execute(text("TRUNCATE seismic_events, import_issues, import_files, import_batches, audit_logs, "
                       "sessions RESTART IDENTITY CASCADE"))
        c.execute(text("DELETE FROM users WHERE username <> 'admin'"))
        c.execute(text("DELETE FROM stations WHERE code NOT IN ('ZAMN','BAYS','KOYT','KULK','PSK','SHRN','SOKH','TVKS')"))
        c.execute(text("UPDATE stations SET aliases = '{}', name = NULL, is_active = true WHERE code <> 'PSK'"))
        c.execute(text("UPDATE stations SET aliases = '{PSKM}', name = NULL, is_active = true WHERE code = 'PSK'"))


@pytest.fixture()
def client(clean):
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, username="admin", password="AdminPass123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture()
def admin(client):
    login(client)
    return client


def sample_files(codes=STATIONS):
    return [("files", (f"{c}_22_10_2026.xlsx", (SAMPLES / f"{c}_22_10_2026.xlsx").read_bytes(),
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")) for c in codes]


@pytest.fixture()
def loaded(admin):
    """Все 8 файлов импортированы."""
    r = admin.post("/api/imports/preview", files=sample_files())
    assert r.status_code == 200, r.text
    r = admin.post(f"/api/imports/{r.json()['id']}/commit")
    assert r.status_code == 200, r.text
    return admin, r.json()
