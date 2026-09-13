"""Notification store.

V1 delivers notifications in-app (they are pulled, not pushed): the Community app
and the Response Center bell both read from here. Nothing is sent to SMS or email
because no provider is configured - the API is deliberately shaped so a real
gateway can be added later without changing who is notified about what.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.core import Notification, new_id
from shared.timeutils import humanize_age, iso, utcnow

AUDIENCE_COMMUNITY = "community"
AUDIENCE_RESPONSE_CENTER = "response_center"


def push(
    db: Session,
    *,
    audience: str,
    title: str,
    body: str,
    kind: str = "info",
    severity: str = "information",
    user_id: str | None = None,
    link: str | None = None,
    request_id: str | None = None,
    incident_id: str | None = None,
    district: str | None = None,
    provenance: str = "derived",
    commit: bool = False,
) -> Notification:
    note = Notification(
        id=new_id("ntf"),
        user_id=user_id,
        audience=audience,
        title=title[:250],
        body=body,
        kind=kind,
        severity=severity,
        link=link,
        request_id=request_id,
        incident_id=incident_id,
        district=district,
        provenance=provenance,
        created_at=utcnow(),
    )
    db.add(note)
    if commit:
        db.commit()
    else:
        db.flush()
    return note


def for_user(db: Session, user_id: str, district: str | None = None, limit: int = 60) -> list[Notification]:
    """Personal notifications plus area-wide ones for the user's district."""
    area_wide = and_(
        Notification.user_id.is_(None),
        Notification.district == district if district else Notification.district.is_(None),
    )
    stmt = (
        select(Notification)
        .where(or_(Notification.user_id == user_id, area_wide))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def for_response_center(db: Session, limit: int = 60) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.audience == AUDIENCE_RESPONSE_CENTER)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def unread_count(db: Session, *, user_id: str | None = None, audience: str | None = None) -> int:
    stmt = select(func.count(Notification.id)).where(Notification.read_at.is_(None))
    if user_id:
        stmt = stmt.where(Notification.user_id == user_id)
    if audience:
        stmt = stmt.where(Notification.audience == audience)
    return db.execute(stmt).scalar_one()


def mark_read(db: Session, notification_id: str, user_id: str | None = None) -> bool:
    note = db.get(Notification, notification_id)
    if note is None:
        return False
    if user_id and note.user_id not in (None, user_id):
        return False
    note.read_at = utcnow()
    db.flush()
    return True


def mark_all_read(db: Session, *, user_id: str | None = None, audience: str | None = None) -> int:
    stmt = select(Notification).where(Notification.read_at.is_(None))
    if user_id:
        stmt = stmt.where(Notification.user_id == user_id)
    if audience:
        stmt = stmt.where(Notification.audience == audience)
    rows = list(db.execute(stmt).scalars())
    now = utcnow()
    for note in rows:
        note.read_at = now
    db.flush()
    return len(rows)


def to_dict(note: Notification) -> dict[str, Any]:
    return {
        "id": note.id,
        "audience": note.audience,
        "title": note.title,
        "body": note.body,
        "kind": note.kind,
        "severity": note.severity,
        "link": note.link,
        "request_id": note.request_id,
        "incident_id": note.incident_id,
        "district": note.district,
        "read": note.read_at is not None,
        "at": iso(note.created_at),
        "age": humanize_age(note.created_at),
        "provenance": note.provenance,
    }
