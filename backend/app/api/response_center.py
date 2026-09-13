"""Response Center routes - the command centre's whole API surface.

Every write here is an *operator action*: it needs a permission, it is audited, and
it can only do what the lifecycle allows. None of them can change what an official
source said.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.deps import get_db, granted_permissions, require_permission
from backend.app.models.core import (
    AssistanceRequest,
    CommunityReport,
    Incident,
    Observation,
    Resource,
    User,
)
from backend.app.schemas import (
    AcknowledgeIn,
    AssignIn,
    EscalateIn,
    IncidentStatusIn,
    LinkIn,
    MergeIn,
    NoteIn,
    ReasonIn,
    ResourceAvailabilityIn,
    ResourceCreateIn,
    ResourceSeedIn,
    ReviewIn,
    SplitIn,
    StatusIn,
    VerifyIn,
    VictimMessageIn,
)
from backend.app.services import assistance, audit
from backend.app.services import community as community_service
from backend.app.services import resources as resource_service
from backend.app.services import response_center as rc_service

router = APIRouter(prefix="/rc", tags=["response-center"])


def _perms(user: User) -> set[str]:
    """What this viewer may press, as plain data for the service layer."""
    return granted_permissions(user)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/queue")
def queue(
    include_information: bool = True,
    limit_per_bucket: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(require_permission("assistance:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return rc_service.action_queue(db, limit_per_bucket=limit_per_bucket, include_information=include_information)


@router.get("/dashboard")
def dashboard(
    _user: User = Depends(require_permission("incidents:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return rc_service.dashboard(db)


@router.get("/activity")
def activity(
    limit: int = Query(default=40, ge=1, le=200),
    _user: User = Depends(require_permission("incidents:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": rc_service.activity_feed(db, limit=limit)}


@router.get("/audit")
def audit_log(
    entity_type: str | None = Query(default=None, max_length=40),
    entity_id: str | None = Query(default=None, max_length=80),
    actor_kind: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=500),
    _user: User = Depends(require_permission("audit:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The browsable audit log. Operators are accountable through this, so it has to
    be readable as a list and not only one entity at a time."""
    rows = audit.recent(
        db, limit=limit, entity_type=entity_type, entity_id=entity_id, actor_kind=actor_kind
    )
    return {"count": len(rows), "items": [audit.to_dict(e) for e in rows]}


