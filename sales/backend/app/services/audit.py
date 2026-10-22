from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.models import AuditLog


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


def audit(db: AsyncSession, user_id: int | None, action: str, entity_type: str | None = None,
          entity_id: object = None, meta: dict | None = None, request: Request | None = None) -> None:
    """Adds an audit row to the caller's transaction (committed with it)."""
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                    entity_id=None if entity_id is None else str(entity_id),
                    meta=redact(meta or {}), ip=client_ip(request)))
