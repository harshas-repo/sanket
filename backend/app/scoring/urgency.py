"""Deterministic urgency classification and response SLAs.

Urgency is decided by rules over structured fields, never by the model. The LLM
only extracts the structured fields from messy language; these rules then decide
what the Response Center sees. Order matters: the first matching rule wins and
its text is surfaced verbatim to operators as the reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from shared.enums import AssistanceType, Urgency
from shared.timeutils import utcnow

# Minutes allowed before an unacknowledged request breaches its SLA.
SLA_MINUTES = {
    Urgency.CRITICAL: 15,
    Urgency.URGENT: 45,
    Urgency.ATTENTION: 240,
    Urgency.INFORMATION: 1440,
}

_RESCUE_CAPABLE = {AssistanceType.RESCUE.value, AssistanceType.MEDICAL.value}
_LIFE_LINE = {AssistanceType.FOOD.value, AssistanceType.WATER.value, AssistanceType.SHELTER.value}


def classify_request(
    *,
    assistance_types: list[str] | None = None,
    medical_need: bool = False,
    immediate_danger: bool = False,
    people_count: int = 1,
    trapped: bool = False,
    description: str = "",
    incident_type: str | None = None,
    location_known: bool = True,
    minors_involved: bool = False,
    elderly_or_disabled_involved: bool = False,
) -> tuple[Urgency, list[str]]:
    types = {t for t in (assistance_types or []) if t}
    reasons: list[str] = []

    rescue_need = bool(types & _RESCUE_CAPABLE) or medical_need
    text = (description or "").lower()
    text_signals = _text_signals(text)

    if immediate_danger and rescue_need:
        reasons.append("Immediate danger reported together with a life-safety need")
        return Urgency.CRITICAL, _finalize(reasons, location_known)
    if trapped and rescue_need:
        reasons.append("Callers report being trapped and unable to self-evacuate")
        return Urgency.CRITICAL, _finalize(reasons, location_known)
    if medical_need and people_count >= 1 and text_signals & {"bleeding", "unconscious", "not breathing", "dying", "severe injury"}:
        reasons.append("Medical emergency with explicit severe-injury indicators")
        return Urgency.CRITICAL, _finalize(reasons, location_known)
    if medical_need:
        reasons.append("Medical assistance required")
        if minors_involved or elderly_or_disabled_involved:
            reasons.append("Vulnerable persons involved")
            return Urgency.CRITICAL, _finalize(reasons, location_known)
        if "medical" in types and immediate_danger:
            return Urgency.CRITICAL, _finalize(reasons, location_known)
        return Urgency.URGENT, _finalize(reasons, location_known)
    if AssistanceType.RESCUE.value in types:
        reasons.append("Rescue assistance requested")
        return (Urgency.CRITICAL if immediate_danger else Urgency.URGENT), _finalize(
            reasons, location_known
        )
    if types & _LIFE_LINE:
        reasons.append("Essential survival need requested (food / water / shelter)")
        return Urgency.URGENT if immediate_danger else Urgency.ATTENTION, _finalize(
            reasons, location_known
        )
    if AssistanceType.TRANSPORT.value in types:
        reasons.append("Transport assistance requested")
        return Urgency.ATTENTION, _finalize(reasons, location_known)
    if incident_type == "road_blockage":
        reasons.append("Road blockage affecting movement")
        return Urgency.ATTENTION, _finalize(reasons, location_known)
    reasons.append("Information or non-life-safety request")
    return Urgency.INFORMATION, _finalize(reasons, location_known)


def _finalize(reasons: list[str], location_known: bool) -> list[str]:
    if not location_known:
        reasons.append("Location not established - responders cannot be dispatched yet")
    return reasons


def _text_signals(text: str) -> set[str]:
    vocabulary = {
        "bleeding",
        "unconscious",
        "not breathing",
        "dying",
        "severe injury",
        "trapped",
        "collapsed",
        "rising water",
        "fire",
        "injured",
    }
    return {token for token in vocabulary if token in text}


def classify_report(
    *,
    incident_type: str | None,
    message: str = "",
    medical_need: bool = False,
    injuries: int = 0,
    people_count: int = 1,
    corroborating_reports: int = 0,
    official_backing: bool = False,
) -> Urgency:
    text = message.lower()
    if medical_need or injuries > 0 or any(k in text for k in ("trapped", "collapsed", "buried")):
        return Urgency.CRITICAL
    if incident_type in {"earthquake", "flood", "landslide"} and corroborating_reports >= 3:
        return Urgency.URGENT
    if incident_type in {"fire", "road_blockage", "lightning"}:
        return Urgency.URGENT if not official_backing else Urgency.ATTENTION
    if people_count > 10:
        return Urgency.URGENT
    if incident_type in {"flood", "landslide", "earthquake", "storm", "heavy_rainfall"}:
        return Urgency.ATTENTION
    return Urgency.INFORMATION


def escalate_from_volume(base: Urgency, report_count: int, open_requests: int) -> Urgency:
    """Deterministic promotion used when an incident suddenly gains attention."""
    order = [Urgency.INFORMATION, Urgency.ATTENTION, Urgency.URGENT, Urgency.CRITICAL]
    idx = order.index(base)
    if open_requests >= 5:
        idx += 2
    elif open_requests >= 1:
        idx += 1
    if report_count >= 15:
        idx += 1
    elif report_count >= 6:
        idx += 1
    return order[min(idx, len(order) - 1)]


def sla_deadline(urgency: Urgency, created_at: datetime | None = None) -> datetime:
    start = created_at or utcnow()
    return start + timedelta(minutes=SLA_MINUTES.get(urgency, 1440))


def sla_state(urgency: Urgency, created_at: datetime | None, now: datetime | None = None) -> dict[str, Any]:
    deadline = sla_deadline(urgency, created_at)
    remaining = (deadline - (now or utcnow())).total_seconds() / 60.0
    return {
        "sla_minutes": SLA_MINUTES.get(urgency, 1440),
        "due_at": deadline,
        "minutes_remaining": round(remaining, 1),
        "breached": remaining < 0,
    }
