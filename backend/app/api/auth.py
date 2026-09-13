"""Authentication routes.

Login returns a bearer token and the account's resolved permissions, so the
frontend can route on capability rather than guessing from the username.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.deps import current_user, get_db, system_mode
from backend.app.models.core import User
from backend.app.schemas import LoginIn, ProfilePatch, RegisterIn
from backend.app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = user_service.authenticate(db, body.username, body.password)
    if user is None:
        # Same answer for unknown user and wrong password - the API must not be a
        # way to find out which names exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username or password is not correct")
    return {
        "token": user_service.issue_token(user),
        "user": user_service.to_dict(user, include_private=True),
        "surface": "response_center" if user.role == "response_center" else "community",
        "mode": system_mode(db),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    if body.role == "response_center":
        if not settings.allow_demo_accounts:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Response Center accounts are provisioned by an administrator, not registered",
            )
        if not settings.secret_key:
            # Without a real secret the tokens are signed with a published default,
            # so granting operator access over such a channel is not acceptable.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Set SANKET_SECRET_KEY before creating Response Center accounts",
            )
    try:
        user = user_service.create(
            db,
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            rank=body.rank,
            phone=body.phone,
            home_district=body.home_district,
            preferred_language=body.preferred_language,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return {"token": user_service.issue_token(user), "user": user_service.to_dict(user, include_private=True)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_service.to_dict(user, include_private=True)}


@router.patch("/me")
def patch_me(
    body: ProfilePatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return {"user": user_service.to_dict(user, include_private=True)}


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)) -> dict:
    """The published demo logins. Only available when demo accounts are allowed,
    and it exists so a reviewer can sign in without reading the source."""
    if not settings.allow_demo_accounts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo accounts are disabled")
    added = user_service.ensure_demo_users(db)
    return {
        "password": user_service.DEMO_PASSWORD,
        "created_now": added,
        "accounts": [
            {
                "username": username,
                "display_name": display_name,
                "role": role,
                "rank": rank,
                "surface": "response_center" if role == "response_center" else "community",
            }
            for username, display_name, role, rank, _district, _language in user_service.DEMO_ACCOUNTS
        ],
    }
