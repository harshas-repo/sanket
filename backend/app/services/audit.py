"""Audit log.

Every state change a human or the agent causes is written here with the previous
and new value, so "who changed what, when, and why" is always answerable. The
audit row is the accountability record for the trust model: an operator can
confirm something, and we can show exactly which operator did it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.core import AuditEvent, User, new_id
from shared.enums import AuditAction
from shared.timeutils import iso, utcnow

ENTITY_INCIDENT = "incident"
ENTITY_REPORT = "report"
ENTITY_REQUEST = "assistance_request"
ENTITY_RESOURCE = "resource"
ENTITY_SOURCE = "source"
ENTITY_USER = "user"


def record(
    db: Session,
    *,
    action: AuditAction | str,
    entity_type: str,
    entity_id: str,
    actor: User | None = None,
    actor_kind: str | None = None,
    previous: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    reason: str | None = None,
    commit: bool = False,
) -> AuditEvent:
    """Write one audit event.

    `actor_kind` is explicit rather than inferred: `operator`, `victim`, `system`
    and `agent` carry different authority, and the distinction has to survive into
    the log.
    """
    event = AuditEvent(
        id=new_id("aud"),
        actor_id=actor.id if actor else None,
        actor_label=(actor.display_name or actor.username) if actor else (actor_kind or "system"),
        actor_kind=actor_kind or ("operator" if actor else "system"),
        action=action.value if isinstance(action, AuditAction) else str(action),
        entity_type=entity_type,
        entity_id=entity_id,
        previous_value=previous,
        new_value=new,
        reason=reason,
        created_at=utcnow(),
    )
    db.add(event)
    if commit:
        db.commit()
    else:
        db.flush()
    return event


def for_entity(db: Session, entity_type: str, entity_id: str, limit: int = 100) -> list[AuditEvent]:
    return list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def recent(
    db: Session,
    limit: int = 50,
    actor_kind: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[AuditEvent]:
    """The log as a list, newest first, filtered by whoever and whatever you are
    looking into. `entity_id` only means anything alongside `entity_type`."""
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if actor_kind:
        stmt = stmt.where(AuditEvent.actor_kind == actor_kind)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_type and entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return list(db.execute(stmt).scalars())


def to_dict(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "actor": event.actor_label,
        "actor_kind": event.actor_kind,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "previous": event.previous_value,
        "new": event.new_value,
        "reason": event.reason,
        "at": iso(event.created_at),
    }
