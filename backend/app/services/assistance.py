"""Assistance requests - the case behind "I NEED HELP".

This module owns the victim-visible lifecycle. Status moves are validated against
`ALLOWED_STATUS_TRANSITIONS` server-side, every move writes a case update (what the
victim sees), a notification (the two-way loop), and an audit row (who did it).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.geo.boundaries import boundary_index, normalize_district
from backend.app.models.core import (
    AssistanceRequest,
    AssistanceUpdate,
    CommunityReport,
    Incident,
    Resource,
    User,
    new_id,
)
from backend.app.scoring import urgency as urgency_mod
from backend.app.services import audit, communication, notifications
from backend.app.services import incidents as incident_service
from shared.enums import (
    ALLOWED_STATUS_TRANSITIONS,
    AssistanceStatus,
    AssistanceType,
    AuditAction,
    Urgency,
    status_progress,
)
from shared.geo import haversine_km
from shared.nepal_places import resolve_place
from shared.timeutils import humanize_age, iso, utcnow


class StatusTransitionError(Exception):
    """Raised when a requested status move is not allowed in the lifecycle.

    The message is shown to an operator verbatim, so it names the legal moves
    rather than just saying 'not allowed'.
    """

    def __init__(self, current: str, target: str, allowed: set[str] | None = None):
        options = sorted(allowed or set())
        if current == target:
            message = f"This case is already '{current}' - there is nothing to change"
        elif options:
            message = (
                f"'{current}' cannot move to '{target}'. Next legal steps: {', '.join(options)}"
            )
        else:
            message = f"'{current}' cannot move to '{target}'"
        super().__init__(message)
        self.current = current
        self.target = target
        self.allowed = options


# --------------------------------------------------------------------------- #
# Location resolution (shared with report intake)
# --------------------------------------------------------------------------- #
def resolve_location(
    db: Session,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    location_text: str | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """Coordinates the sender shared beat text, which beat the home district.

    The confidence is carried through to the UI because "we know the village" and
    "we know the district" lead to different dispatch decisions.
    """
    out: dict[str, Any] = {
        "latitude": None,
        "longitude": None,
        "district": None,
        "province": None,
        "location_text": location_text,
        "location_confidence": "unknown",
    }
    if latitude is not None and longitude is not None:
        out.update(latitude=float(latitude), longitude=float(longitude))
        resolved = boundary_index.resolve_point(latitude, longitude)
        out["district"] = resolved.district
        out["province"] = resolved.province
        out["location_confidence"] = "high" if resolved.precision == "district_polygon" else "medium"
        return out

    match = resolve_place(location_text)
    if match:
        out.update(
            latitude=match.lat,
            longitude=match.lng,
            district=normalize_district(match.district) or match.district,
            province=match.province,
            location_confidence="medium" if match.match_confidence == "high" else "low",
        )
        if not out["location_text"]:
            out["location_text"] = match.name
        return out

    if location_text:
        # A place we could not geocode is still worth keeping - an operator can read
        # "behind the old bus park" and act on it.
        out["location_confidence"] = "text_only"
        out["location_text"] = location_text
    if user and user.home_district:
        out["district"] = normalize_district(user.home_district)
        if out["location_confidence"] == "unknown":
            out["location_confidence"] = "inferred_home_district"
    return out


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #
def create(
    db: Session,
    *,
    user: User | None,
    description: str,
    request_type: str = AssistanceType.OTHER.value,
    assistance_types: list[str] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    location_text: str | None = None,
    people_count: int = 1,
    medical_need: bool = False,
    immediate_danger: bool = False,
    trapped: bool = False,
    minors_involved: bool = False,
    elderly_or_disabled_involved: bool = False,
    incident_id: str | None = None,
    report_id: str | None = None,
    language: str = "en",
    attachments: list[dict[str, Any]] | None = None,
    submitted_offline: bool = False,
    provenance: str = "community",
    demo_scenario_id: str | None = None,
    structured: dict[str, Any] | None = None,
) -> AssistanceRequest:
    location = resolve_location(
        db, latitude=latitude, longitude=longitude, location_text=location_text, user=user
    )
    types = [t for t in (assistance_types or []) if t in {e.value for e in AssistanceType}]
    if request_type in {e.value for e in AssistanceType} and request_type not in types:
        types.insert(0, request_type)
    if medical_need and AssistanceType.MEDICAL.value not in types:
        types.append(AssistanceType.MEDICAL.value)

    incident = db.get(Incident, incident_id) if incident_id else None
    if incident is None and report_id:
        report = db.get(CommunityReport, report_id)
        incident = db.get(Incident, report.incident_id) if report and report.incident_id else None

    urgency, reasons = urgency_mod.classify_request(
        assistance_types=types,
        medical_need=medical_need,
        immediate_danger=immediate_danger,
        people_count=people_count or 1,
        trapped=trapped,
        description=description,
        incident_type=incident.incident_type if incident else None,
        location_known=location["location_confidence"] in {"high", "medium"},
        minors_involved=minors_involved,
        elderly_or_disabled_involved=elderly_or_disabled_involved,
    )

    now = utcnow()
    request = AssistanceRequest(
        id=new_id("asr"),
        ref_code=incident_service.new_ref_code("REQ"),
        user_id=user.id if user else None,
        incident_id=incident.id if incident else None,
        report_id=report_id,
        request_type=request_type or AssistanceType.OTHER.value,
        assistance_types=types,
        description=description.strip()[:4000],
        raw_message=description.strip()[:4000],
        latitude=location["latitude"],
        longitude=location["longitude"],
        location_text=location["location_text"],
        location_confidence=location["location_confidence"],
        district=location["district"],
        province=location["province"],
        urgency=urgency.value,
        urgency_reasons=reasons,
        people_count=max(1, int(people_count or 1)),
        medical_need=medical_need,
        immediate_danger=immediate_danger,
        status=AssistanceStatus.RECEIVED.value,
        sla_due_at=urgency_mod.sla_deadline(urgency, now),
        attachments=attachments or [],
        structured={
            **(structured or {}),
            "trapped": trapped,
            "minors_involved": minors_involved,
            "elderly_or_disabled_involved": elderly_or_disabled_involved,
            "submitted_offline": submitted_offline,
        },
        language=language,
        provenance=provenance,
        demo_scenario_id=demo_scenario_id,
        created_at=now,
    )
    db.add(request)
    db.flush()

    matched = match_resources(db, request)
    request.matched_resource_ids = [r["id"] for r in matched]
    request.response_plan = build_response_plan(request, matched)

    add_update(
        db,
        request,
        actor_type="system",
        actor_id=None,
        actor_label="Sanket",
        kind="status",
        message=communication.receipt_message(
            ref_code=request.ref_code,
            status=request.status,
            urgency=request.urgency,
            language=language,
            location_known=request.location_confidence in {"high", "medium"},
        ),
        visible_to_victim=True,
        to_status=request.status,
    )
    _notify_response_center(db, request)
    audit.record(
        db,
        action="request_created",
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=user,
        actor_kind="victim" if user else "system",
        new={"urgency": request.urgency, "incident_id": request.incident_id, "types": types},
        reason="; ".join(reasons[:2]) or None,
    )
    if request.incident_id:
        _recompute_incident(db, request.incident_id)
    db.commit()
    db.refresh(request)
    return request


# A case is open until it is resolved or cancelled. The queue, the dashboard and the
# duplicate handling all ask this same question, so the answer lives here once.
OPEN_STATUSES = {
    AssistanceStatus.RECEIVED.value,
    AssistanceStatus.REVIEWING.value,
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value,
    AssistanceStatus.ASSIGNED.value,
    AssistanceStatus.IN_PROGRESS.value,
}


def is_open(request: AssistanceRequest) -> bool:
    return request.status in OPEN_STATUSES


def add_update(
    db: Session,
    request: AssistanceRequest,
    *,
    actor_type: str,
    kind: str,
    message: str,
    actor_id: str | None = None,
    actor_label: str = "Sanket",
    visible_to_victim: bool = True,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AssistanceUpdate:
    update = AssistanceUpdate(
        id=new_id("upd"),
        request_id=request.id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        kind=kind,
        message=message,
        visible_to_victim=visible_to_victim,
        from_status=from_status,
        to_status=to_status,
        created_at=utcnow(),
        metadata_=metadata or {},
    )
    db.add(update)
    db.flush()
    return update


# --------------------------------------------------------------------------- #
# Operator actions
# --------------------------------------------------------------------------- #
def acknowledge(db: Session, request: AssistanceRequest, operator: User) -> AssistanceRequest:
    request.acknowledged_at = utcnow()
    request.acknowledged_by = operator.id
    audit.record(
        db,
        action=AuditAction.ACKNOWLEDGE,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="operator",
        new={"acknowledged_at": iso(request.acknowledged_at)},
    )
    db.commit()
    if request.status == AssistanceStatus.RECEIVED.value:
        # Acknowledging is, for the victim, the first proof a human saw it.
        change_status(db, request, operator, AssistanceStatus.REVIEWING.value)
    return request


def assign(
    db: Session,
    request: AssistanceRequest,
    operator: User,
    *,
    team: str,
    assigned_to: str | None = None,
    note: str = "",
    share_note_with_requester: bool = False,
) -> AssistanceRequest:
    """Record who is going. The note stays internal unless the operator explicitly
    shares it - an internal dispatch remark is not automatically a promise to the
    person waiting."""
    previous = request.assigned_team
    request.assigned_team = team[:200]
    request.assigned_to = assigned_to
    audit.record(
        db,
        action=AuditAction.ASSIGN,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="operator",
        previous={"team": previous},
        new={"team": team, "assigned_to": assigned_to},
        reason=note or None,
    )
    add_update(
        db,
        request,
        actor_type="operator",
        actor_id=operator.id,
        actor_label=operator.display_name or operator.username,
        kind="assignment",
        message=_assignment_message(request, team, note if share_note_with_requester else ""),
    )
    db.commit()
    if status_progress(AssistanceStatus(request.status)) < status_progress(
        AssistanceStatus.RESPONSE_TEAM_NOTIFIED
    ):
        change_status(db, request, operator, AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value)
    return request


def _assignment_message(request: AssistanceRequest, team: str, note: str) -> str:
    """Victim-facing line for an assignment. The team name is kept exactly as the
    operator typed it (a proper noun is not translatable), the sentence around it is
    in the language the person wrote in. An operator note only appears when it was
    explicitly shared."""
    extra = f" {note.strip()}" if note.strip() else ""
    if request.language == "ne":
        return f"{team} टोलीलाई खबर गरिएको छ।{extra}"
    return f"Assigned to {team}.{extra}"


def change_status(
    db: Session,
    request: AssistanceRequest,
    operator: User,
    target: str,
    note: str = "",
) -> AssistanceRequest:
    current = AssistanceStatus(request.status)
    try:
        wanted = AssistanceStatus(target)
    except ValueError as exc:
        raise StatusTransitionError(request.status, target) from exc
    if wanted not in ALLOWED_STATUS_TRANSITIONS[current]:
        raise StatusTransitionError(
            current.value, target, {state.value for state in ALLOWED_STATUS_TRANSITIONS[current]}
        )

    request.status = wanted.value
    if wanted == AssistanceStatus.RESOLVED:
        request.resolved_at = utcnow()
    audit.record(
        db,
        action=AuditAction.STATUS_CHANGE,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="operator",
        previous={"status": current.value},
        new={"status": wanted.value},
        reason=note or None,
    )
    message = communication.status_change_message(
        ref_code=request.ref_code,
        from_status=current.value,
        to_status=wanted.value,
        language=request.language,
        operator_note=note,
    )
    add_update(
        db,
        request,
        actor_type="operator",
        actor_id=operator.id,
        actor_label=operator.display_name or operator.username,
        kind="status",
        message=message,
        visible_to_victim=True,
        from_status=current.value,
        to_status=wanted.value,
    )
    notifications.push(
        db,
        audience=notifications.AUDIENCE_COMMUNITY,
        user_id=request.user_id,
        title=f"Update on {request.ref_code}",
        body=message,
        kind="status",
        severity=request.urgency,
        link=f"/requests/{request.ref_code}",
        request_id=request.id,
        incident_id=request.incident_id,
        district=request.district,
    )
    if request.incident_id:
        _recompute_incident(db, request.incident_id)
    db.commit()
    return request


def escalate(
    db: Session, request: AssistanceRequest, operator: User, reason: str
) -> AssistanceRequest:
    previous = request.urgency
    order = [
        Urgency.INFORMATION.value,
        Urgency.ATTENTION.value,
        Urgency.URGENT.value,
        Urgency.CRITICAL.value,
    ]
    target = order[min(order.index(previous) + 1, len(order) - 1)] if previous in order else previous
    if reason.strip().lower().startswith("critical"):
        target = Urgency.CRITICAL.value
    request.urgency = target
    request.urgency_reasons = [*request.urgency_reasons, f"Manually escalated by operator: {reason[:200]}"]
    request.sla_due_at = urgency_mod.sla_deadline(Urgency(target), request.created_at)
    audit.record(
        db,
        action=AuditAction.ESCALATE,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="operator",
        previous={"urgency": previous},
        new={"urgency": target},
        reason=reason,
    )
    add_update(
        db,
        request,
        actor_type="operator",
        actor_id=operator.id,
        actor_label=operator.display_name or operator.username,
        kind="note",
        message="Priority raised by the response centre.",
        visible_to_victim=True,
    )
    _notify_response_center(db, request, escalated=True)
    db.commit()
    return request


def carry_repeat_plea(
    db: Session,
    request: AssistanceRequest,
    *,
    language: str = "en",
    report_id: str | None = None,
) -> AssistanceRequest:
    """The same person asked for help again while their case is still open.

    Raising a second ticket would only add noise to the queue, but ignoring the second
    plea would be worse than noise - it is the sound of someone still waiting. So the
    open case goes up a level, the repeat is written into the timeline the person can
    see, and the Response Center is alerted again.

    The SLA is deliberately *not* restarted: it still runs from the first ask, so a
    repeat on an overdue case shows as overdue instead of buying the queue more time.
    """
    previous = request.urgency
    order = [
        Urgency.INFORMATION.value,
        Urgency.ATTENTION.value,
        Urgency.URGENT.value,
        Urgency.CRITICAL.value,
    ]
    index = order.index(previous) if previous in order else 0
    request.urgency = order[min(index + 1, len(order) - 1)]
    request.urgency_reasons = [
        *request.urgency_reasons,
        "The person reported again - still waiting for help",
    ]
    add_update(
        db,
        request,
        actor_type="victim",
        actor_id=request.user_id,
        actor_label="Sanket",
        kind="repeat_request",
        message=(
            "आपले अझै सहयोग चाहिन्छ भन्ने कुरा दर्ता भयो। चलिरहेको अनुरोधको प्राथमिकता "
            "बढाइएको छ।"
            if language == "ne"
            else "We recorded that you still need help. The priority of your open "
            "request has been raised and the response centre has been alerted."
        ),
        visible_to_victim=True,
        metadata={"report_id": report_id, "carried_from_report": True},
    )
    audit.record(
        db,
        action=AuditAction.ESCALATE,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=None,
        actor_kind="system",
        previous={"urgency": previous},
        new={"urgency": request.urgency},
        reason="Reporter repeated the request on an open case",
    )
    _notify_response_center(db, request, escalated=True)
    db.flush()
    return request


def add_operator_note(
    db: Session, request: AssistanceRequest, operator: User, note: str, visible: bool = False
) -> AssistanceRequest:
    add_update(
        db,
        request,
        actor_type="operator",
        actor_id=operator.id,
        actor_label=operator.display_name or operator.username,
        kind="note",
        message=note,
        visible_to_victim=visible,
    )
    audit.record(
        db,
        action=AuditAction.NOTE_ADDED,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="operator",
        new={"note": note[:500], "visible_to_victim": visible},
    )
    if visible:
        notifications.push(
            db,
            audience=notifications.AUDIENCE_COMMUNITY,
            user_id=request.user_id,
            title=f"Message about {request.ref_code}",
            body=note,
            kind="message",
            severity=request.urgency,
            link=f"/requests/{request.ref_code}",
            request_id=request.id,
            district=request.district,
        )
    db.commit()
    return request


def send_victim_update(
    db: Session,
    request: AssistanceRequest,
    operator: User,
    message: str,
    *,
    via_agent: bool = False,
) -> AssistanceRequest:
    """The explicit 'reply to the person' action - the closing half of the loop.

    `via_agent` marks a message the intelligence layer drafted. The operator is still the
    sender and their name is still on it, but the label says how it arrived: a person in
    danger should not be told "Sunita says help is coming" when what happened is that
    Sunita's agent wrote a sentence and she pressed send.
    """
    add_update(
        db,
        request,
        actor_type="operator",
        actor_id=operator.id,
        actor_label=(operator.display_name or operator.username)
        + (" (drafted by Sanket agent)" if via_agent else ""),
        kind="message",
        message=message,
        visible_to_victim=True,
    )
    notifications.push(
        db,
        audience=notifications.AUDIENCE_COMMUNITY,
        user_id=request.user_id,
        title=f"Message about {request.ref_code}",
        body=message,
        kind="message",
        severity=request.urgency,
        link=f"/requests/{request.ref_code}",
        request_id=request.id,
        district=request.district,
    )
    audit.record(
        db,
        action=AuditAction.VICTIM_UPDATE_SENT,
        entity_type=audit.ENTITY_REQUEST,
        entity_id=request.id,
        actor=operator,
        actor_kind="agent" if via_agent else "operator",
        new={"message": message[:500], "drafted_by": "agent" if via_agent else "operator"},
    )
    db.commit()
    return request


def cancel_by_victim(db: Session, request: AssistanceRequest, user: User, reason: str = "") -> AssistanceRequest:
    current = AssistanceStatus(request.status)
    if AssistanceStatus.CANCELLED not in ALLOWED_STATUS_TRANSITIONS[current]:
        raise StatusTransitionError(request.status, AssistanceStatus.CANCELLED.value)
    return change_status(
        db, request, user, AssistanceStatus.CANCELLED.value, note=reason or "Cancelled by the requester"
    )


# --------------------------------------------------------------------------- #
# Matching and planning
# --------------------------------------------------------------------------- #
def match_resources(
    db: Session, request: AssistanceRequest, limit: int = 5
) -> list[dict[str, Any]]:
    """Nearest *known* resources of the right kind.

    Only rows that came from a real dataset are returned, and each carries its own
    verification timestamp. Nothing here is ever filled in with a plausible-looking
    hospital: an empty list is the honest answer when we have no data.
    """
    wanted = {
        AssistanceType.MEDICAL.value: {"hospital", "health_post", "ambulance"},
        AssistanceType.RESCUE.value: {"police", "army", "fire"},
        AssistanceType.SHELTER.value: {"shelter"},
        AssistanceType.FOOD.value: {"food_distribution", "shelter"},
        AssistanceType.WATER.value: {"water_supply"},
        AssistanceType.TRANSPORT.value: {"ambulance", "helipad"},
    }
    kinds: set[str] = set()
    for key in [request.request_type, *request.assistance_types]:
        kinds |= wanted.get(key, set())
    if not kinds:
        kinds = {"hospital", "police", "shelter"}

    stmt = select(Resource).where(Resource.active.is_(True), Resource.resource_type.in_(kinds))
    rows = list(db.execute(stmt).scalars())
    if not rows:
        return []
    scored: list[tuple[float, Resource]] = []
    for resource in rows:
        if request.latitude is None or resource.latitude is None:
            # Without a coordinate for either side we cannot claim proximity.
            distance = float("inf")
        else:
            distance = haversine_km(
                (request.latitude, request.longitude), (resource.latitude, resource.longitude)
            ) or float("inf")
        if distance == float("inf") and request.district and resource.district:
            distance = 0.0 if request.district == resource.district else float("inf")
        if distance != float("inf"):
            scored.append((distance, resource))
    scored.sort(key=lambda item: item[0])
    out: list[dict[str, Any]] = []
    for distance, resource in scored[:limit]:
        out.append(
            {
                "id": resource.id,
                "name": resource.name,
                "resource_type": resource.resource_type,
                "district": resource.district,
                "contact": resource.contact,
                "contact_verified": resource.contact_verified,
                "availability": resource.availability,
                "distance_km": None if distance == float("inf") else round(distance, 1),
                "source": resource.source,
                "verified_at": iso(resource.availability_verified_at),
                "provenance": resource.provenance,
            }
        )
    return out


def build_response_plan(
    request: AssistanceRequest, matched: list[dict[str, Any]]
) -> dict[str, Any]:
    """A structured, deterministic plan object - not generated prose.

    Steps describe what Sanket can actually do with the data it holds, and the
    `unknowns` list names what we cannot answer yet, so the gap is visible.
    """
    steps: list[dict[str, str]] = [
        {
            "step": "confirm_location",
            "text": (
                "Location established"
                if request.location_confidence in {"high", "medium"}
                else "Get a reachable named place from the requester before dispatch"
            ),
        },
        {
            "step": "triage",
            "text": f"Classified {request.urgency.upper()} by deterministic rules; operator to acknowledge",
        },
    ]
    if matched:
        nearest = matched[0]
        text = f"Nearest matching resource: {nearest['name']}"
        if nearest.get("distance_km") is not None:
            text += f" (~{nearest['distance_km']} km away)"
        text += f"; availability {nearest['availability']}"
        steps.append({"step": "route_to_resource", "text": text})
    else:
        steps.append(
            {
                "step": "route_to_resource",
                "text": "No verified facility in Sanket's resource dataset for this need - "
                        "escalate to official emergency contacts",
            }
        )
    if request.urgency == Urgency.CRITICAL.value:
        steps.append(
            {"step": "official_channels", "text": "Critical: also notify official emergency contacts"}
        )
    unknowns: list[str] = []
    if request.location_confidence not in {"high", "medium"}:
        unknowns.append("Exact location of the requester")
    if not request.incident_id:
        unknowns.append("Which incident this belongs to (no confident match yet)")
    if not matched:
        unknowns.append("Nearby verified facilities")
    return {
        "generated_by": "deterministic",
        "urgency": request.urgency,
        "urgency_reasons": request.urgency_reasons,
        "steps": steps,
        "unknowns": unknowns,
        "sla_minutes": urgency_mod.SLA_MINUTES.get(Urgency(request.urgency), 1440),
        "victim_visibility": "status and messages only; internal routing detail stays internal",
    }


def refresh_plan(db: Session, request: AssistanceRequest) -> AssistanceRequest:
    matched = match_resources(db, request)
    request.matched_resource_ids = [r["id"] for r in matched]
    request.response_plan = build_response_plan(request, matched)
    db.flush()
    return request


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def timeline(db: Session, request: AssistanceRequest, victim_view: bool = False) -> list[dict[str, Any]]:
    stmt = (
        select(AssistanceUpdate)
        .where(AssistanceUpdate.request_id == request.id)
        .order_by(AssistanceUpdate.created_at.asc())
    )
    rows = list(db.execute(stmt).scalars())
    if victim_view:
        rows = [u for u in rows if u.visible_to_victim]
    return [
        {
            "id": u.id,
            "actor_type": u.actor_type,
            "actor": u.actor_label,
            "kind": u.kind,
            "message": u.message,
            "from_status": u.from_status,
            "to_status": u.to_status,
            "at": iso(u.created_at),
        }
        for u in rows
    ]


def get_by_ref(db: Session, ref_code: str) -> AssistanceRequest | None:
    return db.execute(
        select(AssistanceRequest).where(AssistanceRequest.ref_code == ref_code)
    ).scalar_one_or_none()


def sla_info(request: AssistanceRequest) -> dict[str, Any]:
    state = urgency_mod.sla_state(Urgency(request.urgency), request.created_at)
    acknowledged = request.acknowledged_at is not None
    return {
        "sla_minutes": state["sla_minutes"],
        "due_at": iso(state["due_at"]),
        "minutes_remaining": None if acknowledged else state["minutes_remaining"],
        "breached": bool(state["breached"]) and not acknowledged,
        "acknowledged": acknowledged,
    }


def to_dict(db: Session, request: AssistanceRequest, *, victim_view: bool = False) -> dict[str, Any]:
    """Operator view by default. The victim view hides internal detail
    (who is assigned, notes not meant for them) but never hides the status."""
    incident = db.get(Incident, request.incident_id) if request.incident_id else None
    data: dict[str, Any] = {
        "id": request.id,
        "ref_code": request.ref_code,
        "status": request.status,
        "status_label": communication.status_label(request.status, request.language),
        "urgency": request.urgency,
        "urgency_reasons": request.urgency_reasons,
        "request_type": request.request_type,
        "assistance_types": request.assistance_types,
        "description": request.description,
        "people_count": request.people_count,
        "medical_need": request.medical_need,
        "immediate_danger": request.immediate_danger,
        "district": request.district,
        "province": request.province,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "location_text": request.location_text,
        "location_confidence": request.location_confidence,
        "language": request.language,
        "incident": (
            {"id": incident.id, "ref_code": incident.ref_code, "title": incident.title,
             "incident_type": incident.incident_type}
            if incident
            else None
        ),
        "created_at": iso(request.created_at),
        "age": _age(request.created_at),
        "acknowledged_at": iso(request.acknowledged_at),
        "resolved_at": iso(request.resolved_at),
        "provenance": request.provenance,
        "demo": request.provenance == "demo",
        "timeline": timeline(db, request, victim_view=victim_view),
    }
    if victim_view:
        data["next_step"] = communication.next_step(request.status, request.language)
        data["sla"] = {"acknowledged": request.acknowledged_at is not None}
        return data
    data.update(
        {
            "assigned_team": request.assigned_team,
            "assigned_to": request.assigned_to,
            "sla": sla_info(request),
            "matched_resources": match_resources(db, request),
            "response_plan": request.response_plan,
            "report_id": request.report_id,
            "structured": request.structured,
            "submitted_offline": bool((request.structured or {}).get("submitted_offline")),
        }
    )
    return data


def _age(moment) -> str:
    return humanize_age(moment)


def _notify_response_center(db: Session, request: AssistanceRequest, escalated: bool = False) -> None:
    critical = request.urgency == Urgency.CRITICAL.value
    notifications.push(
        db,
        audience=notifications.AUDIENCE_RESPONSE_CENTER,
        title=(
            f"{'ESCALATED: ' if escalated else ''}{'CRITICAL ' if critical else ''}request "
            f"{request.ref_code}"
            + (f" in {request.district}" if request.district else "")
        ),
        body=_first_line(request.description),
        kind="critical_request" if critical else "request",
        severity=request.urgency,
        link=f"/response-center/requests/{request.ref_code}",
        request_id=request.id,
        incident_id=request.incident_id,
        district=request.district,
    )
    if request.user_id:
        notifications.push(
            db,
            audience=notifications.AUDIENCE_COMMUNITY,
            user_id=request.user_id,
            title=f"Request {request.ref_code} received",
            body=communication.receipt_message(
                ref_code=request.ref_code,
                status=request.status,
                urgency=request.urgency,
                language=request.language,
                location_known=request.location_confidence in {"high", "medium"},
            ),
            kind="status",
            severity=request.urgency,
            link=f"/requests/{request.ref_code}",
            request_id=request.id,
            district=request.district,
        )


def _first_line(text: str, limit: int = 180) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit] + ("…" if len(clean) > limit else "")


def _recompute_incident(db: Session, incident_id: str) -> None:
    incident = db.get(Incident, incident_id)
    if incident is not None:
        incident_service.recompute(db, incident)
