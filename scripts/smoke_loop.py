"""End-to-end two-way loop on live data: community report -> incident linkage ->
assistance request -> operator actions -> victim-visible timeline.

Run after scripts/smoke_slice.py so the database already holds real observations.
Nothing here synthesises an incident: if there is no live Nepal incident to attach
to, the script says so and stops.
"""

from __future__ import annotations

import sys

import _bootstrap

_bootstrap.prepare()

from sqlalchemy import select  # noqa: E402

from backend.app.db import SessionLocal, init_db  # noqa: E402
from backend.app.models.core import Incident  # noqa: E402
from backend.app.services import (
    assistance,  # noqa: E402
    audit,  # noqa: E402
    ingestion,  # noqa: E402
    notifications,  # noqa: E402
    response_center,  # noqa: E402
)
from backend.app.services import community as community_service  # noqa: E402
from backend.app.services import users as user_service  # noqa: E402
from shared.enums import AssistanceStatus, Urgency  # noqa: E402

ISSUES: list[str] = []


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def show(label: str, value: object) -> None:
    print(f"  {label}: {value}")


def note_issue(text: str) -> None:
    ISSUES.append(text)
    print(f"  [ISSUE] {text}")


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        setup(db)
        incident = pick_live_incident(db)
        if incident is None:
            note_issue("No live Nepal incident in the database - run scripts/smoke_slice.py first")
            return 1
        report, linked, request = file_report(db, incident)
        if report is None or request is None:
            return 0
        work_the_case(db, request)
        read_back(db, request, linked)
        print("\n=== Issues to fix later ===")
        for issue in ISSUES or ["none"]:
            print(f"  - {issue}")
        return 0
    finally:
        db.close()


def setup(db) -> None:
    step("Setup")
    show("sources registered", ingestion.ensure_sources(db))
    show("demo users added", user_service.ensure_demo_users(db))
    show("accounts", user_service.counts(db))


def pick_live_incident(db) -> Incident | None:
    step("Live incident to attach to")
    # Prefer a real seismic event inside Nepal (that is the mandated slice); fall
    # back to any located official incident so the loop is still tested on real data.
    incident = db.execute(
        select(Incident)
        .where(
            Incident.archived.is_(False),
            Incident.duplicate_of.is_(None),
            Incident.provenance == "official",
            Incident.latitude.is_not(None),
            Incident.incident_type == "earthquake",
        )
        .order_by(Incident.within_nepal.desc(), Incident.impact_score.desc())
        .limit(1)
    ).scalar_one_or_none()
    if incident is None:
        note_issue("No earthquake incident available - falling back to another official incident type")
        incident = db.execute(
            select(Incident)
            .where(
                Incident.archived.is_(False),
                Incident.duplicate_of.is_(None),
                Incident.provenance == "official",
                Incident.latitude.is_not(None),
            )
            .order_by(Incident.within_nepal.desc(), Incident.impact_score.desc())
            .limit(1)
        ).scalar_one_or_none()
    if incident is None:
        return None
    show("ref", incident.ref_code)
    show("title", incident.title)
    show("type", incident.incident_type)
    show("district", incident.district)
    show("evidence", incident.evidence_state)
    show("coords", f"{incident.latitude}, {incident.longitude}")
    return incident


HAZARD_WORDS = {
    "earthquake": "The house cracked in the shaking and two people inside are injured.",
    "flood": "Water has entered our house and two people are hurt.",
    "landslide": "A landslide hit close to the house and two people are injured.",
}


def file_report(db, incident: Incident):
    step("Community: REPORT SOMETHING + I NEED HELP")
    reporter = user_service.get_by_username(db, "ram.prasad")
    hazard = incident.incident_type
    text = HAZARD_WORDS.get(hazard, "Two people are injured here after the event.")
    text += (
        " Please send help, the road to the health post is blocked. "
        "गार्हो भत्कियो, उद्धार गर्नुहोस्।"
    )
    # ~1 km from the official event, coordinates shared, Nepali mixed in - the
    # realistic worst case for the community app.
    report, linked, request = community_service.submit_report(
        db,
        user=reporter,
        message=text,
        incident_type=hazard,
        latitude=(incident.latitude or 28.0) - 0.01,
        longitude=incident.longitude or 84.0,
        location_text="near " + (incident.location_name or incident.district or "the event"),
        people_count=4,
        medical_need=True,
        injuries=2,
        language="ne",
        needs_help=True,
        help_types=["medical", "rescue"],
        immediate_danger=True,
    )
    show("report id", report.id)
    show("report urgency", report.urgency)
    show("report district", report.district)
    show("location confidence", report.location_confidence)
    show("linked incident", linked.ref_code if linked else None)
    show("distance to incident km", report.distance_to_incident_km)
    show("duplicate status", report.duplicate_status)
    if linked is None:
        note_issue("Correlator did not attach the report to the live incident it was filed next to")
    if request is None:
        note_issue("A medical + immediate-danger report did not create an assistance request")
        return report, linked, None
    show("request ref", request.ref_code)
    show("request urgency", request.urgency)
    show("urgency reasons", request.urgency_reasons)
    show("sla", assistance.sla_info(request))
    show("evidence state of incident now", linked.evidence_state if linked else "-")
    if linked is not None and linked.evidence_state == "community_reported":
        note_issue("Community report downgraded an officially confirmed incident")
    return report, linked, request


