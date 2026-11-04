"""Audit log helper. It adds a row and never commits: the caller's transaction
decides whether the row and the change it describes both happen or neither."""

from typing import Any

from sqlalchemy.orm import Session

from critisizer.models import AuditLog, User


def record_audit(
    session: Session,
    action: str,
    target_type: str,
    target_id: int | None,
    details: dict[str, Any] | None = None,
    actor: User | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=None if actor is None else actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    session.add(entry)
    return entry
