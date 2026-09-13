"""Community-side service: report intake, local alerts, "my requests".

This is the entry point of the two-way loop. Everything a person sends is stored
with its own provenance (`community`), linked to the shared situation only by the
deterministic correlator, and never upgraded to official status by anything here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from backend.app.geo.boundaries import boundary_index, normalize_district
from backend.app.models.core import (
    AssistanceRequest,
    CommunityReport,
    Incident,
    User,
    new_id,
)
from backend.app.scoring import urgency as urgency_mod
from backend.app.services import alerts as alert_service
from backend.app.services import assistance, audit, notifications
from backend.app.services import incidents as incident_service
from backend.app.services import signals as signal_service
from shared.enums import (
    AssistanceType,
    IncidentType,
    ReportType,
    Urgency,
)
from shared.geo import haversine_km
from shared.timeutils import humanize_age, iso, utcnow

ATTENTION_WORTHY = {Urgency.CRITICAL.value, Urgency.URGENT.value}


# --------------------------------------------------------------------------- #
# Report intake
# --------------------------------------------------------------------------- #
def submit_report(
    db: Session,
    *,
    user: User | None,
    message: str,
    report_type: str = ReportType.INCIDENT.value,
    incident_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    location_text: str | None = None,
    people_count: int | None = None,
    medical_need: bool = False,
    injuries: int = 0,
    language: str = "en",
    attachments: list[dict[str, Any]] | None = None,
    client_timestamp: Any = None,
    submitted_offline: bool = False,
    needs_help: bool = False,
    help_types: list[str] | None = None,
    incident_id: str | None = None,
    immediate_danger: bool = False,
    provenance: str = "community",
    demo_scenario_id: str | None = None,
) -> tuple[CommunityReport, Incident | None, AssistanceRequest | None]:
    """File a community report, link it to the situation, and (optionally) turn the
    same text into an assistance request.

    Returns the three objects so the caller can show the reporter exactly what
    happened: "logged as a report", "linked to incident X" or "also raised a
    help request".
    """
    text = (message or "").strip()[:4000]
    location = assistance.resolve_location(
        db, latitude=latitude, longitude=longitude, location_text=location_text, user=user
    )
    hazard = incident_type or IncidentType.from_source_label(text).value

    report = CommunityReport(
        id=new_id("rep"),
        user_id=user.id if user else None,
        report_type=report_type if report_type in {r.value for r in ReportType} else ReportType.INCIDENT.value,
        message=text,
        structured={
            "injuries": injuries,
            "immediate_danger": immediate_danger,
            "source_of_urgency": "user_declared",
        },
        latitude=location["latitude"],
        longitude=location["longitude"],
        location_text=location["location_text"],
        location_confidence=location["location_confidence"],
        district=location["district"],
        province=location["province"],
        incident_type=hazard,
        urgency=Urgency.INFORMATION.value,
        people_count=people_count,
        medical_need=medical_need,
        attachments=attachments or [],
        language=language,
        client_timestamp=_parse_client_ts(client_timestamp),
        submitted_offline=submitted_offline,
        provenance=provenance,
        demo_scenario_id=demo_scenario_id,
        created_at=utcnow(),
    )
    db.add(report)
    db.flush()

    linked = db.get(Incident, incident_id) if incident_id else None
    if linked is not None:
        report.incident_id = linked.id
        report.distance_to_incident_km = _distance_to(report, linked)
        incident_service.link_report_as_observation(db, linked, report)
    else:
        # attach_report does the correlation, the distance and the duplicate check.
        linked, _distance = incident_service.attach_report(db, report)

    report.severity = _severity_hint(text, medical_need, injuries)
    corroborating = len(report.corroborating_report_ids or [])
    report.urgency = urgency_mod.classify_report(
        incident_type=hazard,
        message=text,
        medical_need=medical_need,
        injuries=injuries,
        people_count=people_count or 1,
        corroborating_reports=corroborating,
        official_backing=bool(linked and linked.official_confirmation),
    ).value

    request = None
    wants_help = needs_help or (report.urgency == Urgency.CRITICAL.value and _asks_for_help(text))
    open_prior = (
        _open_request_behind(db, report) if wants_help and report.duplicate_status == "duplicate" else None
    )
    if wants_help and open_prior is not None:
        # Someone re-sending the same plea inside the dedupe window does not add a
        # second case to work - but the repeat is itself information: they are still
        # waiting. So it is carried onto the open case and escalated, never dropped.
        assistance.carry_repeat_plea(db, open_prior, language=language, report_id=report.id)
        report.structured = {**(report.structured or {}), "help_carried_on": open_prior.ref_code}
        request = open_prior
    elif wants_help:
        request = assistance.create(
            db,
            user=user,
            description=text,
            request_type=(help_types or [AssistanceType.OTHER.value])[0],
            assistance_types=help_types or [],
            latitude=report.latitude,
            longitude=report.longitude,
            location_text=report.location_text,
            people_count=people_count or 1,
            medical_need=medical_need,
            immediate_danger=immediate_danger,
            incident_id=report.incident_id,
            report_id=report.id,
            language=language,
            attachments=attachments or [],
            submitted_offline=submitted_offline,
            provenance=provenance,
            demo_scenario_id=demo_scenario_id,
            structured={"from_report": report.id},
        )

    audit.record(
        db,
        action="report_submitted",
        entity_type=audit.ENTITY_REPORT,
        entity_id=report.id,
        actor=user,
        actor_kind="victim",
        new={
            "incident_id": report.incident_id,
            "urgency": report.urgency,
            "duplicate_status": report.duplicate_status,
            "assistance_request_id": request.id if request else None,
        },
        reason="offline resubmission" if submitted_offline else None,
    )
    if linked is not None:
        incident_service.recompute(db, linked)
    if report.urgency in ATTENTION_WORTHY and (linked is None or linked.needs_review):
        notifications.push(
            db,
            audience=notifications.AUDIENCE_RESPONSE_CENTER,
            title=f"{report.urgency.upper()} community report"
            + (f" in {report.district}" if report.district else ""),
            body=_first_line(text),
            kind="report",
            severity=report.urgency,
            link=f"/response-center/reports/{report.id}",
            incident_id=report.incident_id,
            district=report.district,
        )
    db.commit()
    db.refresh(report)
    return report, linked, request


def _open_request_behind(db: Session, report: CommunityReport) -> AssistanceRequest | None:
    """The still-open assistance case behind a duplicate report, if there is one.

    Only the reporter's own case counts, and a resolved or cancelled one does not: a
    person who asks again after being closed out is starting a new case, and the queue
    has to see that as a new case.

    The lookup follows the duplicate chain rather than taking one step. A report that
    was carried onto an open case starts no case of its own, so the newest duplicate
    usually has no request attached and the real one sits further down the chain -
    report three points at report two, which points at report one, which owns the
    request. Stopping early when a request is found but closed is deliberate: the
    chain ends where the person's case ended.
    """
    seen: set[str] = {report.id}
    cursor = report.duplicate_of_report_id
    for _hop in range(10):
        if not cursor or cursor in seen:
            return None
        seen.add(cursor)
        prior = db.execute(
            select(AssistanceRequest)
            .where(AssistanceRequest.report_id == cursor)
            .order_by(desc(AssistanceRequest.created_at))
            .limit(1)
        ).scalar_one_or_none()
        if prior is not None:
            if not assistance.is_open(prior):
                return None
            if report.user_id and prior.user_id != report.user_id:
                return None
            return prior
        parent = db.get(CommunityReport, cursor)
        if parent is None:
            return None
        cursor = parent.duplicate_of_report_id
    return None


def _asks_for_help(text: str) -> bool:
    lowered = (text or "").lower()
    keywords = ("help", "rescue", "trapped", "stuck", "injured", "bleeding", "urgent", "मद्दत", "उद्धार")
    return any(word in lowered for word in keywords)


def _severity_hint(text: str, medical_need: bool, injuries: int) -> str | None:
    lowered = (text or "").lower()
    if injuries or medical_need or any(k in lowered for k in ("dead", "died", "collapsed", "buried")):
        return "severe" if injuries and injuries >= 3 else "high"
    if any(k in lowered for k in ("flood", "landslide", "fire", "blocked")):
        return "moderate"
    return None


def _parse_client_ts(value: Any):
    if not value:
        return None
    if isinstance(value, (int, float)):
        from shared.timeutils import epoch_ms_to_utc

        return epoch_ms_to_utc(value)
    from shared.timeutils import parse_iso

    return parse_iso(str(value))


# --------------------------------------------------------------------------- #
# Reads for the community app
# --------------------------------------------------------------------------- #
def local_feed(
    db: Session,
    *,
    user: User | None = None,
    district: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    language: str = "en",
) -> dict[str, Any]:
    """Everything a person nearby should see: official alerts, area risk signals
    and officially-backed incidents. Community reports are deliberately excluded
    from the alert feed so unverified claims never read as official warnings."""
    area = district or (user.home_district if user else None)
    if not area and latitude is not None and longitude is not None:
        area = boundary_index.resolve_point(latitude, longitude).district
    alerts = alert_service.list_alerts(db, district=area, limit=10)
    signals = [
        signal_service.signal_to_dict(signal)
        for signal in signal_service.active_signals(db, limit=200)
        if area is None or signal.district == area
    ]
    incidents = _nearby_official_incidents(db, area, latitude, longitude)
    return {
        "district": area,
        "generated_at": iso(utcnow()),
        "language": language,
        "alerts": alerts,
        "signals": signals,
        "incidents": incidents,
        "counts": {
            "alerts": len(alerts),
            "signals": len(signals),
            "incidents": len(incidents),
        },
        "empty_message": None
        if (alerts or signals or incidents)
        else _no_alerts_line(area, language),
    }


def _no_alerts_line(district: str | None, language: str) -> str:
    if language == "ne":
        return "अहिले तपाईंको क्षेत्रका लागि कुनै आधिकारिक सूचना छैन।" + (
            f" ({district})" if district else ""
        )
    prefix = "No official alerts for your area right now"
    return f"{prefix}{' (' + district + ')' if district else ''}."


def _nearby_official_incidents(
    db: Session,
    district: str | None,
    latitude: float | None,
    longitude: float | None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    cutoff = utcnow() - timedelta(days=7)
    stmt = (
        select(Incident)
        .where(
            Incident.archived.is_(False),
            Incident.duplicate_of.is_(None),
            Incident.provenance != "demo",
            Incident.first_detected_at >= cutoff,
        )
        .order_by(Incident.impact_score.desc())
        .limit(limit * 3)
    )
    wanted = normalize_district(district) if district else None
    out: list[dict[str, Any]] = []
    for incident in db.execute(stmt).scalars():
        if incident.official_confirmation is False and incident.evidence_state in {
            "unverified",
            "community_reported",
        }:
            continue
        near = True
        if wanted:
            near = (normalize_district(incident.district) == wanted) or _within(
                latitude, longitude, incident, 60.0
            )
        if not near:
            continue
        out.append(
            {
                "id": incident.id,
                "ref_code": incident.ref_code,
                "title": incident.title,
                "incident_type": incident.incident_type,
                "severity": incident.severity,
                "district": incident.district,
                "location_name": incident.location_name,
                "latitude": incident.latitude,
                "longitude": incident.longitude,
                "location_precision": incident.location_precision,
                "event_time": iso(incident.event_time),
                "updated_label": humanize_age(incident.last_updated_at),
                "evidence_state": incident.evidence_state,
                "freshness_state": (incident.impact or {}).get("freshness_state"),
                "within_nepal": incident.within_nepal,
                "provenance": incident.provenance,
            }
        )
        if len(out) >= limit:
            break
    return out


def _within(lat: float | None, lng: float | None, incident: Incident, radius_km: float) -> bool:
    if lat is None or lng is None or incident.latitude is None:
        return False
    from shared.geo import haversine_km

    distance = haversine_km((lat, lng), (incident.latitude, incident.longitude))
    return distance is not None and distance <= radius_km


def my_activity(db: Session, user: User) -> dict[str, Any]:
    """'MY REQUESTS' plus the reports this person filed - the victim's own trail."""
    requests = list(
        db.execute(
            select(AssistanceRequest)
            .where(AssistanceRequest.user_id == user.id)
            .order_by(AssistanceRequest.created_at.desc())
            .limit(50)
        ).scalars()
    )
    reports = list(
        db.execute(
            select(CommunityReport)
            .where(CommunityReport.user_id == user.id)
            .order_by(CommunityReport.created_at.desc())
            .limit(50)
        ).scalars()
    )
    return {
        "requests": [assistance.to_dict(db, r, victim_view=True) for r in requests],
        "reports": [report_to_dict(db, r) for r in reports],
        "open_count": sum(
            1 for r in requests if r.status not in {"resolved", "cancelled"}
        ),
    }


