"""Scripted scenarios, replayed through the real pipeline.

Two rules shape everything here:

1. A demo step is not a parallel fake universe. Every step goes through the same
   services the live system uses - `ingestion.upsert_observations`, `incidents.absorb`,
   `community.submit_report`, `assistance.change_status` - so what an operator watches
   during a rehearsal is the actual correlation, scoring and lifecycle code, not a
   recording of it. The only difference is `provenance="demo"` and the clock.

2. Facilities are never simulated. A demo help request is matched against the real
   OpenStreetMap-seeded catalogue, because "the nearest hospital" is a fact about Nepal
   and an invented one is worse than none. If the catalogue is empty, the demo request
   shows an empty resource list - the same honest nothing the live system shows.

Demo rows are deleted when demo mode is cleared, so a rehearsal can never leave a
synthetic incident behind in a live system.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.models.core import (
    AgentInvestigation,
    AssistanceRequest,
    AssistanceUpdate,
    AuditEvent,
    CommunityReport,
    DemoEvent,
    Incident,
    IncidentObservation,
    Notification,
    Observation,
    Resource,
    User,
)
from backend.app.services import assistance, audit, ingestion
from backend.app.services import community as community_service
from backend.app.services import incidents as incident_service
from backend.app.services import resources as resource_service
from backend.app.services import signals as signal_service
from backend.app.services import state as system_state
from data_ingestion.normalizers.observation import NormalizedObservation
from shared.enums import AssistanceStatus, AuditAction, IncidentType, ObservationKind
from shared.timeutils import iso, parse_iso, real_utcnow, set_simulated_clock, utcnow

logger = logging.getLogger("sanket.demo")

DEMO_PROVENANCE = "demo"
DEMO_ACTOR_USER = "sunita.rc"
DEMO_REPORTER_USER = "ram.prasad"


# --------------------------------------------------------------------------- #
# The scenarios
# --------------------------------------------------------------------------- #
# Offsets are seconds from the moment the scenario is armed, so a 6-step sequence can be
# replayed over six minutes or, at speed=60, over six seconds. Nothing here pretends to be
# a forecast: each step is a *report* of something that "happened" inside the script.
SCENARIOS: dict[str, dict[str, Any]] = {
    "gorkha_aftershock": {
        "name": "Gorkha aftershock sequence",
        "summary": (
            "An M5.6 aftershock north of Pokhara: an official bulletin, then community "
            "reports arriving before the second bulletin, then a trapped-people request "
            "that has to be worked while the casualty count is still being revised."
        ),
        "districts": ["Gorkha", "Dhading"],
        "steps": [
            {
                "at": 0,
                "kind": "official_update",
                "label": "Seismological bulletin: M5.6, 8 km NE of Gorkha",
                "payload": {
                    "kind": ObservationKind.EARTHQUAKE.value,
                    "incident_type": IncidentType.EARTHQUAKE.value,
                    "title": "M5.6 earthquake - 8 km NE of Gorkha",
                    "summary": "Demo bulletin. Depth 10 km, felt across the mid-hills.",
                    "latitude": 28.1,
                    "longitude": 84.72,
                    "district": "Gorkha",
                    "magnitude": 5.6,
                    "depth_km": 10.0,
                    "severity": "moderate",
                },
            },
            {
                "at": 45,
                "kind": "report",
                "label": "Nepali report: stone house collapsed in Chhiabishe",
                "payload": {
                    "message": "Chhiabishe ma dhuwa ghar bhanke, 4 jana phansiya cha",
                    "language": "ne",
                    "report_type": "incident",
                    "incident_type": IncidentType.EARTHQUAKE.value,
                    "latitude": 28.03,
                    "longitude": 84.71,
                    "location_text": "Chhiabishe-4, Gorkha",
                    "people_count": 4,
                    "immediate_danger": True,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 90,
                "kind": "request",
                "label": "Help request: medical + rescue for 4 trapped",
                "payload": {
                    "message": "4 jana bhitra phansi aako cha, ek jna ghayal, hami lai uddhar chha",
                    "language": "ne",
                    "latitude": 28.03,
                    "longitude": 84.71,
                    "location_text": "Chhiabishe-4, Gorkha",
                    "help_types": ["rescue", "medical"],
                    "people_count": 4,
                    "medical_need": True,
                    "immediate_danger": True,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 150,
                "kind": "official_update",
                "label": "Second bulletin: 2 dead, 11 injured (revised)",
                "payload": {
                    "kind": ObservationKind.OFFICIAL_INCIDENT.value,
                    "incident_type": IncidentType.EARTHQUAKE.value,
                    "title": "Gorkha aftershock - casualty revision",
                    "summary": "Demo revision. Numbers moved after a ground check.",
                    "latitude": 28.08,
                    "longitude": 84.65,
                    "district": "Gorkha",
                    "deaths": 2,
                    "injured": 11,
                    "houses_damaged": 60,
                    "affected_people": 400,
                    "severity": "high",
                },
            },
            {
                # The lifecycle is enforced, not narrated: `received` cannot jump to
                # `in_progress`, so the rehearsal walks the real chain
                # received -> reviewing -> response_team_notified -> in_progress and shows
                # an operator what a skipped step would cost them.
                "at": 210,
                "kind": "status",
                "label": "Operator reviews the request",
                "payload": {
                    "target": AssistanceStatus.REVIEWING.value,
                    "note": "Demo: report checked against the bulletin and the map",
                },
            },
            {
                "at": 250,
                "kind": "status",
                "label": "District rescue team tasked",
                "payload": {
                    "target": AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value,
                    "note": "Demo: district police team tasked, ETA 40 minutes",
                },
            },
            {
                "at": 300,
                "kind": "status",
                "label": "Team en route, request moves to in_progress",
                "payload": {
                    "target": AssistanceStatus.IN_PROGRESS.value,
                    "note": "Demo: rescue party left Damauli",
                },
            },
            {
                "at": 360,
                "kind": "signal",
                "label": "Aftershock risk signal rebuilt for Gorkha",
                "payload": {"district": "Gorkha"},
            },
        ],
    },
    "bagmati_flood": {
        "name": "Bagmati river rising",
        "summary": (
            "A gauge crosses warning stage, rainfall keeps falling upstream, and a "
            "low-lying ward loses its road. Shows a risk signal becoming an incident "
            "and a shelter request being matched against real facilities."
        ),
        "districts": ["Kathmandu", "Bhaktapur", "Rautahat"],
        "steps": [
            {
                "at": 0,
                "kind": "official_update",
                "label": "River gauge: Bagmati at Chapagaun above warning stage",
                "payload": {
                    "kind": ObservationKind.RIVER_LEVEL.value,
                    "incident_type": IncidentType.FLOOD.value,
                    "title": "Bagmati at Chapagaun - warning stage exceeded",
                    "summary": "Demo gauge reading. Level 2.9 m against a 2.4 m warning stage.",
                    "latitude": 27.6,
                    "longitude": 85.36,
                    "district": "Lalitpur",
                    "value": 2.9,
                    "unit": "m",
                    "threshold_state": "warning",
                    "trend": "rising",
                    "severity": "high",
                },
            },
            {
                "at": 60,
                "kind": "official_update",
                "label": "Rainfall: 148 mm in 6 h at Pharping",
                "payload": {
                    "kind": ObservationKind.RAINFALL.value,
                    "incident_type": IncidentType.HEAVY_RAINFALL.value,
                    "title": "Pharping automatic station - 148 mm / 6 h",
                    "latitude": 27.67,
                    "longitude": 85.28,
                    "district": "Kavrepalanchok",
                    "value": 148.0,
                    "unit": "mm",
                    "threshold_state": "warning",
                    "severity": "moderate",
                },
            },
            {
                "at": 120,
                "kind": "report",
                "label": "Report: ward road under water, no boats",
                "payload": {
                    "message": "Ward 9 ko sadak paani ma chha. Nauka chhaaina.",
                    "language": "ne",
                    "latitude": 27.63,
                    "longitude": 85.34,
                    "location_text": "Ward 9, Bagmati corridor",
                    "incident_type": IncidentType.FLOOD.value,
                    "people_count": 200,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 180,
                "kind": "request",
                "label": "Help request: shelter + food for 34 people",
                "payload": {
                    "message": "34 jana sarnarthako lagi thau khoji raheko cha, khana pani chha",
                    "language": "ne",
                    "latitude": 27.63,
                    "longitude": 85.34,
                    "location_text": "Ward 9, Bagmati corridor",
                    "help_types": ["shelter", "food"],
                    "people_count": 34,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 240,
                "kind": "signal",
                "label": "Flood risk signal rebuilt for Kathmandu valley",
                "payload": {"district": "Kathmandu"},
            },
        ],
    },
    "dharan_landslide": {
        "name": "Highway cut by a landslide",
        "summary": (
            "A monsoon landslide blocks the Biratnagar-Kathmandu corridor at Dharan. "
            "One incident absorbs two official records and a community report, and the "
            "repeat plea from the same person shows escalation without a duplicate case."
        ),
        "districts": ["Sunsari", "Morang"],
        "steps": [
            {
                "at": 0,
                "kind": "official_update",
                "label": "Road notice: highway blocked at Dharan-19",
                "payload": {
                    "kind": ObservationKind.ROAD_STATUS.value,
                    "incident_type": IncidentType.ROAD_BLOCKAGE.value,
                    "title": "Biratnagar-Kathmandu highway blocked, Dharan-19",
                    "summary": "Demo road notice. Clearance equipment reported on the way.",
                    "latitude": 26.81,
                    "longitude": 87.28,
                    "district": "Sunsari",
                    "severity": "high",
                },
            },
            {
                "at": 50,
                "kind": "report",
                "label": "Report: vehicles stranded, no water for 6 hours",
                "payload": {
                    "message": "Gaadi ritseka, 6 ghanta bata pani chhaina. Teshro leuka",
                    "language": "ne",
                    "latitude": 26.82,
                    "longitude": 87.29,
                    "location_text": "Dharan-19 highway queue",
                    "incident_type": IncidentType.ROAD_BLOCKAGE.value,
                    "people_count": 80,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 110,
                "kind": "request",
                "label": "Help request: water for stranded passengers",
                "payload": {
                    "message": "Yatrai haru lai pani chha, 2 jna bittita, 1 garbharati",
                    "language": "ne",
                    "latitude": 26.82,
                    "longitude": 87.29,
                    "location_text": "Dharan-19 highway queue",
                    "help_types": ["water", "medical"],
                    "people_count": 80,
                    "medical_need": True,
                    "immediate_danger": True,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 170,
                "kind": "request",
                "label": "Same person pleads again (tests duplicate + escalation)",
                "payload": {
                    "message": "Ahijain pani hami lai koi aako chhaina, chito gardinus",
                    "language": "ne",
                    "latitude": 26.82,
                    "longitude": 87.29,
                    "location_text": "Dharan-19 highway queue",
                    "help_types": ["water"],
                    "people_count": 80,
                    "as_user": DEMO_REPORTER_USER,
                },
            },
            {
                "at": 230,
                "kind": "official_update",
                "label": "Second notice: landslide, not a rockfall (correlation test)",
                "payload": {
                    "kind": ObservationKind.OFFICIAL_INCIDENT.value,
                    "incident_type": IncidentType.LANDSLIDE.value,
                    "title": "Landslide at Dharan-19, one span covered",
                    "latitude": 26.815,
                    "longitude": 87.285,
                    "district": "Sunsari",
                    "affected_people": 300,
                    "severity": "high",
                },
            },
        ],
    },
}


# --------------------------------------------------------------------------- #
# Arming and clearing
# --------------------------------------------------------------------------- #
def scenario_list() -> list[dict[str, Any]]:
    out = []
    for scenario_id, scenario in SCENARIOS.items():
        steps: list[dict[str, Any]] = scenario["steps"]
        out.append(
            {
                "id": scenario_id,
                "name": scenario["name"],
                "summary": scenario["summary"],
                "districts": scenario["districts"],
                "steps": len(steps),
                "duration_seconds": max(step["at"] for step in steps),
                "kinds": sorted({step["kind"] for step in steps}),
                "synthetic": True,
            }
        )
    return out


def arm(db: Session, scenario_id: str, *, speed: float = 1.0, actor: User | None = None) -> dict[str, Any]:
    """Load a scenario and switch the system into demo mode.

    Arming always starts from an empty demo: a second arming on top of the last one's
    leftovers would replay a sequence into a situation that already contains it, and the
    correlation code would be reasoning about a rehearsal's own output.
    """
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"No such scenario '{scenario_id}'. Known: {', '.join(SCENARIOS)}")

    cleared = clear_demo_rows(db)
    db.execute(delete(DemoEvent))
    # The clock is cleared before the arm time is read: arming on top of a running
    # rehearsal would otherwise stamp the previous scenario's simulated time as the start
    # of this one, and every step would fire at once.
    set_simulated_clock(None)
    started = real_utcnow()
    for index, step in enumerate(scenario["steps"]):
        db.add(
            DemoEvent(
                scenario_id=scenario_id,
                step_index=index,
                at_offset_seconds=int(step["at"]),
                kind=str(step["kind"]),
                label=str(step.get("label", "")),
                payload=dict(step.get("payload") or {}),
            )
        )
    db.commit()

    system_state.set_system_mode(
        db,
        {
            "mode": "demo",
            "scenario_id": scenario_id,
            "sim_clock": iso(started),
            "armed_at": iso(started),
            "speed": speed,
            "armed_by": (actor.username if actor else None),
        },
    )
    audit.record(
        db,
        action=AuditAction.DEMO_INJECT,
        entity_type="system",
        entity_id="mode",
        actor=actor,
        actor_kind="operator" if actor else "system",
        previous={"mode": "live", "cleared_demo_rows": cleared},
        new={"mode": "demo", "scenario_id": scenario_id, "steps": len(scenario["steps"])},
        reason="demo scenario armed",
        commit=True,
    )
    return status(db)


def disarm(db: Session, *, actor: User | None = None) -> dict[str, Any]:
    """Back to live, and the rehearsal's rows go with it."""
    cleared = clear_demo_rows(db)
    db.execute(delete(DemoEvent))
    db.commit()
    system_state.set_system_mode(db, dict(system_state.LIVE))
    set_simulated_clock(None)
    audit.record(
        db,
        action=AuditAction.DEMO_INJECT,
        entity_type="system",
        entity_id="mode",
        actor=actor,
        actor_kind="operator" if actor else "system",
        previous={"mode": "demo"},
        new={"mode": "live", "cleared_demo_rows": cleared},
        reason="demo scenario cleared",
        commit=True,
    )
    return {"mode": "live", "cleared": cleared, **status(db)}


