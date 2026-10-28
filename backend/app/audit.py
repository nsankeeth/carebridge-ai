import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None,
    *,
    actor: User | None = None,
    actor_type: str | None = None,
    org_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an audit event in the caller's transaction. Keep `details` free of medical content."""
    event = AuditEvent(
        org_id=org_id or (actor.org_id if actor else None),
        actor_user_id=actor.id if actor else None,
        actor_type=actor_type or ("USER" if actor else "SYSTEM"),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        details=details or {},
    )
    db.add(event)
    return event
