import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .config import get_settings
from .db import SessionLocal
from .models import User
from .routers import admin, auth, dashboard, events, imports, reports, stations, users
from .security import hash_password

log = logging.getLogger("seismo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    Path(cfg.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.backup_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        if (db.scalar(select(func.count()).select_from(User)) or 0) == 0:
            db.add(User(username=cfg.admin_username, full_name=cfg.admin_full_name, role="admin",
                        password_hash=hash_password(cfg.admin_password)))
            db.commit()
            log.warning("Создан администратор «%s». Смените пароль после первого входа!", cfg.admin_username)
    yield


app = FastAPI(title="Seismo — учёт сейсмологических бюллетеней", version="1.0.0", lifespan=lifespan)
origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
for r in (auth, users, stations, events, imports, reports, dashboard, admin):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Необработанная ошибка: %s", request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