def clear_demo_rows(db: Session) -> dict[str, int]:
    """Delete every row whose only reason for existing is a rehearsal.

    Two things this has to get right, and SQLite enforces the first one literally:

    - Order. `db.delete()` leaves flush ordering to the unit of work, which does not
      treat `incidents` as a parent of the bare foreign key on `community_reports`:
      it emitted `DELETE FROM incidents` while a demo report still pointed at the row
      and the whole disarm transaction died on an IntegrityError. Statements built
      with `delete()` run in the order they are written, children first.
    - Scope. Only rows tagged provenance='demo' are deleted. A real report that
      happened to correlate with a scripted incident is detached (its incident_id goes
      back to NULL), never deleted - a rehearsal must not be able to eat real data.

    The arm/disarm audit entries stay: they are keyed to entity_id='system', not to a
    demo row, so the fact that a rehearsal happened remains on the record.
    """
    incident_ids = _demo_ids(db, Incident, DEMO_PROVENANCE)
    observation_ids = _demo_ids(db, Observation, DEMO_PROVENANCE)
    report_ids = _demo_ids(db, CommunityReport, DEMO_PROVENANCE)
    request_ids = _demo_ids(db, AssistanceRequest, DEMO_PROVENANCE)
    resource_ids = _demo_ids(db, Resource, resource_service.PROVENANCE_DEMO)
    # Agent runs about scripted incidents. `subject_id` is a soft reference with no foreign
    # key, so nothing would have objected when the incident went away - and an operator
    # could still open a "finding" describing a rehearsal row that no longer exists.
    investigation_ids = list(
        db.execute(
            select(AgentInvestigation.id).where(AgentInvestigation.subject_id.in_(incident_ids))
        ).scalars()
    ) if incident_ids else []

    # Real evidence that drifted into the scripted incident's radius keeps its text and
    # loses the link, so it can be re-correlated against a real incident later.
    detached = 0
    if incident_ids:
        for model in (CommunityReport, AssistanceRequest):
            result = db.execute(
                update(model)
                .where(model.incident_id.in_(incident_ids), model.provenance != DEMO_PROVENANCE)
                .values(incident_id=None)
            )
            detached += int(result.rowcount or 0)

    # Stage 1: link tables and rows that hang off a demo row. `incident_observations`
    # goes first because it is the only table with two foreign keys into this set.
    # An empty `.in_([])` compiles to a false condition, so no placeholder guards needed.
    statements: list[Any] = [
        delete(AssistanceUpdate).where(AssistanceUpdate.request_id.in_(request_ids)),
        delete(IncidentObservation).where(
            or_(
                IncidentObservation.incident_id.in_(incident_ids),
                IncidentObservation.observation_id.in_(observation_ids),
            )
        ),
        delete(Notification).where(
            or_(
                Notification.incident_id.in_(incident_ids),
                Notification.request_id.in_(request_ids),
                Notification.provenance == DEMO_PROVENANCE,
            )
        ),
        delete(AgentInvestigation).where(AgentInvestigation.id.in_(investigation_ids)),
        delete(AuditEvent).where(
            AuditEvent.entity_id.in_([*incident_ids, *observation_ids, *report_ids, *request_ids, *investigation_ids])
        ),
    ]
    for statement in statements:
        db.execute(statement)
    db.commit()

    # Stage 2: the parents, requests before reports (a request can name a report),
    # reports before incidents (they hold the only real FK), incidents last.
    deleted: dict[str, int] = {}
    for name, model, ids in (
        ("requests", AssistanceRequest, request_ids),
        ("reports", CommunityReport, report_ids),
        ("observations", Observation, observation_ids),
        ("incidents", Incident, incident_ids),
        ("resources", Resource, resource_ids),
    ):
        if not ids:
            deleted[name] = 0
            continue
        result = db.execute(delete(model).where(model.id.in_(ids)))
        deleted[name] = int(result.rowcount or 0)
        db.commit()
    deleted["detached_real_rows"] = detached
    deleted["agent_runs"] = len(investigation_ids)

    if any(deleted.values()):
        logger.info("cleared demo rows: %s", deleted)
    return deleted


