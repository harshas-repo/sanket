"""FastAPI dependencies: database session, current user, role authorization."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.db import SessionLocal
from backend.app.models.core import User
from backend.app.security import TokenClaims, parse_authorization
from backend.app.services.state import set_system_mode, system_mode
from shared.enums import Role

# What a duty operator may do. A coordinator gets all of it plus the destructive
# / configuration actions, so the two lists can never drift apart.
_OPERATOR_PERMISSIONS = {
    "assistance:read",
    "assistance:acknowledge",
    "assistance:assign",
    "assistance:status",
    "assistance:message_victim",
    "reports:read",
    "reports:verify",
    "reports:link",
    "incidents:read",
    "incidents:update",
    "incidents:merge",
    "resources:read",
    "resources:update",
    "sources:read",
    "sources:run",
    "agent:run",
    "demo:read",
    # An operator who cannot read the official alert feed cannot compare what the country
    # announced with what the platform is showing them - the one comparison that catches a
    # missed bulletin. This used to be a community-only permission.
    "alerts:read",
    # Who did what is supervisory: an analyst reads the situation, not the staff log.
    "audit:read",
}

PERMISSIONS: dict[str, set[str]] = {
    "operator": set(_OPERATOR_PERMISSIONS),
    "coordinator": _OPERATOR_PERMISSIONS
    | {"incidents:split", "settings:write", "demo:control"},
    "analyst": {
        "assistance:read",
        "reports:read",
        "incidents:read",
        "resources:read",
        "sources:read",
        "alerts:read",
        "agent:run",
    },
    "community_member": {
        "community:report",
        "community:request",
        "community:read_own",
        "alerts:read",
        "agent:chat",
    },
}

# Community users may browse public alert and incident context, but never other
# people's private assistance details - enforced here and again in the queries.
COMMUNITY_PUBLIC_READ = {"alerts:read", "incidents:read_public", "resources:read_public"}
PERMISSIONS["community_member"] |= COMMUNITY_PUBLIC_READ


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def token_claims(request: Request) -> TokenClaims | None:
    header = request.headers.get("authorization")
    if not header:
        token = request.query_params.get("token")
        if not token:
            return None
        return parse_authorization(f"Bearer {token}")
    return parse_authorization(header)


def current_claims(request: Request) -> TokenClaims:
    claims = token_claims(request)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    if claims.invalid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is not valid")
    if claims.expired:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, sign in again")
    return claims


def current_user(
    request: Request, db: Session = Depends(get_db), claims: TokenClaims = Depends(current_claims)
) -> User:
    user = db.get(User, claims.user_id or "")
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is no longer active")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if roles and user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This area requires a different account type"
            )
        return user

    return dependency


def require_permission(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Your role cannot perform '{permission}'"
            )
        return user

    return dependency


def granted_permissions(user: User) -> set[str]:
    """The whole permission set for this user.

    Handed to the services as plain data on purpose: a service must not have to know
    about the web layer to say which buttons this viewer may press.
    """
    if user.role == Role.RESPONSE_CENTER.value:
        return set(PERMISSIONS.get(user.rank or "operator", set()))
    return set(PERMISSIONS.get("community_member", set()))


def has_permission(user: User, permission: str) -> bool:
    return permission in granted_permissions(user)


def is_response_center(user: User) -> bool:
    return user.role == Role.RESPONSE_CENTER.value


# Re-exported from the service layer: the mode switch is read by the demo engine too, and
# a service may not import this module. Request code keeps importing it from here.
__all__ = [
    "get_db",
    "granted_permissions",
    "has_permission",
    "is_response_center",
    "require_permission",
    "set_system_mode",
    "system_mode",
    "token_claims",
    "current_user",
]
