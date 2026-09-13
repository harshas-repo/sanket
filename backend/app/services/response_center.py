"""Response Center service: action queue, dashboard, incident detail, operations.

The action queue answers one question - "what needs a human decision right now" -
and every entry carries the reason it is there. Merging, verifying and status
changes are the only ways state moves, each audited, and none of them can alter
what an official source said.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.core import (
    AssistanceRequest,
    AuditEvent,
    CommunityReport,
    Incident,
    IncidentObservation,
    Observation,
    RiskSignal,
    User,
    new_id,
)
from backend.app.scoring import evidence as evidence_mod
from backend.app.scoring import freshness as freshness_mod
from backend.app.services import alerts as alert_service
from backend.app.services import assistance, audit
from backend.app.services import community as community_service
from backend.app.services import incidents as incident_service
from backend.app.services import signals as signal_service
from shared.enums import (
    AuditAction,
    EvidenceState,
    IncidentStatus,
    Urgency,
)
from shared.geo import haversine_km
from shared.timeutils import humanize_age, iso, utcnow

# The lifecycle is owned by the assistance service; the queue only reads it.
OPEN_STATUSES = assistance.OPEN_STATUSES
QUEUE_ORDER = [
    Urgency.CRITICAL.value,
    Urgency.URGENT.value,
    Urgency.ATTENTION.value,
    Urgency.INFORMATION.value,
]


# --------------------------------------------------------------------------- #
# Action queue
# --------------------------------------------------------------------------- #
def action_queue(db: Session, *, limit_per_bucket: int = 25, include_information: bool = True) -> dict[str, Any]:
    """Everything a duty operator can act on, bucketed by urgency.

    Sources of queue entries: open assistance requests, incidents flagged for
    review, and unverified reports that contradict or outrank the current picture.
    """
    entries: list[dict[str, Any]] = []

    requests = list(
        db.execute(
            select(AssistanceRequest)
            .where(AssistanceRequest.status.in_(OPEN_STATUSES))
            .order_by(AssistanceRequest.created_at.desc())
            .limit(400)
        ).scalars()
    )
    for request in requests:
        sla = assistance.sla_info(request)
        entries.append(
            {
                "kind": "assistance_request",
                "id": request.id,
                "ref_code": request.ref_code,
                "urgency": request.urgency,
                "title": _first_line(request.description) or request.request_type,
                "why": request.urgency_reasons[:2] or ["Awaiting response"],
                "district": request.district,
                "status": request.status,
                "at": iso(request.created_at),
                "age": humanize_age(request.created_at),
                "acknowledged": request.acknowledged_at is not None,
                "sla": sla,
                "incident_id": request.incident_id,
                "medical_need": request.medical_need,
                "immediate_danger": request.immediate_danger,
                "people_count": request.people_count,
                "demo": request.provenance == "demo",
            }
        )

    review_incidents = list(
        db.execute(
            select(Incident)
            .where(
                Incident.archived.is_(False),
                Incident.duplicate_of.is_(None),
                Incident.needs_review.is_(True),
            )
            .order_by(Incident.impact_score.desc())
            .limit(120)
        ).scalars()
    )
    for incident in review_incidents:
        entries.append(
            {
                "kind": "incident_review",
                "id": incident.id,
                "ref_code": incident.ref_code,
                "urgency": incident.urgency,
                "title": incident.title,
                "why": [incident.review_reason or "Needs review", *incident.prioritization_reasons[:1]],
                "district": incident.district,
                "status": incident.status,
                "at": iso(incident.last_updated_at),
                "age": humanize_age(incident.last_updated_at),
                "evidence_state": incident.evidence_state,
                "impact_score": incident.impact_score,
                "demo": incident.provenance == "demo",
            }
        )

    pending_reports = list(
        db.execute(
            select(CommunityReport)
            .where(
                CommunityReport.verification_status == "pending",
                CommunityReport.duplicate_status != "duplicate",
                CommunityReport.urgency.in_([Urgency.CRITICAL.value, Urgency.URGENT.value]),
                CommunityReport.incident_id.is_(None),
            )
            .order_by(CommunityReport.created_at.desc())
            .limit(120)
        ).scalars()
    )
    for report in pending_reports:
        entries.append(
            {
                "kind": "unlinked_report",
                "id": report.id,
                "ref_code": None,
                "urgency": report.urgency,
                "title": _first_line(report.message),
                "why": [
                    "No incident matched this report - it may describe something new",
                    f"location confidence {report.location_confidence}",
                ],
                "district": report.district,
                "status": report.verification_status,
                "at": iso(report.created_at),
                "age": humanize_age(report.created_at),
                "demo": report.provenance == "demo",
            }
        )

    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in QUEUE_ORDER}
    for entry in entries:
        bucket = entry["urgency"] if entry["urgency"] in buckets else Urgency.INFORMATION.value
        buckets[bucket].append(entry)
    counts = {key: len(items) for key, items in buckets.items()}
    for key in buckets:
        buckets[key].sort(key=lambda item: item["at"] or "", reverse=True)
        buckets[key] = buckets[key][:limit_per_bucket]
    if not include_information:
        buckets.pop(Urgency.INFORMATION.value, None)
    return {
        "generated_at": iso(utcnow()),
        "buckets": buckets,
        "counts": counts,
        "total_open_requests": sum(
            db.execute(
                select(func.count(AssistanceRequest.id)).where(
                    AssistanceRequest.status == status
                )
            ).scalar_one()
            for status in OPEN_STATUSES
        ),
        "sla_breaches": sum(1 for e in entries if e.get("sla", {}).get("breached")),
        "unacknowledged_critical": sum(
            1
            for e in entries
            if e["kind"] == "assistance_request"
            and e["urgency"] == Urgency.CRITICAL.value
            and not e["acknowledged"]
        ),
    }


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def dashboard(db: Session) -> dict[str, Any]:
    live = and_(Incident.archived.is_(False), Incident.duplicate_of.is_(None))
    impacts = [
        row
        for (row,) in db.execute(
            select(Incident.impact).where(live)
        ).all()
    ]
    incidents_24h = db.execute(
        select(func.count(Incident.id)).where(live, Incident.first_detected_at >= utcnow() - timedelta(days=1))
    ).scalar_one()
    by_type = db.execute(
        select(Incident.incident_type, func.count(Incident.id))
        .where(live)
        .group_by(Incident.incident_type)
        .order_by(func.count(Incident.id).desc())
    ).all()
    open_requests = db.execute(
        select(func.count(AssistanceRequest.id)).where(AssistanceRequest.status.in_(OPEN_STATUSES))
    ).scalar_one()
    critical_requests = db.execute(
        select(func.count(AssistanceRequest.id)).where(
            AssistanceRequest.status.in_(OPEN_STATUSES),
            AssistanceRequest.urgency == Urgency.CRITICAL.value,
        )
    ).scalar_one()
    by_urgency = dict(
        db.execute(
            select(AssistanceRequest.urgency, func.count(AssistanceRequest.id))
            .where(AssistanceRequest.status.in_(OPEN_STATUSES))
            .group_by(AssistanceRequest.urgency)
        ).all()
    )
    latest_event = db.execute(select(func.max(Incident.last_updated_at))).scalar_one_or_none()
    return {
        "generated_at": iso(utcnow()),
        "last_change": iso(latest_event),
        "last_change_label": humanize_age(latest_event),
        "incidents": {
            "total_active": db.execute(select(func.count(Incident.id)).where(live)).scalar_one(),
            "new_last_24h": incidents_24h,
            "needs_review": db.execute(
                select(func.count(Incident.id)).where(live, Incident.needs_review.is_(True))
            ).scalar_one(),
            # JSON extraction across dialects is not worth it for a counter this
            # small: recompute from the rows we already have.
            "cross_validated": sum(1 for impact in impacts if (impact or {}).get("cross_validated")),
            "by_type": {key: count for key, count in by_type},
        },
        "assistance": {
            "open": open_requests,
            "critical": critical_requests,
            "by_urgency": by_urgency,
        },
        "community": {
            "reports_last_24h": db.execute(
                select(func.count(CommunityReport.id)).where(
                    CommunityReport.created_at >= utcnow() - timedelta(days=1)
                )
            ).scalar_one(),
            "unverified_pending": db.execute(
                select(func.count(CommunityReport.id)).where(
                    CommunityReport.verification_status == "pending"
                )
            ).scalar_one(),
        },
    }


# --------------------------------------------------------------------------- #
# Incident reads
# --------------------------------------------------------------------------- #
def incident_summary(db: Session, incident: Incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "ref_code": incident.ref_code,
        "title": incident.title,
        "incident_type": incident.incident_type,
        "status": incident.status,
        "severity": incident.severity,
        "urgency": incident.urgency,
        "impact_score": incident.impact_score,
        "score_band": impact_band(incident.impact_score),
        "evidence_state": incident.evidence_state,
        "freshness_state": (incident.impact or {}).get("freshness_state", "unknown"),
        "district": incident.district,
        "province": incident.province,
        "local_municipality": incident.local_municipality,
        "location_name": incident.location_name,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "location_precision": incident.location_precision,
        "within_nepal": incident.within_nepal,
        "magnitude": incident.magnitude,
        "depth_km": incident.depth_km,
        "event_time": iso(incident.event_time),
        "event_time_label": humanize_age(incident.event_time),
        "first_detected_at": iso(incident.first_detected_at),
        "last_updated_at": iso(incident.last_updated_at),
        "updated_label": humanize_age(incident.last_updated_at),
        "impact": incident.impact or {},
        "community_report_count": incident.community_report_count,
        "open_assistance_count": incident.open_assistance_count,
        "supporting_signal_count": incident.supporting_signal_count,
        "conflicting_signal_count": incident.conflicting_signal_count,
        "needs_review": incident.needs_review,
        "review_reason": incident.review_reason,
        "prioritization_reasons": incident.prioritization_reasons or [],
        "provenance": incident.provenance,
        "demo": incident.provenance == "demo",
        "cluster_id": incident.cluster_id,
        "duplicate_count": db.execute(
            select(func.count(Incident.id)).where(Incident.duplicate_of == incident.id)
        ).scalar_one(),
    }


def impact_band(score: float) -> str:
    from backend.app.scoring import impact as impact_mod

    return impact_mod.band(score or 0.0)


def incident_detail(db: Session, incident: Incident, permissions: set[str] | None = None) -> dict[str, Any]:
    links = list(
        db.execute(
            select(IncidentObservation).where(IncidentObservation.incident_id == incident.id)
        ).scalars()
    )
    evidence_rows: list[dict[str, Any]] = []
    for row in links:
        obs = row.observation or db.get(Observation, row.observation_id)
        if obs is None:
            continue
        evidence_rows.append(_evidence_row(row, obs))
    evidence_rows.sort(key=lambda item: item["at"] or "", reverse=True)

    reports = community_service.recent_reports(db, incident_id=incident.id, limit=60)
    requests = list(
        db.execute(
            select(AssistanceRequest)
            .where(AssistanceRequest.incident_id == incident.id)
            .order_by(AssistanceRequest.created_at.desc())
            .limit(60)
        ).scalars()
    )
    state = EvidenceState(incident.evidence_state)
    meta = evidence_mod.state_meta(state)
    related = _related_incidents(db, incident)
    breakdown = incident.score_breakdown or {}

    return {
        "incident": incident_summary(db, incident),
        "why_prioritized": {
            "headline": _headline(incident),
            "reasons": incident.prioritization_reasons or [],
            "score": incident.impact_score,
            "score_band": impact_band(incident.impact_score),
            "formula": breakdown.get("formula"),
            "weights": breakdown.get("weights"),
            "components": breakdown.get("components"),
            "freshness_multiplier": breakdown.get("freshness_multiplier"),
            "explanation": "Deterministic score from official impact, community activity and "
            "evidence state. Older information is scaled down by the freshness multiplier.",
        },
        "evidence": {
            "state": state.value,
            "label": meta["label"],
            "meaning": meta["meaning"],
            "official_confirmation": incident.official_confirmation,
            "confirmed_by_source": incident.confirmed_by_source,
            "verified_by_operator": bool(incident.verified_by),
            "records": evidence_rows,
            "source_count": len({row.get("source") for row in evidence_rows if row.get("source")}),
            "conflicting_count": incident.conflicting_signal_count,
        },
        "timeline": incident_service.timeline(db, incident),
        "reports": [community_service.report_to_dict(db, report) for report in reports],
        "requests": [assistance.to_dict(db, request) for request in requests],
        "related_incidents": related,
        "signals": _signals_for(db, incident),
        "alerts": alert_service.list_alerts(db, district=incident.district, limit=5),
        "duplicates": [
            incident_summary(db, duplicate)
            for duplicate in db.execute(
                select(Incident).where(Incident.duplicate_of == incident.id).limit(20)
            ).scalars()
        ],
        "available_actions": available_actions(incident, permissions),
        "audit": [audit.to_dict(event) for event in audit.for_entity(db, audit.ENTITY_INCIDENT, incident.id, 40)],
    }


def _evidence_row(row: IncidentObservation, obs: Observation) -> dict[str, Any]:
    moment = obs.event_time or obs.received_at
    source = obs.source
    return {
        "observation_id": obs.id,
        "role": row.role,
        "linked_by": row.link_source,
        "linked_at": iso(row.linked_at),
        "kind": obs.kind,
        "incident_type": obs.incident_type,
        "title": obs.title,
        "summary": obs.summary[:400] if obs.summary else "",
        "district": obs.district,
        "location_name": obs.location_name,
        "latitude": obs.latitude,
        "longitude": obs.longitude,
        "magnitude": obs.magnitude,
        "value": obs.value,
        "unit": obs.unit,
        "severity": obs.severity,
        "deaths": obs.deaths,
        "injured": obs.injured,
        "missing": obs.missing,
        "affected_people": obs.affected_people,
        "at": iso(moment),
        "age": humanize_age(moment),
        "source": obs.source_id,
        "source_name": source.name if source else obs.source_id,
        "source_organization": source.organization if source else None,
        "official": bool(source.official) if source else obs.provenance == "official",
        "source_url": obs.source_url,
        "freshness_state": freshness_mod.of_observation(
            obs.kind,
            obs.event_time,
            obs.received_at,
            source.stale_after_seconds if source else 86_400,
        ).value,
        "authority": evidence_mod.authority_of(obs.source_id),
        "provenance": obs.provenance,
        "demo": obs.provenance == "demo",
    }


def _headline(incident: Incident) -> str:
    impact = incident.impact or {}
    parts = [incident.title or incident.incident_type.replace("_", " ").title()]
    if impact.get("deaths"):
        parts.append(f"{impact['deaths']} reported dead")
    if impact.get("injured"):
        parts.append(f"{impact['injured']} injured")
    if incident.community_report_count:
        parts.append(f"{incident.community_report_count} community reports")
    if incident.open_assistance_count:
        parts.append(f"{incident.open_assistance_count} open help requests")
    return "; ".join(parts)


def _related_incidents(db: Session, incident: Incident, radius_km: float = 25.0) -> list[dict[str, Any]]:
    if incident.latitude is None:
        return []
    out: list[dict[str, Any]] = []
    stmt = (
        select(Incident)
        .where(
            Incident.id != incident.id,
            Incident.archived.is_(False),
            Incident.duplicate_of.is_(None),
        )
        .order_by(Incident.last_updated_at.desc())
        .limit(400)
    )
    for other in db.execute(stmt).scalars():
        if other.latitude is None:
            continue
        distance = haversine_km(
            (incident.latitude, incident.longitude), (other.latitude, other.longitude)
        )
        if distance is None or distance > radius_km:
            continue
        out.append({**incident_summary(db, other), "distance_km": round(distance, 1)})
        if len(out) >= 8:
            break
    out.sort(key=lambda item: item["distance_km"])
    return out


def _signals_for(db: Session, incident: Incident) -> list[dict[str, Any]]:
    if not incident.district:
        return []
    rows = list(
        db.execute(
            select(RiskSignal).where(
                RiskSignal.active.is_(True), RiskSignal.district == incident.district
            )
        ).scalars()
    )
    return [signal_service.signal_to_dict(row) for row in rows]


def available_actions(
    incident: Incident, permissions: set[str] | None = None
) -> list[dict[str, Any]]:
    """Every move the server will actually accept for this incident right now.

    The UI renders its action bar from this list rather than hardcoding buttons, so a
    control can never appear that the API would then refuse. `permissions` is the
    viewer's permission set; pass None to list the surface without filtering it (used
    by in-process callers, never by an HTTP response).

    Each entry carries `action`, `method`, `path` and, for status moves, the `target`.
    Status targets are the legal ones for the incident's current state; a resolved
    incident offers no "contain" button because the server would reject one.
    """
    try:
        current = IncidentStatus(incident.status)
    except ValueError:
        current = IncidentStatus.ACTIVE
    forward = {
        IncidentStatus.ACTIVE: [IncidentStatus.MONITORING, IncidentStatus.CONTAINED],
        IncidentStatus.MONITORING: [IncidentStatus.ACTIVE, IncidentStatus.CONTAINED],
        IncidentStatus.CONTAINED: [IncidentStatus.RESOLVED, IncidentStatus.MONITORING],
        IncidentStatus.RESOLVED: [IncidentStatus.ARCHIVED],
        IncidentStatus.ARCHIVED: [],
    }
    ref = incident.id
    surface: list[tuple[str, str, str, str, str | None, str]] = [
        # action, label, method, path, status target, permission required
        ("verify", "Mark as verified by an operator", "POST", f"/api/rc/incidents/{ref}/verify", None, "incidents:update"),
        ("request_verification", "Send for official verification", "POST", f"/api/rc/incidents/{ref}/request-verification", None, "incidents:update"),
        ("note", "Add an operator note", "POST", f"/api/rc/incidents/{ref}/note", None, "incidents:update"),
        ("link_report", "Attach a community report as evidence", "POST", f"/api/rc/incidents/{ref}/link/report", None, "reports:link"),
        ("link_observation", "Attach a source record as evidence", "POST", f"/api/rc/incidents/{ref}/link/observation", None, "incidents:update"),
        ("merge", "Merge a duplicate into this incident", "POST", f"/api/rc/incidents/{ref}/merge", None, "incidents:merge"),
        ("split", "Split records out of this incident", "POST", f"/api/rc/incidents/{ref}/split", None, "incidents:split"),
    ]
    surface.extend(
        (
            "set_status",
            f"Set status to {target.value.replace('_', ' ').title()}",
            "POST",
            f"/api/rc/incidents/{ref}/status",
            target.value,
            "incidents:update",
        )
        for target in forward.get(current, [])
    )
    out: list[dict[str, Any]] = []
    for action, label, method, path, target, permission in surface:
        if permissions is not None and permission not in permissions:
            continue
        entry: dict[str, Any] = {
            "action": action,
            "label": label,
            "method": method,
            "path": path,
            "permission": permission,
        }
        if target is not None:
            entry["target"] = target
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Operator actions
# --------------------------------------------------------------------------- #
def set_status(
    db: Session, incident: Incident, operator: User, target: str, reason: str = ""
) -> Incident:
    previous = incident.status
    incident.status = target
    incident.last_updated_at = utcnow()
    if target == IncidentStatus.ARCHIVED.value:
        incident.archived = True
    db.add(
        AuditEvent(
            id=new_id("aud"),
            actor_id=operator.id,
            actor_label=operator.display_name or operator.username,
            actor_kind="operator",
            action="incident_status",
            entity_type=audit.ENTITY_INCIDENT,
            entity_id=incident.id,
            previous_value={"status": previous},
            new_value={"status": target},
            reason=reason or None,
            created_at=utcnow(),
        )
    )
    db.commit()
    return incident


def verify_as_operator(
    db: Session, incident: Incident, operator: User, reason: str
) -> Incident:
    """An accountable human confirming the picture. This is the only non-source
    route to OFFICIALLY_CONFIRMED, and it records who did it."""
    if not reason.strip():
        raise ValueError("A verification reason is required")
    incident.verified_by = operator.id
    incident.verified_at = utcnow()
    audit.record(
        db,
        action=AuditAction.VERIFY,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        previous={"evidence_state": incident.evidence_state},
        new={"verified_by": operator.display_name or operator.username},
        reason=reason,
    )
    incident_service.recompute(db, incident)
    db.commit()
    return incident


def request_more_verification(db: Session, incident: Incident, operator: User, reason: str) -> Incident:
    """The conservative move: mark that official confirmation is being chased, without
    claiming it."""
    incident.needs_review = True
    incident.review_reason = f"Operator requested verification: {reason[:180]}"
    audit.record(
        db,
        action=AuditAction.REQUEST_VERIFICATION,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        new={"requested_verification": True},
        reason=reason,
    )
    db.commit()
    return incident


def add_note(db: Session, incident: Incident, operator: User, note: str) -> Incident:
    entry = {
        "id": new_id("note"),
        "author": operator.display_name or operator.username,
        "author_id": operator.id,
        "note": note[:2000],
        "at": iso(utcnow()),
    }
    incident.operator_notes = [*incident.operator_notes, entry]
    audit.record(
        db,
        action=AuditAction.NOTE_ADDED,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        new={"note": note[:300]},
    )
    db.commit()
    return incident


def link_report(
    db: Session, incident: Incident, report: CommunityReport, operator: User
) -> Incident:
    previous = report.incident_id
    report.incident_id = incident.id
    report.duplicate_status = "unique" if report.duplicate_status == "duplicate" else report.duplicate_status
    incident_service.link_report_as_observation(db, incident, report, link_source="operator")
    audit.record(
        db,
        action=AuditAction.LINK_REPORT,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        previous={"report_id": report.id, "incident_id": previous},
        new={"report_id": report.id, "incident_id": incident.id},
    )
    incident_service.recompute(db, incident)
    if previous:
        other = db.get(Incident, previous)
        if other is not None:
            incident_service.recompute(db, other)
    db.commit()
    return incident


def link_observation(
    db: Session, incident: Incident, observation: Observation, operator: User, role: str = "supporting"
) -> Incident:
    """Manual provenance link - used when the correlator left an ambiguous pair for
    a human (or the agent) to decide."""
    incident_service.link(db, incident, observation, role=role, link_source="operator")
    audit.record(
        db,
        action="link_observation",
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        new={"observation_id": observation.id, "role": role},
    )
    incident_service.recompute(db, incident)
    db.commit()
    return incident


def merge(
    db: Session, primary: Incident, duplicate_ids: list[str], operator: User, reason: str
) -> Incident:
    """Fold duplicates into the primary incident.

    The duplicate rows are kept (with `duplicate_of`) rather than deleted, so the
    provenance of every observation stays intact and a merge can be undone.
    """
    if not reason.strip():
        raise ValueError("A merge reason is required")
    moved: list[str] = []
    for duplicate_id in duplicate_ids:
        duplicate = db.get(Incident, duplicate_id)
        if duplicate is None or duplicate.id == primary.id:
            continue
        for row in db.execute(
            select(IncidentObservation).where(IncidentObservation.incident_id == duplicate.id)
        ).scalars():
            row.incident_id = primary.id
            row.link_source = "operator"
        db.execute(
            CommunityReport.__table__.update()
            .where(CommunityReport.incident_id == duplicate.id)
            .values(incident_id=primary.id)
        )
        db.execute(
            AssistanceRequest.__table__.update()
            .where(AssistanceRequest.incident_id == duplicate.id)
            .values(incident_id=primary.id)
        )
        duplicate.duplicate_of = primary.id
        duplicate.archived = True
        duplicate.cluster_id = primary.cluster_id or duplicate.cluster_id
        moved.append(duplicate.ref_code)
    primary.last_updated_at = utcnow()
    audit.record(
        db,
        action=AuditAction.MERGE_INCIDENTS,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=primary.id,
        actor=operator,
        actor_kind="operator",
        new={"merged_into": primary.ref_code, "duplicates": moved},
        reason=reason,
    )
    incident_service.recompute(db, primary)
    db.commit()
    return primary


def split(
    db: Session, incident: Incident, report_ids: list[str], operator: User, reason: str
) -> Incident:
    """Move a set of reports into a fresh incident when the original grouping was
    wrong (e.g. two separate landslides in one district)."""
    if not report_ids:
        raise ValueError("Select at least one report to split out")
    moved = list(
        db.execute(select(CommunityReport).where(CommunityReport.id.in_(report_ids))).scalars()
    )
    first = moved[0]
    new_incident = Incident(
        id=new_id("inc"),
        ref_code=incident_service.new_ref_code("INC"),
        incident_type=first.incident_type or incident.incident_type,
        title=(first.location_text or first.district or "Split case") + " - separated from " + incident.ref_code,
        description=_first_line(first.message, 500),
        status=IncidentStatus.ACTIVE.value,
        severity=incident.severity,
        latitude=first.latitude,
        longitude=first.longitude,
        location_name=first.location_text,
        district=first.district or incident.district,
        province=first.province or incident.province,
        location_precision="user_shared" if first.latitude is not None else incident.location_precision,
        first_detected_at=utcnow(),
        last_updated_at=utcnow(),
        event_time=first.created_at,
        provenance=first.provenance,
        within_nepal=incident.within_nepal,
        demo_scenario_id=incident.demo_scenario_id,
    )
    db.add(new_incident)
    db.flush()
    for report in moved:
        report.incident_id = new_incident.id
    new_incident = incident_service.recompute(db, new_incident)
    audit.record(
        db,
        action=AuditAction.SPLIT_INCIDENT,
        entity_type=audit.ENTITY_INCIDENT,
        entity_id=incident.id,
        actor=operator,
        actor_kind="operator",
        new={"new_incident": new_incident.ref_code, "reports": [r.id for r in moved]},
        reason=reason,
    )
    incident_service.recompute(db, incident)
    db.commit()
    return new_incident


# --------------------------------------------------------------------------- #
# Lists used by the left-hand queue and the map
# --------------------------------------------------------------------------- #
def list_incidents(
    db: Session,
    *,
    incident_type: str | None = None,
    district: str | None = None,
    urgency: str | None = None,
    evidence_state: str | None = None,
    q: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    only_within_nepal: bool = False,
    min_score: float | None = None,
    limit: int = 200,
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.impact_score.desc(), Incident.last_updated_at.desc())
    if not include_archived:
        stmt = stmt.where(Incident.archived.is_(False))
    stmt = stmt.where(Incident.duplicate_of.is_(None))
    if incident_type:
        stmt = stmt.where(Incident.incident_type == incident_type)
    if district:
        stmt = stmt.where(Incident.district == district)
    if urgency:
        stmt = stmt.where(Incident.urgency == urgency)
    if evidence_state:
        stmt = stmt.where(Incident.evidence_state == evidence_state)
    if status:
        stmt = stmt.where(Incident.status == status)
    if only_within_nepal:
        stmt = stmt.where(Incident.within_nepal.is_(True))
    if min_score is not None:
        stmt = stmt.where(Incident.impact_score >= min_score)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Incident.title).like(pattern),
                func.lower(Incident.district).like(pattern),
                func.lower(Incident.location_name).like(pattern),
                func.lower(Incident.ref_code).like(pattern),
            )
        )
    return list(db.execute(stmt.limit(limit)).scalars())


def list_requests(
    db: Session,
    *,
    status: str | None = None,
    urgency: str | None = None,
    district: str | None = None,
    unassigned_only: bool = False,
    limit: int = 200,
) -> list[AssistanceRequest]:
    stmt = select(AssistanceRequest).order_by(AssistanceRequest.created_at.desc())
    if status:
        stmt = stmt.where(AssistanceRequest.status == status)
    if urgency:
        stmt = stmt.where(AssistanceRequest.urgency == urgency)
    if district:
        stmt = stmt.where(AssistanceRequest.district == district)
    if unassigned_only:
        stmt = stmt.where(AssistanceRequest.assigned_team.is_(None))
    return list(db.execute(stmt.limit(limit)).scalars())


def activity_feed(db: Session, limit: int = 40) -> list[dict[str, Any]]:
    """Bottom strip: what just happened across the whole system."""
    rows = audit.recent(db, limit=limit)
    out = []
    for event in rows:
        out.append(
            {
                "at": iso(event.created_at),
                "age": humanize_age(event.created_at),
                "actor": event.actor_label,
                "actor_kind": event.actor_kind,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "reason": event.reason,
                "summary": _event_summary(event),
            }
        )
    return out


def _event_summary(event: AuditEvent) -> str:
    new = event.new_value or {}
    if event.action == AuditAction.STATUS_CHANGE.value:
        return f"{event.entity_id}: {(event.previous_value or {}).get('status')} → {new.get('status')}"
    if event.action == AuditAction.MERGE_INCIDENTS.value:
        return f"merged {', '.join(new.get('duplicates', [])[:3])} into {new.get('merged_into')}"
    if event.action == AuditAction.ACKNOWLEDGE.value:
        return "request acknowledged"
    if event.action == "report_submitted":
        return "community report filed"
    return event.action.replace("_", " ")


def _first_line(text: str, limit: int = 160) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit] + ("…" if len(clean) > limit else "")
