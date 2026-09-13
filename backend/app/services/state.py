"""The live/demo switch and the simulated clock, as a service.

This lives here rather than in `deps` because both the API *and* the demo engine have to
read it, and a service importing the web layer would invert the dependency rule. `deps`
re-exports these two names so request-level code can keep importing them from where it
always has.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.core import SystemState

MODE_KEY = "mode"
LIVE: dict[str, Any] = {"mode": "live", "scenario_id": None, "sim_clock": None}


def system_mode(db: Session) -> dict[str, Any]:
    """Live vs demo mode. They are never mixed silently - every read path consults
    this and stamps responses with the active mode."""
    row = db.execute(select(SystemState).where(SystemState.key == MODE_KEY)).scalar_one_or_none()
    return (row.value if row else None) or dict(LIVE)


def set_system_mode(db: Session, value: dict[str, Any]) -> dict[str, Any]:
    row = db.execute(select(SystemState).where(SystemState.key == MODE_KEY)).scalar_one_or_none()
    if row is None:
        db.add(SystemState(key=MODE_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return value


def is_demo(db: Session) -> bool:
    return system_mode(db).get("mode") == "demo"
