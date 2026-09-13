"""Agent routes: investigate, ask, classify, and see what the agent is allowed to do.

Two of these are Response Center tools and one is a resident's. The permission names keep
them apart - `agent:run` for the operator surface, `agent:chat` for a community account -
and the tools an agent may call are built from the *caller's* permission set, so an agent
can never be used to read past the person standing in front of it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.deps import get_db, granted_permissions, require_permission
from backend.app.models.core import Incident, User
from backend.app.schemas import AgentClassifyIn, AgentInvestigateIn, AgentRespondIn, ChatIn
from backend.app.services import agent as agent_service
from shared.timeutils import iso, utcnow

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/status")
def agent_status(
    _user: User = Depends(require_permission("agent:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Whether a model is reachable, what runs when it is not, and what has run before."""
    return {
        **agent_service.model_status(),
        "runs": agent_service.stats(db),
        "generated_at": iso(utcnow()),
    }


@router.get("/tools")
def agent_tools(
    _user: User = Depends(require_permission("agent:run")),
) -> dict[str, Any]:
    """The tool inventory: names, descriptions and arguments. Read-only by construction."""
    return agent_service.inventory()


@router.post("/investigate")
def investigate(
    body: AgentInvestigateIn,
    user: User = Depends(require_permission("agent:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Investigate one incident and store the run."""
    incident = (
        db.get(Incident, body.incident_id)
        if body.incident_id
        else db.execute(
            select(Incident).where(Incident.ref_code == body.ref_code)
        ).scalar_one_or_none()
    )
    if incident is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No incident matches that id or ref code. Search with GET /api/incidents.",
        )
    return {
        **agent_service.investigate_incident(
            db, incident, permissions=granted_permissions(user), actor=user
        ),
        "generated_at": iso(utcnow()),
    }


@router.post("/respond")
def respond(
    body: AgentRespondIn,
    user: User = Depends(require_permission("agent:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Take one victim report through the agent: understand it, check what can be checked,
    file the request if help is needed, and say what happened.

    This is the only agent route that writes. What it may write is bounded in code, not in a
    prompt: the report's own words set the priority inputs, the location is geocoded rather
    than accepted, the case is created by the same service the community form drives, and no
    status transition is reachable from here. The `activity` list it returns is the tool and
    step names with their statuses and results - deliberately not the model's reasoning.

    `incident_id` links the case to a tracked incident; it is validated against the database
    by the tools, so a made-up one files an unlinked request rather than a wrong link.
    """
    return {
        **agent_service.respond(
            db,
            body.text,
            permissions=granted_permissions(user),
            operator=user,
            report_id=body.report_id,
            incident_id=body.incident_id,
        ),
        "generated_at": iso(utcnow()),
    }


@router.get("/investigations")
def investigations(
    incident_id: str,
    limit: int = 10,
    _user: User = Depends(require_permission("agent:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Previous runs for one incident, newest first - including the rejected ones."""
    rows = agent_service.for_incident(db, incident_id, limit=min(max(limit, 1), 50))
    return {
        "count": len(rows),
        "items": rows,
        "note": (
            "A run whose status is 'rejected_unverified_numbers' produced wording the system "
            "could not trace to a record; the deterministic answer is what was shown."
        ),
    }


@router.post("/chat")
def chat(
    body: ChatIn,
    user: User = Depends(require_permission("agent:chat")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Answer a resident about their own area, from the same records their screen shows.

    `body.language` is accepted and ignored on purpose: the reply follows the language the
    question was actually written in, then the saved preference, so a mismatch in the form
    cannot produce an answer nobody asked for.
    """
    return {
        **agent_service.chat(db, user=user, question=body.message, district=body.district),
        "generated_at": iso(utcnow()),
    }


@router.post("/classify")
def classify(
    body: AgentClassifyIn,
    _user: User = Depends(require_permission("agent:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Read one piece of community text. Deterministic unless `use_model` is asked for."""
    return agent_service.classify_text(db, body.text, with_model=body.use_model)
