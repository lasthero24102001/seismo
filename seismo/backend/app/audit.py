from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def log(db: Session, action: str, user: User | None = None, request: Request | None = None,
        entity_type: str | None = None, entity_id=None, details: dict | None = None,
        username: str | None = None) -> None:
    db.add(AuditLog(
        user_id=user.id if user else None, username=user.username if user else username,
        action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None,
        details=details, ip=request.client.host if request and request.client else None))