def work_the_case(db, request) -> None:
    step("Response Center: work the case")
    operator = user_service.get_by_username(db, "sunita.rc")
    token = user_service.issue_token(operator)
    show("operator token issued", token[:24] + "...")

    queue = response_center.action_queue(db)
    show("queue counts", queue["counts"])
    show("critical unacknowledged", queue["unacknowledged_critical"])
    in_queue = any(e["id"] == request.id for e in queue["buckets"].get(request.urgency, []))
    show("this request is in the action queue", in_queue)
    if not in_queue:
        note_issue("Newly filed request did not appear in the action queue")

    assistance.acknowledge(db, request, operator)
    show("status after acknowledge", request.status)
    if request.status != AssistanceStatus.REVIEWING.value:
        note_issue("Acknowledging did not move the case to REVIEWING, so the victim sees no human contact")
    assistance.assign(db, request, operator, team="District Emergency Operation Center", note="Ambulance dispatched")
    assistance.change_status(db, request, operator, AssistanceStatus.IN_PROGRESS.value, note="Team on the road")
    assistance.send_victim_update(
        db, request, operator, "A health-post team is on the way with an ambulance. Stay on this channel."
    )
    try:
        assistance.change_status(db, request, operator, AssistanceStatus.RECEIVED.value)
        note_issue("Lifecycle allowed a backwards status jump to RECEIVED")
    except assistance.StatusTransitionError:
        show("backwards transition rejected", "RECEIVED (expected)")
    assistance.change_status(db, request, operator, AssistanceStatus.RESOLVED.value, note="Casualty reached hospital")
    show("status", request.status)
    show("resolved at", request.resolved_at)


def read_back(db, request, incident: Incident | None) -> None:
    step("Victim's view (what Ram Prasad actually sees)")
    victim = user_service.get_by_username(db, "ram.prasad")
    activity = community_service.my_activity(db, victim)
    show("my requests", len(activity.get("requests", [])))
    for item in activity.get("requests", [])[:3]:
        show("  request", f"{item.get('ref_code')} {item.get('status')} - {item.get('status_label')}")
    timeline = assistance.timeline(db, request, victim_view=True)
    for entry in timeline:
        print(f"    [{entry['at']}] {entry['kind']:<10} {entry['actor']}: {entry['message'][:90]}")
    if len(timeline) < 5:
        note_issue(f"Victim timeline has only {len(timeline)} entries - operator actions are not surfacing")

    step("Notifications")
    personal = notifications.for_user(db, victim.id, district=victim.home_district)
    show("victim notifications", len(personal))
    unread = notifications.unread_count(db, user_id=victim.id)
    show("victim unread", unread)
    if personal:
        notifications.mark_read(db, personal[0].id, victim.id)
        db.commit()
        show("after marking one read", notifications.unread_count(db, user_id=victim.id))

    step("Audit trail for this case")
    events = audit.for_entity(db, audit.ENTITY_REQUEST, request.id)
    for event in events:
        show(f"  {event.action}", f"by {event.actor_kind}:{event.actor_label}")
    if not events:
        note_issue("No audit rows for an assistance request that was acknowledged, assigned and resolved")

    step("Response Center incident detail")
    incident = incident or (db.get(Incident, request.incident_id) if request.incident_id else None)
    if incident is None:
        note_issue("Assistance request ended up with no incident link")
        return
    detail = response_center.incident_detail(db, incident)
    why = detail.get("why_prioritized", {})
    show("why (headline)", why.get("headline"))
    show("score", why.get("score"))
    show("formula", why.get("formula"))
    show("weights", why.get("weights"))
    components = why.get("components") or {}
    for name, comp in components.items():
        # Every component is shown as raw -> contribution so the score can be checked
        # by hand against the published formula.
        if isinstance(comp, dict):
            show(
                f"  {name}",
                f"raw={comp.get('raw')} x weight={comp.get('weight')} "
                f"= {comp.get('contribution')}",
            )
        else:
            show(f"  {name}", comp)
    seismic = [
        name for name, comp in components.items()
        if isinstance(comp, dict) and (comp.get("contribution") or 0) > 0
    ]
    if not seismic:
        note_issue("every impact-score component is zero for an officially confirmed event")
    evidence = detail.get("evidence", {})
    show("evidence state", f"{evidence.get('label')} - {evidence.get('meaning')}")
    show("evidence records", len(evidence.get("records", [])))
    show("official sources", evidence.get("source_count"))
    show("confirmed by", evidence.get("confirmed_by_source"))
    show("community reports", len(detail.get("reports", [])))
    show("requests on incident", len(detail.get("requests", [])))
    show("signals", [row.get("label") for row in detail.get("signals", [])])
    show("timeline entries", len(detail.get("timeline", [])))
    show(
        "available actions",
        [
            # Only `set_status` carries a `target`; the other actions gained labels and paths when
            # the surface stopped listing status moves alone, so an absent target is the normal case
            # here and not a payload problem.
            f"{a['action']} -> {a['target']}" if a.get("target") else a["action"]
            for a in detail.get("available_actions", [])
        ],
    )
    show("audit rows in detail", len(detail.get("audit", [])))
    if not evidence.get("records"):
        note_issue("incident_detail returned no evidence records for an incident built from official data")
    if not components:
        note_issue("why_prioritized has no score components - the number would be unexplainable")
    if Urgency(request.urgency) == Urgency.CRITICAL and not detail.get("requests"):
        note_issue("Critical request is missing from the incident detail payload")


if __name__ == "__main__":
    sys.exit(main())