def report_to_dict(db: Session, report: CommunityReport) -> dict[str, Any]:
    incident = db.get(Incident, report.incident_id) if report.incident_id else None
    return {
        "id": report.id,
        "message": report.message,
        "report_type": report.report_type,
        "incident_type": report.incident_type,
        "urgency": report.urgency,
        "severity": report.severity,
        "district": report.district,
        "location_text": report.location_text,
        "location_confidence": report.location_confidence,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "language": report.language,
        "duplicate_status": report.duplicate_status,
        "corroborating_count": len(report.corroborating_report_ids or []),
        "verification_status": report.verification_status,
        "distance_to_incident_km": report.distance_to_incident_km,
        "submitted_offline": report.submitted_offline,
        # If this message was a repeat of a plea still open, say which case took it -
        # the reporter is owed the difference between "ignored" and "added to yours".
        "carried_on_request": (report.structured or {}).get("help_carried_on"),
        "incident": (
            {"id": incident.id, "ref_code": incident.ref_code, "title": incident.title}
            if incident
            else None
        ),
        "at": iso(report.created_at),
        "age": humanize_age(report.created_at),
        "provenance": report.provenance,
        "demo": report.provenance == "demo",
    }


def recent_reports(
    db: Session,
    *,
    district: str | None = None,
    incident_id: str | None = None,
    include_duplicates: bool = False,
    limit: int = 100,
) -> list[CommunityReport]:
    stmt = select(CommunityReport).order_by(CommunityReport.created_at.desc()).limit(limit)
    if district:
        stmt = stmt.where(CommunityReport.district == district)
    if incident_id:
        stmt = stmt.where(CommunityReport.incident_id == incident_id)
    if not include_duplicates:
        stmt = stmt.where(
            or_(
                CommunityReport.duplicate_status != "duplicate",
                CommunityReport.duplicate_status.is_(None),
            )
        )
    return list(db.execute(stmt).scalars())


def verify_report(
    db: Session, report: CommunityReport, operator: User, status: str, reason: str = ""
) -> CommunityReport:
    """Operator verification. This raises the *report's* verification status; an
    incident's evidence state only changes through recomputation, which weighs this
    alongside the official records."""
    previous = report.verification_status
    report.verification_status = status
    audit.record(
        db,
        action="verify" if status == "verified" else "report_rejected",
        entity_type=audit.ENTITY_REPORT,
        entity_id=report.id,
        actor=operator,
        actor_kind="operator",
        previous={"verification_status": previous},
        new={"verification_status": status},
        reason=reason or None,
    )
    if report.incident_id:
        incident = db.get(Incident, report.incident_id)
        if incident is not None:
            incident_service.recompute(db, incident)
    db.commit()
    return report


def _distance_to(report: CommunityReport, incident: Incident) -> float | None:
    if report.latitude is None or incident.latitude is None:
        return None
    distance = haversine_km(
        (report.latitude, report.longitude), (incident.latitude, incident.longitude)
    )
    return None if distance is None else round(distance, 2)


def _first_line(text: str, limit: int = 180) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit] + ("…" if len(clean) > limit else "")
