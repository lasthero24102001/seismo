import hashlib
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import User, UserSession

_ph = PasswordHasher()
COOKIE = "seismo_session"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(hours=get_settings().session_ttl_hours)
    db.add(UserSession(id=_digest(token), user_id=user.id, expires_at=exp))
    db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc)))
    return token


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.scalar(select(UserSession).where(UserSession.id == _digest(token)))
    if not s or s.expires_at < datetime.now(timezone.utc):
        return None
    u = db.get(User, s.user_id)
    return u if u and u.is_active else None


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.id == _digest(token)))


def destroy_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))


# простейшая защита от перебора пароля: 5 неудач / 15 минут на (логин, ip)
_fails: dict[str, list[float]] = defaultdict(list)


def login_blocked(key: str) -> bool:
    now = time.time()
    _fails[key] = [t for t in _fails[key] if now - t < 900]
    return len(_fails[key]) >= 5


def login_failed(key: str) -> None:
    _fails[key].append(time.time())


def login_ok(key: str) -> None:
    _fails.pop(key, None)