@router.get("/audit/{entity_type}/{entity_id}")
def entity_audit(
    entity_type: str,
    entity_id: str,
    _user: User = Depends(require_permission("incidents:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    events = audit.for_entity(db, entity_type, entity_id)
    return {"entity_type": entity_type, "entity_id": entity_id, "items": [audit.to_dict(e) for e in events]}


@router.get("/requests")
def list_requests(
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    urgency: str | None = None,
    district: str | None = None,
    unassigned_only: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    _user: User = Depends(require_permission("assistance:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = rc_service.list_requests(
        db,
        status=status_filter,
        urgency=urgency,
        district=district,
        unassigned_only=unassigned_only,
        limit=limit,
    )
    return {
        "count": len(rows),
        "items": [assistance.to_dict(db, row) for row in rows],
    }


@router.get("/requests/{request_id}")
def request_detail(
    request_id: str,
    _user: User = Depends(require_permission("assistance:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    return {
        "request": assistance.to_dict(db, request),
        "timeline": assistance.timeline(db, request),
        "victim_timeline": assistance.timeline(db, request, victim_view=True),
        "sla": assistance.sla_info(request),
        "matched_resources": assistance.match_resources(db, request),
        "audit": [audit.to_dict(event) for event in audit.for_entity(db, audit.ENTITY_REQUEST, request.id)],
        "available_actions": _request_actions(request),
    }


def _request_actions(request: AssistanceRequest) -> list[dict[str, str]]:
    current = request.status
    legal = {
        "received": ["acknowledge", "status:reviewing", "cancel"],
        "reviewing": ["assign", "status:response_team_notified", "escalate", "message", "cancel"],
        "response_team_notified": ["assign", "status:assigned", "status:in_progress", "escalate", "message", "cancel"],
        "assigned": ["status:in_progress", "escalate", "message", "cancel"],
        "in_progress": ["status:resolved", "escalate", "message", "cancel"],
        "resolved": ["message"],
        "cancelled": ["message"],
    }
    return [
        {"action": item.split(":")[0], "target": item.split(":")[1] if ":" in item else None}
        for item in legal.get(current, [])
    ]


def _load_request(db: Session, request_id: str) -> AssistanceRequest:
    """Accept either the internal id or the human ref code an operator sees on screen
    and would otherwise paste straight back into the URL."""
    request = db.get(AssistanceRequest, request_id) or assistance.get_by_ref(db, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request")
    return request


@router.get("/reports")
def list_reports(
    district: str | None = None,
    incident_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    include_duplicates: bool = False,
    _user: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = community_service.recent_reports(
        db,
        district=district,
        incident_id=incident_id,
        include_duplicates=include_duplicates,
        limit=limit,
    )
    return {"count": len(rows), "items": [community_service.report_to_dict(db, row) for row in rows]}


@router.get("/reports/{report_id}")
def report_detail(
    report_id: str,
    _user: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One report, for the console link the platform sends operators.

    `community.py` writes `/response-center/reports/{id}` into a notification's `link`, so the
    console needs somewhere to land that is not a list search. The projection is deliberately the
    same one the list uses: there is no "more" to show on a single report, and inventing a second
    shape would let the two disagree about what a report is.
    """
    report = db.get(CommunityReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such report")
    return {"report": community_service.report_to_dict(db, report)}


@router.post("/reports/{report_id}/verify")
def verify_report(
    body: VerifyIn,
    report_id: str,
    operator: User = Depends(require_permission("reports:verify")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    report = db.get(CommunityReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such report")
    report = community_service.verify_report(db, report, operator, body.state, reason=body.reason)
    db.commit()
    return {"report": community_service.report_to_dict(db, report)}


@router.get("/incidents/{incident_id}")
def incident_detail(
    incident_id: str,
    user: User = Depends(require_permission("incidents:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return rc_service.incident_detail(db, _load_incident(db, incident_id), _perms(user))


def _load_incident(db: Session, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such incident")
    return incident


# --------------------------------------------------------------------------- #
# Operator actions on requests
# --------------------------------------------------------------------------- #
@router.post("/requests/{request_id}/acknowledge")
def acknowledge(
    body: AcknowledgeIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:acknowledge")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    assistance.acknowledge(db, request, operator)
    if body.note.strip():
        assistance.add_operator_note(db, request, operator, body.note)
    return {"request": assistance.to_dict(db, request), "timeline": assistance.timeline(db, request, victim_view=True)}


@router.post("/requests/{request_id}/assign")
def assign(
    body: AssignIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:assign")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    assistance.assign(
        db,
        request,
        operator,
        team=body.team,
        assigned_to=body.assigned_to,
        note=body.note,
        share_note_with_requester=body.share_note_with_requester,
    )
    return {
        "request": assistance.to_dict(db, request),
        "victim_timeline": assistance.timeline(db, request, victim_view=True),
    }


@router.post("/requests/{request_id}/status")
def change_status(
    body: StatusIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:status")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    try:
        assistance.change_status(db, request, operator, body.status, note=body.note)
    except assistance.StatusTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {
        "request": assistance.to_dict(db, request),
        "timeline": assistance.timeline(db, request, victim_view=True),
    }


@router.post("/requests/{request_id}/escalate")
def escalate(
    body: EscalateIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:status")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    assistance.escalate(db, request, operator, body.reason)
    return {"request": assistance.to_dict(db, request), "urgency_reasons": request.urgency_reasons}


@router.post("/requests/{request_id}/note")
def add_note(
    body: NoteIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _load_request(db, request_id)
    assistance.add_operator_note(db, request, operator, body.note, visible=body.visible_to_requester)
    return {"request": assistance.to_dict(db, request)}


@router.post("/requests/{request_id}/message")
def message_requester(
    body: VictimMessageIn,
    request_id: str,
    operator: User = Depends(require_permission("assistance:message_victim")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The closing half of the two-way loop: a reply the person actually sees."""
    request = _load_request(db, request_id)
    assistance.send_victim_update(db, request, operator, body.message)
    return {
        "request": assistance.to_dict(db, request),
        "victim_timeline": assistance.timeline(db, request, victim_view=True),
    }


# --------------------------------------------------------------------------- #
# Operator actions on incidents
# --------------------------------------------------------------------------- #
@router.post("/incidents/{incident_id}/status")
def set_incident_status(
    body: IncidentStatusIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    legal = {item["target"] for item in rc_service.available_actions(incident) if item["action"] == "set_status"}
    if body.status not in legal:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{incident.status}' cannot move to '{body.status}'. Legal next: {', '.join(sorted(legal)) or 'none'}",
        )
    rc_service.set_status(db, incident, operator, body.status, reason=body.reason)
    return {"incident": rc_service.incident_summary(db, incident)}


@router.post("/incidents/{incident_id}/verify")
def verify_incident(
    body: VerifyIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    try:
        rc_service.verify_as_operator(db, incident, operator, body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return rc_service.incident_detail(db, incident, _perms(operator))


@router.post("/incidents/{incident_id}/request-verification")
def request_verification(
    body: VerifyIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    rc_service.request_more_verification(db, incident, operator, body.reason)
    return {"incident": rc_service.incident_summary(db, incident)}


@router.post("/incidents/{incident_id}/review")
def set_review(
    body: ReviewIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    incident.needs_review = body.needs_review
    incident.review_reason = body.reason[:300] if body.needs_review else None
    rc_service.add_note(
        db, incident, operator, f"Review flag {'raised' if body.needs_review else 'cleared'}: {body.reason[:200]}"
    )
    db.commit()
    return {"incident": rc_service.incident_summary(db, incident)}


@router.post("/incidents/{incident_id}/note")
def incident_note(
    body: NoteIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    rc_service.add_note(db, incident, operator, body.note)
    return {"incident": rc_service.incident_summary(db, incident)}


@router.post("/incidents/{incident_id}/link/report")
def link_report(
    body: LinkIn,
    incident_id: str,
    operator: User = Depends(require_permission("reports:link")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    report = db.get(CommunityReport, body.report_id or "")
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such report")
    rc_service.link_report(db, incident, report, operator)
    return rc_service.incident_detail(db, incident, _perms(operator))


@router.post("/incidents/{incident_id}/link/observation")
def link_observation(
    body: LinkIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    observation = db.get(Observation, body.observation_id or "")
    if observation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such observation")
    rc_service.link_observation(db, incident, observation, operator)
    return rc_service.incident_detail(db, incident, _perms(operator))


@router.post("/incidents/{incident_id}/merge")
def merge_incidents(
    body: MergeIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:merge")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load_incident(db, incident_id)
    merged = rc_service.merge(db, incident, [body.duplicate_id], operator, body.reason)
    return rc_service.incident_detail(db, merged, _perms(operator))


@router.post("/incidents/{incident_id}/split")
def split_incident(
    body: SplitIn,
    incident_id: str,
    operator: User = Depends(require_permission("incidents:split")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Break a wrong grouping apart. The original incident keeps its official
    records; the selected reports move into a new one that is explicitly marked as
    operator-created rather than presented as newly discovered fact."""
    incident = _load_incident(db, incident_id)
    try:
        created = rc_service.split(db, incident, body.report_ids, operator, body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "original": rc_service.incident_summary(db, incident),
        "created": rc_service.incident_summary(db, created),
    }


# --------------------------------------------------------------------------- #
# Resources - facilities, teams, capacity
# --------------------------------------------------------------------------- #
@router.get("/resources")
def list_resources(
    resource_type: str | None = Query(default=None, max_length=32),
    district: str | None = None,
    availability: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=300, ge=1, le=1000),
    _user: User = Depends(require_permission("resources:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = resource_service.list_resources(
        db,
        resource_type=resource_type,
        district=district,
        availability=availability,
        include_inactive=include_inactive,
        limit=limit,
    )
    counts = resource_service.counts(db)
    return {
        "count": len(rows),
        "items": [resource_service.to_dict(row) for row in rows],
        # The counts are catalogue-wide, not page-wide: an operator deciding whether to
        # trust this list needs to know how thin the whole thing is.
        "catalogue": counts,
        "seed": resource_service.seed_status(),
        "empty_reason": (
            "No facility catalogue has been loaded. Nothing here is invented - seed from "
            "OpenStreetMap or add verified facilities yourself."
            if counts["empty"]
            else None
        ),
    }


@router.post("/resources", status_code=status.HTTP_201_CREATED)
def create_resource(
    body: ResourceCreateIn,
    operator: User = Depends(require_permission("resources:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A facility an operator knows about, recorded as their statement."""
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A facility needs both a latitude and a longitude, or neither",
        )
    resource = resource_service.create(
        db,
        actor=operator,
        resource_type=body.resource_type,
        name=body.name,
        description=body.description,
        latitude=body.latitude,
        longitude=body.longitude,
        address=body.address,
        district=body.district,
        contact=body.contact,
        capacity=body.capacity,
        availability=body.availability,
    )
    return {"resource": resource_service.to_dict(resource)}


@router.post("/resources/{resource_id}/availability")
def set_resource_availability(
    resource_id: str,
    body: ResourceAvailabilityIn,
    operator: User = Depends(require_permission("resources:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such resource")
    resource = resource_service.set_availability(
        db,
        resource,
        operator,
        body.availability,
        capacity_left=body.capacity,
        contact_verified=body.contact_verified,
        reason=body.reason,
    )
    return {"resource": resource_service.to_dict(resource)}


@router.post("/resources/{resource_id}/deactivate")
def retire_resource(
    resource_id: str,
    body: ReasonIn,
    operator: User = Depends(require_permission("resources:update")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Take a facility off the map. Retired, never deleted: if a wrong entry sent someone
    to a closed gate, the log has to show who listed it and when it was withdrawn."""
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such resource")
    resource = resource_service.deactivate(db, resource, operator, reason=body.reason)
    return {"resource": resource_service.to_dict(resource)}


@router.post("/resources/seed")
def seed_resources(
    body: ResourceSeedIn,
    operator: User = Depends(require_permission("resources:update")),
) -> dict[str, Any]:
    """Start pulling the facility catalogue from OpenStreetMap.

    Returns immediately: a nationwide Overpass query takes minutes, and an operator who
    asked for it should see it running rather than a spinner on a request that timed out.
    """
    outcome = resource_service.start_seed(
        actor_id=operator.id, types=body.types or None, timeout=90.0
    )
    return {"seed": outcome, "status": resource_service.seed_status()}


@router.get("/resources/seed")
def seed_resources_status(
    _user: User = Depends(require_permission("resources:read")),
) -> dict[str, Any]:
    return resource_service.seed_status()
