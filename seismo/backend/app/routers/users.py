from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import admin_only
from ..models import User
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import destroy_user_sessions, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active)) or 0


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if db.scalar(select(User.id).where(func.lower(User.username) == data.username.lower())):
        raise HTTPException(409, "Пользователь с таким логином уже существует")
    u = User(username=data.username, full_name=data.full_name, role=data.role,
             password_hash=hash_password(data.password))
    db.add(u)
    db.flush()
    audit.log(db, "user_created", admin, request, "user", u.id, {"username": u.username, "role": u.role})
    db.commit()
    return u


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(admin_only)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    demoting = (data.role and data.role != "admin") or data.is_active is False
    if u.role == "admin" and u.is_active and demoting and _admins(db) <= 1:
        raise HTTPException(400, "Нельзя отключить или понизить последнего администратора")
    changes = {}
    for f in ("full_name", "role", "is_active"):
        v = getattr(data, f)
        if v is not None:
            setattr(u, f, v)
            changes[f] = v
    if data.password:
        u.password_hash = hash_password(data.password)
        changes["password"] = "изменён"
    if data.is_active is False or data.password:
        destroy_user_sessions(db, u.id)
    audit.log(db, "user_updated", admin, request, "user", u.id, changes)
    db.commit()
    return u


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя удалить самого себя")
    if u.role == "admin" and u.is_active and _admins(db) <= 1:
        raise HTTPException(400, "Нельзя удалить последнего администратора")
    audit.log(db, "user_deleted", admin, request, "user", u.id, {"username": u.username})
    db.delete(u)
    db.commit()
