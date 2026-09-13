"""Accounts: registration, demo seeding, login, profiles.

V1 keeps its own user table and never talks to an identity provider, so the demo
accounts have to be created here rather than expected from somewhere else. Two
things are deliberate:

* a community user is shown to responders only as an alias - the personal
  identity stays in this table;
* the demo accounts are clearly named and their password is fixed and published
  in the README, because a demo you cannot log into is not a demo.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.core import User, new_id
from backend.app.security import create_token, hash_password, verify_password
from shared.enums import ResponseCenterRank, Role
from shared.timeutils import iso, utcnow

DEMO_PASSWORD = "sanket123"

# (username, display name, role, rank, home district, language)
DEMO_ACCOUNTS: list[tuple[str, str, str, str | None, str | None, str]] = [
    ("sunita.rc", "Sunita Thapa", Role.RESPONSE_CENTER.value, ResponseCenterRank.OPERATOR.value, "Kathmandu", "en"),
    ("rajesh.rc", "Rajesh Karki", Role.RESPONSE_CENTER.value, ResponseCenterRank.COORDINATOR.value, "Kathmandu", "en"),
    ("analyst.rc", "Anita Gurung", Role.RESPONSE_CENTER.value, ResponseCenterRank.ANALYST.value, "Pokhara", "en"),
    ("ram.prasad", "Ram Prasad", Role.COMMUNITY.value, None, "Mustang", "ne"),
    ("sita.dev", "Sita Devi", Role.COMMUNITY.value, None, "Sindhupalchok", "ne"),
]


def _make_alias(user_id: str) -> str:
    """A stable, readable handle for responders: 'Community Member 1f3c'. The last
    characters of the id keep it tied to the account without exposing anything."""
    return f"Community Member {user_id[-4:]}"


def get_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username.strip().lower())).scalar_one_or_none()


def get(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def create(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = Role.COMMUNITY.value,
    rank: str | None = None,
    phone: str | None = None,
    home_district: str | None = None,
    preferred_language: str = "en",
) -> User:
    """Create an account. Raises ValueError on a taken username - the API turns
    that into a 409 with a message the person can act on."""
    handle = (username or "").strip().lower()
    if len(handle) < 3:
        raise ValueError("Username is too short")
    if get_by_username(db, handle) is not None:
        raise ValueError("That username is already taken")
    if role == Role.RESPONSE_CENTER.value and rank not in {r.value for r in ResponseCenterRank}:
        raise ValueError("A Response Center account needs a rank (operator, coordinator, analyst)")
    user = User(
        id=new_id("usr"),
        username=handle,
        display_name=(display_name or handle).strip()[:128],
        password_hash=hash_password(password) if password else "",
        role=role,
        rank=rank,
        phone=(phone or None),
        home_district=home_district,
        preferred_language=preferred_language if preferred_language in {"en", "ne"} else "en",
        is_active=True,
    )
    user.alias = _make_alias(user.id) if role == Role.COMMUNITY.value else user.display_name
    db.add(user)
    db.flush()
    return user


def ensure_demo_users(db: Session) -> int:
    """Idempotently create the published demo accounts. Returns how many were added."""
    added = 0
    for username, display_name, role, rank, district, language in DEMO_ACCOUNTS:
        if get_by_username(db, username) is not None:
            continue
        create(
            db,
            username=username,
            password=DEMO_PASSWORD,
            display_name=display_name,
            role=role,
            rank=rank,
            home_district=district,
            preferred_language=language,
        )
        added += 1
    if added:
        db.commit()
    return added


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = get_by_username(db, username)
    if user is None or not user.is_active:
        return None
    if not user.password_hash or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    return user


def issue_token(user: User) -> str:
    return create_token({"sub": user.id, "role": user.role, "rank": user.rank or ""})


def counts(db: Session) -> dict[str, int]:
    return {
        "total": db.execute(select(func.count(User.id))).scalar_one(),
        "response_center": db.execute(
            select(func.count(User.id)).where(User.role == Role.RESPONSE_CENTER.value)
        ).scalar_one(),
        "community": db.execute(
            select(func.count(User.id)).where(User.role == Role.COMMUNITY.value)
        ).scalar_one(),
    }


def to_dict(user: User, *, include_private: bool = False) -> dict[str, Any]:
    """Public profile shape. `password_hash` never leaves the database, and the
    phone number is only returned to the account owner."""
    data: dict[str, Any] = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "alias": user.alias,
        "role": user.role,
        "rank": user.rank,
        "is_response_center": user.role == Role.RESPONSE_CENTER.value,
        "preferred_language": user.preferred_language,
        "home_district": user.home_district,
        "permissions": sorted(_permissions_for(user)),
        "created_at": iso(user.created_at),
        "last_login_at": iso(user.last_login_at),
    }
    if include_private:
        data["phone"] = user.phone
    return data


def _permissions_for(user: User) -> set[str]:
    # Imported here because deps.py imports the models, and a module-level import
    # would make the two files depend on each other.
    from backend.app.deps import PERMISSIONS

    if user.role == Role.RESPONSE_CENTER.value:
        return PERMISSIONS.get(user.rank or ResponseCenterRank.OPERATOR.value, set())
    return PERMISSIONS.get("community_member", set())