def _demo_ids(db: Session, model: Any, provenance: str) -> list[str]:
    return list(db.execute(select(model.id).where(model.provenance == provenance)).scalars())


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
def _mode_clock(mode: dict[str, Any]) -> datetime:
    armed = parse_iso(mode.get("armed_at")) or real_utcnow()
    speed = float(mode.get("speed") or 1.0)
    # Real minutes are multiplied into scenario minutes; without the factor the speed the
    # operator asked for would be accepted and silently ignored.
    elapsed = (real_utcnow() - armed).total_seconds() * speed
    return armed + timedelta(seconds=max(0.0, elapsed))


def advance(db: Session, *, jump_seconds: float | None = None) -> dict[str, Any]:
    """Fire every scenario step whose time has come.

    Driven by the caller rather than a background thread: a rehearsal that only moves when
    somebody is watching is easier to reason about than one that fires into a closed laptop.
    The `/api/demo` routes that used to drive this from a browser are unmounted, so a script is
    the only caller now. `jump_seconds` puts the simulated clock forward on demand, which is
    what stepping through a scenario from a script needs.
    """
    mode = system_state.system_mode(db)
    if mode.get("mode") != "demo":
        return {"armed": False, "fired": [], "skipped_reason": "system is in live mode"}

    scenario_id = str(mode.get("scenario_id") or "")
    armed = parse_iso(mode.get("armed_at")) or real_utcnow()
    speed = float(mode.get("speed") or 1.0)
    if jump_seconds is not None:
        clock = armed + timedelta(seconds=abs(jump_seconds) * speed)
    else:
        clock = _mode_clock(mode)
    set_simulated_clock(clock)
    # Persist it too, for readers rather than for the next step - `_mode_clock()` recomputes from
    # `armed_at` - but this is the field `status()`, the agent's mode tool and /api/system/status
    # all report, and a sim_clock frozen at the arming moment next to data that has moved on would
    # be its own small lie.
    system_state.set_system_mode(db, {**mode, "sim_clock": iso(clock)})
    elapsed = (clock - armed).total_seconds()

    due = list(
        db.execute(
            select(DemoEvent)
            .where(
                DemoEvent.scenario_id == scenario_id,
                DemoEvent.fired_at.is_(None),
                DemoEvent.at_offset_seconds <= elapsed,
            )
            .order_by(DemoEvent.step_index)
        ).scalars()
    )
    operator = _user(db, str(mode.get("armed_by") or DEMO_ACTOR_USER))
    fired: list[dict[str, Any]] = []
    for event in due:
        try:
            detail = _fire(db, event, operator=operator, scenario_id=scenario_id)
            event.fired_at = clock
            db.commit()
            fired.append({"step": event.step_index, "label": event.label, "ok": True, **detail})
        except Exception as exc:  # noqa: BLE001 - one bad step must not stop the replay
            db.rollback()
            event.fired_at = clock
            event.payload = {**(event.payload or {}), "_error": f"{type(exc).__name__}: {exc}"}
            db.commit()
            fired.append(
                {"step": event.step_index, "label": event.label, "ok": False, "error": str(exc)[:300]}
            )
            logger.exception("demo step %s failed", event.step_index)
    return {
        "armed": True,
        "scenario_id": scenario_id,
        "sim_clock": iso(clock),
        "elapsed_seconds": int(elapsed),
        "fired": fired,
        "remaining": remaining(db),
    }


