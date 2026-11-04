from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import LoginIn, PasswordChange, UserOut
from ..security import (COOKIE, create_session, destroy_session, destroy_user_sessions, hash_password,
                        login_blocked, login_failed, login_ok, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY = hash_password("dummy-password-for-timing")


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{data.username.lower()}|{request.client.host if request.client else '-'}"
    if login_blocked(key):
        raise HTTPException(429, "Слишком много неудачных попыток. Повторите через 15 минут")
    user = db.scalar(select(User).where(User.username == data.username.strip()))
    ok = verify_password(data.password, user.password_hash if user else _DUMMY)
    if not (user and ok and user.is_active):
        login_failed(key)
        audit.log(db, "login_failed", request=request, username=data.username[:64])
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    login_ok(key)
    user.last_login_at = datetime.now(timezone.utc)
    token = create_session(db, user)
    audit.log(db, "login", user, request)
    db.commit()
    cfg = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=cfg.cookie_secure,
                        max_age=cfg.session_ttl_hours * 3600, path="/")
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    destroy_session(db, token)
    db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/change-password", status_code=204)
def change_password(data: PasswordChange, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    user.password_hash = hash_password(data.new_password)
    destroy_user_sessions(db, user.id)
    audit.log(db, "password_changed", user, request)
    db.commit()