def remaining(db: Session) -> int:
    mode = system_state.system_mode(db)
    scenario_id = mode.get("scenario_id")
    if mode.get("mode") != "demo" or not scenario_id:
        return 0
    return int(
        db.execute(
            select(func.count(DemoEvent.id)).where(
                DemoEvent.scenario_id == scenario_id, DemoEvent.fired_at.is_(None)
            )
        ).scalar()
        or 0
    )


def _user(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def _fire(
    db: Session, event: DemoEvent, *, operator: User | None, scenario_id: str
) -> dict[str, Any]:
    payload = dict(event.payload or {})
    if event.kind in ("official_update", "observation", "signal"):
        if event.kind == "signal":
            signal_service.rebuild_signals(db)
            return {"action": "rebuilt risk signals"}
        return _fire_observation(db, event, payload, scenario_id=scenario_id)
    if event.kind == "report":
        return _fire_report(db, event, payload, scenario_id=scenario_id, needs_help=False)
    if event.kind == "request":
        return _fire_report(db, event, payload, scenario_id=scenario_id, needs_help=True)
    if event.kind == "status":
        return _fire_status(db, event, payload, operator=operator)
    return {"action": "unsupported step kind", "ok": False, "error": event.kind}


def _fire_observation(
    db: Session, event: DemoEvent, payload: dict[str, Any], *, scenario_id: str
) -> dict[str, Any]:
    record = NormalizedObservation(
        source_code="demo",
        external_id=f"{scenario_id}-{event.step_index}",
        kind=ObservationKind(payload.get("kind") or ObservationKind.OFFICIAL_INCIDENT.value),
        title=payload.get("title", "") or event.label,
        summary=payload.get("summary", ""),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        location_name=payload.get("location_text"),
        district=payload.get("district"),
        within_nepal=True,
        incident_type=IncidentType(payload["incident_type"]) if payload.get("incident_type") else None,
        event_time=utcnow() - timedelta(minutes=int(payload.get("minutes_ago") or 5)),
        severity=payload.get("severity"),
        magnitude=payload.get("magnitude"),
        depth_km=payload.get("depth_km"),
        value=payload.get("value"),
        unit=payload.get("unit"),
        threshold_state=payload.get("threshold_state"),
        trend=payload.get("trend"),
        subtype="demo_scenario",
        deaths=int(payload.get("deaths") or 0),
        injured=int(payload.get("injured") or 0),
        affected_people=int(payload.get("affected_people") or 0),
        houses_damaged=int(payload.get("houses_damaged") or 0),
        provenance=DEMO_PROVENANCE,
        normalized_data={"scenario_id": scenario_id, "step": event.step_index},
    )
    _created, _updated, rows = ingestion.upsert_observations(db, [record])
    db.commit()
    touched = ingestion.absorb(db, rows)
    db.commit()
    incident = incident_service.absorb_observation(db, rows[0]) if rows else None
    if incident is not None:
        # The absorb path deliberately does not set provenance on an incident it creates
        # for a source it has never seen before; a demo incident must be tagged here or it
        # would survive into live mode as an apparent fact.
        incident.provenance = DEMO_PROVENANCE
        db.commit()
    return {
        "action": "observation absorbed",
        "observations": len(rows),
        "incidents_touched": touched,
        "incident_ref": incident.ref_code if incident else None,
    }


def _fire_report(
    db: Session,
    event: DemoEvent,
    payload: dict[str, Any],
    *,
    scenario_id: str,
    needs_help: bool,
) -> dict[str, Any]:
    reporter = _user(db, str(payload.get("as_user") or DEMO_REPORTER_USER))
    _report, incident, request = community_service.submit_report(
        db,
        user=reporter,
        message=str(payload.get("message") or event.label),
        report_type=str(payload.get("report_type") or "incident"),
        incident_type=payload.get("incident_type"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        location_text=payload.get("location_text"),
        people_count=payload.get("people_count"),
        medical_need=bool(payload.get("medical_need")),
        language=str(payload.get("language") or "ne"),
        needs_help=needs_help,
        help_types=list(payload.get("help_types") or []),
        immediate_danger=bool(payload.get("immediate_danger")),
        provenance=DEMO_PROVENANCE,
        demo_scenario_id=scenario_id,
    )
    db.commit()
    return {
        "action": "request opened" if request is not None else "report filed",
        "incident_ref": incident.ref_code if incident else None,
        "request_ref": request.ref_code if request else None,
        "urgency": request.urgency if request else None,
    }


def _fire_status(
    db: Session, event: DemoEvent, payload: dict[str, Any], *, operator: User | None
) -> dict[str, Any]:
    target = str(payload.get("target") or AssistanceStatus.IN_PROGRESS.value)
    request = db.execute(
        select(AssistanceRequest)
        .where(AssistanceRequest.provenance == DEMO_PROVENANCE)
        .order_by(AssistanceRequest.created_at.desc())
    ).scalars().first()
    if request is None:
        return {"action": "no demo request to update", "ok": False}
    if operator is None:
        return {"action": "no demo operator on file", "ok": False}
    assistance.change_status(db, request, operator, target, note=str(payload.get("note", "")))
    db.commit()
    plan = assistance.refresh_plan(db, request)
    return {
        "action": "status advanced",
        "request_ref": request.ref_code,
        "status": plan.status,
        "matched_resources": len(plan.matched_resource_ids or []),
    }


# --------------------------------------------------------------------------- #
# What the surface shows
# --------------------------------------------------------------------------- #
def status(db: Session) -> dict[str, Any]:
    mode = system_state.system_mode(db)
    scenario_id = mode.get("scenario_id")
    scenario = SCENARIOS.get(str(scenario_id or ""))
    steps = list(
        db.execute(
            select(DemoEvent).where(DemoEvent.scenario_id == scenario_id).order_by(DemoEvent.step_index)
        ).scalars()
    ) if scenario_id else []
    fired = [event for event in steps if event.fired_at is not None]
    return {
        "mode": mode.get("mode", "live"),
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"] if scenario else None,
        "armed_at": mode.get("armed_at"),
        "speed": mode.get("speed"),
        "sim_clock": mode.get("sim_clock"),
        "steps_total": len(steps),
        "steps_fired": len(fired),
        "remaining": len(steps) - len(fired),
        "next_step": next(({"step": e.step_index, "label": e.label, "at": e.at_offset_seconds}
                           for e in steps if e.fired_at is None), None),
        "timeline": [
            {
                "step": event.step_index,
                "at": event.at_offset_seconds,
                "kind": event.kind,
                "label": event.label,
                "fired": event.fired_at is not None,
                "error": (event.payload or {}).get("_error"),
            }
            for event in steps
        ],
        # Demo rows are counted separately so an operator can never mistake the size of a
        # rehearsal for the size of the disaster.
        "demo_rows": {
            "incidents": _count(db, Incident, DEMO_PROVENANCE),
            "reports": _count(db, CommunityReport, DEMO_PROVENANCE),
            "requests": _count(db, AssistanceRequest, DEMO_PROVENANCE),
        },
        "warning": (
            "Demo mode is on. Everything labelled demo is scripted, including times and "
            "casualty figures. Facilities shown are real."
            if mode.get("mode") == "demo"
            else None
        ),
    }


def _count(db: Session, model: Any, provenance: str) -> int:
    return int(
        db.execute(select(func.count(model.id)).where(model.provenance == provenance)).scalar() or 0
    )
