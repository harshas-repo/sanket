"""What one victim report may be answered with.

`agent/tools/read.py` holds the read-only investigation set and its rule is "nothing here
writes". This file is the deliberate exception: a report about a person who needs help is
only worth anything if it can become a case. So the write tools exist - and every one of
them is a thin wrapper over the same service function the Response Center screen calls,
which is what keeps the agent's power equal to a named operator's and no larger.

Three rules, all enforced here rather than in a prompt:

1. **The model never supplies an input to a deterministic function.** It cannot pass a
   coordinate (a place phrase is geocoded by `resolve_location`), it cannot pass a primary
   key (`incident_ref` is looked up or the call is refused), it cannot pass whose report
   this is (the victim and the operator are closed over at build time), and it cannot pass
   the description (it is the report's own words, verbatim).
2. **Nothing that feeds the priority score is accepted on the model's word.** A risk flag
   is true only when the report text supports it; the quote the model must supply is
   checked against the text character for character.
3. **No lifecycle moves.** `update_assistance_request` appends an internal note. The
   statuses in `AssistanceStatus` belong to humans, and the transition table is enforced in
   the service - the agent is not given a way to reach it.

Every tool ends in `record_action`, which records the action in the activity trace and adds the
payload to the evidence corpus the number guardrail checks the final answer against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from strands import tool

from backend.app.geo.boundaries import normalize_district
from backend.app.models.core import (
    AssistanceRequest,
    CommunityReport,
    Incident,
    Observation,
    Resource,
    User,
)
from backend.app.scoring import urgency as urgency_mod
from backend.app.services import assistance as assistance_service
from backend.app.services import audit as audit_service
from backend.app.services import community as community_service
from backend.app.services import notifications as notification_service
from backend.app.services import response_center as rc_service
from shared.enums import AssistanceType, ObservationKind, Urgency
from shared.geo import haversine_km
from shared.nepal_places import resolve_place
from shared.timeutils import humanize_age, iso, utcnow

MEDICAL_KINDS = ("hospital", "health_post", "ambulance")
SHELTER_KINDS = ("shelter", "camp")
RELIEF_KINDS = ("food_distribution", "water_supply", "camp")

# Words that make a risk flag true. This is not a model standing in for a model: it is the
# same kind of table `_text_signals` in the scoring module already uses to decide urgency,
# applied one step earlier to decide which words count as evidence.
_FLAG_WORDS: dict[str, tuple[str, ...]] = {
    "medical_need": (
        "injur", "bleed", "wound", "unconscious", "not breathing", "medical", "hospital",
        "fractur", "can't move", "cannot move", "pain", "sick", "bleeding",
    ),
    "trapped": (
        "trapped", "stuck", "buried", "can't get out", "cannot get out", "couldn't get out",
        "no way out", "under the rubble", "collapsed on", "surrounded",
    ),
    "immediate_danger": (
        "collaps", "about to fall", "aftershock", "fire", "flood", "water rising",
        "landslide", "avalanche", "earthquake", "gas leak", "explosion", "still shaking",
        "danger", "dying",
    ),
    "minors_involved": (
        "child", "children", "kid", "baby", "infant", "son", "daughter", "minor", "school",
        "student",
    ),
    "elderly_or_disabled_involved": (
        "elderly", "grandparent", "grandmother", "grandfather", "wheelchair", "disabled",
        "difficulty walking", "can't walk", "cannot walk", "bedridden", "old mother",
        "old father",
    ),
}

_TYPE_WORDS: dict[str, tuple[str, ...]] = {
    AssistanceType.MEDICAL.value: _FLAG_WORDS["medical_need"] + ("ambulance",),
    AssistanceType.RESCUE.value: _FLAG_WORDS["trapped"] + ("rescue", "save us", "rubble"),
    AssistanceType.FOOD.value: ("food", "hungry", "eat", "meal", "cooking"),
    AssistanceType.WATER.value: ("water", "thirsty", "drinking"),
    AssistanceType.SHELTER.value: ("shelter", "tent", "homeless", "no home", "roofless", "cold", "open air"),
    AssistanceType.TRANSPORT.value: (
        "road", "blocked road", "bridge", "transport", "evacuate", "evacuation", "vehicle",
    ),
    AssistanceType.INFORMATION.value: ("information", "what happened", "is it safe"),
}

_NO_PERMISSION = {
    "error": "not_permitted",
    "detail": "The person running this investigation is not allowed to do that.",
}


@dataclass
class ResponderContext:
    """Everything a tool is allowed to know about this run.

    Built by the workflow and handed to `build_respond_tools`, so the identity of the
    victim and the operator are fixed before the model is ever asked a question.
    """

    db: Any
    permissions: set[str] | None = None
    report_text: str = ""
    victim: User | None = None
    operator: User | None = None
    report_id: str | None = None
    incident_id: str | None = None
    language: str = "en"
    trace: Any = None
    # Every payload this run returned, for the number guardrail, and the reference codes it
    # wrote, so the run can be judged on what it actually produced.
    evidence: list[str] = field(default_factory=list)
    created_refs: list[str] = field(default_factory=list)
    _location: dict[str, Any] | None = None

    def allowed(self, permission: str) -> bool:
        return self.permissions is None or permission in self.permissions

    def location(self, place: str = "") -> dict[str, Any]:
        """Coordinates for this run, resolved by code from words.

        With a phrase, geocode that phrase; without one, fall back to the phrase resolved
        at the start of the run (the report's own words). A model is never trusted with a
        latitude, so no tool here takes one.
        """
        if place:
            resolved = assistance_service.resolve_location(
                self.db, location_text=place, user=self.victim
            )
            resolved["method"] = "geocoded_from_call"
            resolved["phrase"] = place
            return resolved
        if self._location is None:
            # Geocode the place the report names, not the whole report: a sentence passed to
            # the gazetteer comes back with the sentence attached as its own location text,
            # and an operator should see "Melamchi" where the place is, not the plea.
            match = resolve_place(self.report_text)
            self._location = assistance_service.resolve_location(
                self.db,
                location_text=match.name if match else (self.report_text[:250] or None),
                user=self.victim,
            )
            self._location["method"] = "geocoded_from_report"
        return self._location


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def record_action(
    ctx: ResponderContext,
    action: str,
    payload: dict[str, Any],
    *,
    detail: str,
    status: str = "ok",
    asked: dict[str, Any] | None = None,
) -> str:
    """Record, keep as evidence, answer. The one way out of every tool."""
    if ctx.trace is not None:
        ctx.trace.tool(action, status=status, detail=detail, asked=asked)
    body = _dump(payload)
    ctx.evidence.append(body)
    return body


def _status_for(count: int) -> str:
    return "ok" if count else "empty"


def _district(value: str) -> str | None:
    return (normalize_district(value) or value.strip() or None) if value else None


def _since(hours: int) -> Any:
    return utcnow() - timedelta(hours=min(max(hours, 1), 24 * 30))


def _point_of(location: dict[str, Any]) -> tuple[float, float] | None:
    if location.get("latitude") is None or location.get("longitude") is None:
        return None
    return (float(location["latitude"]), float(location["longitude"]))


def _distance_note(location: dict[str, Any]) -> str:
    """How the tools describe their own location, so 'nearest' never claims more than the
    geocoder actually established."""
    if location.get("latitude") is None:
        return "no coordinate could be resolved from the words given, so distances are not claimed"
    return (
        f"distances are straight-line from {location.get('location_text') or 'the resolved place'} "
        f"(location confidence {location.get('location_confidence', 'unknown')}, district "
        f"{location.get('district') or 'unnamed'})"
    )


def _observation_rows(
    db: Any,
    kind: str,
    *,
    district: str | None,
    since: Any,
    limit: int,
    center: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Newest rows of one kind, with age computed here and never by the model."""
    stmt = (
        select(Observation)
        .where(Observation.kind == kind, Observation.received_at >= since)
        .order_by(Observation.event_time.desc())
        .limit(min(max(limit, 1), 50))
    )
    if district:
        stmt = stmt.where(Observation.district.ilike(district))  # noqa: E711
    rows: list[dict[str, Any]] = []
    for row in db.execute(stmt).scalars():
        distance = None
        if center and row.latitude is not None:
            km = haversine_km(center, (row.latitude, row.longitude))
            distance = None if km is None else round(km, 1)
        rows.append(
            {
                "title": row.title,
                "value": row.value,
                "unit": row.unit,
                "threshold_state": row.threshold_state,
                "trend": row.trend,
                "magnitude": row.magnitude,
                "depth_km": row.depth_km,
                "severity": row.severity,
                "district": row.district,
                "location_name": row.location_name,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "distance_km": distance,
                "at": iso(row.event_time),
                "age": humanize_age(row.event_time),
                "source": row.source_id,
                "source_name": getattr(row.source, "name", None),
                "provenance": row.provenance,
                "official": row.provenance == "official",
                "url": row.source_url,
            }
        )
    return rows


def _nearest_resources(
    db: Any,
    kinds: tuple[str, ...],
    *,
    center: tuple[float, float] | None,
    district: str | None,
    within_km: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Facilities of the asked-for kinds, ordered by computed distance.

    The same columns and the same haversine the dispatcher uses, because an agent that
    answered "the nearest hospital is 40 km away" from a different calculation than the
    screen shows would be the first thing an operator had to disbelieve.
    """
    stmt = select(Resource).where(
        Resource.active.is_(True), Resource.resource_type.in_(list(kinds))
    )
    if district:
        stmt = stmt.where(Resource.district.ilike(district))  # noqa: E711
    scored: list[tuple[float, Resource]] = []
    for row in db.execute(stmt).scalars():
        if center and row.latitude is not None:
            km = haversine_km(center, (row.latitude, row.longitude))
            if km is None:
                continue
            if km > within_km:
                continue
            scored.append((km, row))
    scored.sort(key=lambda item: item[0])
    out: list[dict[str, Any]] = []
    for km, row in scored[: min(max(limit, 1), 20)]:
        out.append(
            {
                "name": row.name,
                "resource_type": row.resource_type,
                "district": row.district,
                "address": row.address,
                "contact": row.contact,
                "contact_verified": row.contact_verified,
                "availability": row.availability,
                "capacity": row.capacity,
                "distance_km": round(km, 1),
                "source": row.source,
                "provenance": row.provenance,
                "availability_verified_at": iso(row.availability_verified_at),
                "availability_age": humanize_age(row.availability_verified_at),
            }
        )
    return out


def _read_flags(text: str) -> dict[str, bool]:
    lowered = (text or "").lower()
    return {
        flag: any(word in lowered for word in words) for flag, words in _FLAG_WORDS.items()
    }


def _read_types(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [
        key
        for key, words in _TYPE_WORDS.items()
        if key != AssistanceType.INFORMATION.value and any(word in lowered for word in words)
    ]


def _grounded_quote(quote: str, report: str) -> bool:
    """Is this the report's own wording? Whitespace and case are ignored; nothing else is."""
    wanted = " ".join((quote or "").split()).casefold()
    if len(wanted) < 4:
        return False
    return wanted in " ".join((report or "").split()).casefold()


def _keyword_backed(flag: str, quote: str, report: str) -> bool:
    """True when the quote itself contains the words that make this flag real."""
    if not _grounded_quote(quote, report):
        return False
    quoted = " ".join((quote or "").split()).casefold()
    return any(word in quoted for word in _FLAG_WORDS.get(flag, ()))


def _ref_matches(column: Any, ref_code: str) -> Any:
    """A `WHERE` clause that finds a reference code however the caller typed it.

    `new_ref_code` ends in four lowercase hex characters, and a model - like an operator reading a
    screen and typing what they see - may hand one back in either case. Uppercasing the value and
    comparing it against an exact column match finds nothing except the roughly one code in seven
    whose suffix happens to be all digits, so `update_assistance_request` and `send_victim_update`
    answered `not_found` about a case their own reply had just named. Case is folded on both sides
    here; the code still has to be complete, so folding it cannot turn a wrong reference into a
    plausible one.
    """
    return func.upper(column) == (ref_code or "").strip().upper()


def _request_by_ref(ctx: ResponderContext, ref_code: str) -> AssistanceRequest | None:
    if not (ref_code or "").strip():
        return None
    return ctx.db.execute(
        select(AssistanceRequest).where(_ref_matches(AssistanceRequest.ref_code, ref_code))
    ).scalars().first()


def _incident_by_ref(db: Any, ref: str) -> Incident | None:
    if not (ref or "").strip():
        return None
    return db.execute(
        select(Incident).where(_ref_matches(Incident.ref_code, ref))
    ).scalars().first()


def preliminary_reading(text: str) -> dict[str, Any]:
    """What the fixed rules already understand about a report, before anyone asks a model.

    The workflow records this as its own timeline step, because it is genuinely the first
    half of understanding - and on a run with no model reachable, it is all there is, so it
    has to be enough to file the case from.
    """
    flags = _read_flags(text)
    return {
        "risk_flags": {name: value for name, value in flags.items() if value},
        "help_types": _read_types(text),
        "words": len((text or "").split()),
        "method": "keyword_rules",
    }


def _flag_state(report: str, proposed: dict[str, bool]) -> tuple[dict[str, bool], list[str], list[str]]:
    """Which risk flags are true, decided from the report's own words.

    The model's proposal is compared, never believed: a flag the words carry stands even if
    the model missed it (missing 'trapped' is the worst failure available here), and a flag
    the words do not carry is refused even if the model asserted it. Both disagreements are
    returned as names so the run can show them instead of hiding them.
    """
    supported = _read_flags(report)
    missed = [name for name, value in supported.items() if value and not proposed.get(name)]
    overreached = [name for name, value in proposed.items() if value and not supported.get(name)]
    return supported, missed, overreached


def _type_state(
    report: str, claimed: list[str], quote_ok: bool
) -> tuple[list[str], list[str], list[str]]:
    """Which kinds of help the request is for.

    A type is an urgency input, so it needs grounding too - but the phrase that proves it is
    not always a keyword ('come pull us out' is a rescue request my table will not see). The
    way through is the quote: a proposed type stands when the model pointed at words that
    are really in the report, because then the claim is at least traceable to the reporter.
    Without a verbatim quote the table alone decides.
    """
    grounded = _read_types(report)
    accepted = list(grounded)
    from_quote: list[str] = []
    for value in claimed:
        if value not in accepted and quote_ok and value != AssistanceType.INFORMATION.value:
            accepted.append(value)
            from_quote.append(value)
    dropped = [value for value in claimed if value not in accepted]
    return (accepted or grounded[:1] or [AssistanceType.OTHER.value]), dropped, from_quote


def file_request(ctx: ResponderContext, proposal: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Ground a report, then write the case. Returns the payload and its one-line digest.

    Public and separate from the tool because the same code has to run when no model is
    reachable: a report that cannot wait for a provider is filed by these rules with the
    model's proposal empty, and the only thing that changes is who read the words.
    """
    report = ctx.report_text
    quote = str(proposal.get("evidence_quote") or "")
    quote_ok = _grounded_quote(quote, report)
    claimed_flags = {
        name: bool(proposal.get(name))
        for name in (
            "medical_need",
            "immediate_danger",
            "trapped",
            "minors_involved",
            "elderly_or_disabled_involved",
        )
    }
    flags, missed, overreached = _flag_state(report, claimed_flags)
    claimed_types = [
        str(value)
        for value in [proposal.get("request_type"), *(proposal.get("assistance_types") or [])]
        if value
    ]
    types, dropped_types, types_from_quote = _type_state(report, claimed_types, quote_ok)

    location = ctx.location(str(proposal.get("location_text") or ""))
    proposal_ref = str(proposal.get("incident_ref") or "").strip()
    incident = _incident_by_ref(ctx.db, proposal_ref)
    people_count = max(1, min(int(proposal.get("people_count") or 1), 999))

    # The rules run here first and again inside `create()` on identical inputs - a pure
    # function, so two calls cannot disagree. It buys a timeline where the priority decision
    # is its own step, at its own moment, with the reason the rules gave.
    preview_urgency, preview_reasons = urgency_mod.classify_request(
        assistance_types=types,
        medical_need=flags["medical_need"],
        immediate_danger=flags["immediate_danger"],
        people_count=people_count,
        trapped=flags["trapped"],
        description=report,
        incident_type=incident.incident_type if incident else None,
        location_known=location.get("location_confidence") in {"high", "medium"},
        minors_involved=flags["minors_involved"],
        elderly_or_disabled_involved=flags["elderly_or_disabled_involved"],
    )
    if ctx.trace is not None:
        ctx.trace.phase(
            "evaluating_priority",
            detail=f"{preview_urgency.value} by fixed rules: "
            + ("; ".join(preview_reasons[:2]) or "no rule matched"),
        )

    # No coordinates are handed to `create()` even though the gazetteer has them, and the reason
    # is the confidence. `resolve_location` treats a lat/lng as a shared pin and reverse-looks-up
    # the district polygon, which reports "high"; the caller shared the words "near Melamchi".
    # Passing the words keeps one resolution, in the branch that matches how the place was
    # actually learned, and it still stores the gazetteer's coordinate.
    request = assistance_service.create(
        ctx.db,
        user=ctx.victim,
        description=report,
        request_type=types[0],
        assistance_types=types,
        latitude=None,
        longitude=None,
        location_text=location.get("location_text") or report[:250],
        people_count=people_count,
        medical_need=flags["medical_need"],
        immediate_danger=flags["immediate_danger"],
        trapped=flags["trapped"],
        minors_involved=flags["minors_involved"],
        elderly_or_disabled_involved=flags["elderly_or_disabled_involved"],
        incident_id=incident.id if incident else ctx.incident_id,
        report_id=ctx.report_id,
        language=ctx.language,
        structured={
            "filed_by": "agent",
            # Which of the two routes wrote this case: the model called the filing tool, or the
            # fixed rules filed it because the report's own words asked for help and no case
            # existed. "An agent filed this" without saying which part of the agent did it is a
            # record nobody can audit, and the two routes are not equivalent - only one of them
            # read a sentence the reporter wrote.
            "filing_route": "model_called_the_tool" if proposal else "deterministic_rules",
            "agent_proposed_flags": {k: v for k, v in claimed_flags.items() if v},
            "flags_model_missed": missed,
            "flags_model_overreached": overreached,
            "agent_proposed_types": claimed_types,
            "types_from_verified_quote": types_from_quote,
            "dropped_ungrounded_types": dropped_types,
            "evidence_quote_verified": quote_ok,
            "urgency_decided_by": "deterministic rules over the report's own words",
        },
    )
    if ctx.trace is not None:
        ctx.trace.phase(
            "creating_assistance_request", detail=f"{request.ref_code} filed at {request.urgency}"
        )
    ctx.created_refs.append(request.ref_code)
    matched = request.matched_resource_ids or []
    sla_minutes = None
    if request.sla_due_at is not None:
        sla_minutes = int(max(0, (request.sla_due_at - utcnow()).total_seconds() // 60))
    payload = {
        "created": True,
        "ref_code": request.ref_code,
        "status": request.status,
        "urgency": request.urgency,
        "urgency_reasons": request.urgency_reasons,
        "request_type": request.request_type,
        "assistance_types": request.assistance_types,
        "district": request.district,
        "location_confidence": request.location_confidence,
        "matched_resources": len(matched),
        "sla_minutes": sla_minutes,
        "flags_used": flags,
        "flags_the_model_missed": missed,
        "flags_the_model_overreached": overreached,
        "types_dropped_as_unsupported": dropped_types,
        "evidence_quote_verified": quote_ok,
        "description_stored": "the reporter's own words, unchanged",
        # Unlike a notice, a filing is never refused over a bad reference: the case is the thing
        # a person in danger needs, and dropping it to be tidy about a link would trade a real
        # harm for a small one. What it does get is an honest reply, so the run that meant to
        # attach an incident learns that it did not, here, rather than from an empty field later.
        **(
            {
                "incident_not_attached": proposal_ref,
                "detail": f"No tracked incident {proposal_ref!r}, so the case was filed unlinked.",
            }
            if proposal_ref and incident is None
            else {}
        ),
        "note": (
            "urgency, matched facilities, the response plan and the Response Center "
            "notification were computed by code from these fields; this response reports them "
            "and sets none of them"
        ),
    }
    detail = (
        f"{request.ref_code} filed at {request.urgency.upper()} "
        f"({'; '.join(request.urgency_reasons[:1]) or 'no rule matched'}), "
        f"{len(matched)} facility(s) matched"
    )
    return payload, detail


# --------------------------------------------------------------------------- #
def build_respond_tools(ctx: ResponderContext) -> list[Any]:
    """The fifteen tools, bound to one report, one victim and one operator."""
    db = ctx.db

    def refused(permission: str) -> str:
        return _dump(
            {
                **_NO_PERMISSION,
                "detail": f"This run was started by someone without '{permission}'.",
            }
        )

    # ------------------------------------------------------------------ hazard picture
    @tool
    def get_recent_earthquakes(
        district: str = "",
        since_hours: int = 72,
        within_km: int = 0,
        limit: int = 10,
    ) -> str:
        """Earthquakes in the window, newest first, from the official feeds. Distances are
        computed from the report's own location, which this tool geocodes - it takes no
        coordinates. Use it when the report mentions shaking, a quake or a collapse."""
        location = ctx.location()
        center = _point_of(location)
        cutoff = _since(since_hours)
        rows = _observation_rows(
            db,
            ObservationKind.EARTHQUAKE.value,
            district=_district(district),
            since=cutoff,
            limit=limit,
            center=center,
        )
        if within_km and center:
            rows = [row for row in rows if (row["distance_km"] or 1e9) <= within_km]
        largest = max((row for row in rows if row.get("magnitude") is not None),
                      key=lambda row: row["magnitude"], default=None)
        detail = (
            f"{len(rows)} quake(s)"
            + (
                f", largest M{largest['magnitude']} {largest['location_name'] or largest['district'] or ''}".rstrip()
                + f" ({largest['age'] or 'time unknown'})"
                if largest
                else ""
            )
        )
        return record_action(
            ctx,
            "get_recent_earthquakes",
            {
                "count": len(rows),
                "items": rows,
                "since_hours": min(max(since_hours, 1), 24 * 30),
                "location": _distance_note(location),
                "note": "magnitude and depth are as published by the source; nothing here is scaled or converted",
            },
            detail=detail,
            status=_status_for(len(rows)),
            asked={"district": district, "since_hours": since_hours, "within_km": within_km},
        )

    @tool
    def get_official_disaster_incidents(
        district: str = "",
        incident_type: str = "",
        urgency: str = "",
        limit: int = 10,
    ) -> str:
        """Incidents the Response Center is tracking that an official body has standing
        behind. This is the only route to an 'official' statement - if a situation is not
        here, say it is unconfirmed rather than describing it as official."""
        if not ctx.allowed("incidents:read"):
            return refused("incidents:read")
        rows = rc_service.list_incidents(
            db,
            incident_type=incident_type or None,
            district=_district(district) or None,
            urgency=urgency or None,
            limit=min(max(limit, 1), 30),
        )
        official = [row for row in rows if row.official_confirmation or row.provenance == "official"]
        items = [rc_service.incident_summary(db, row) for row in official]
        return record_action(
            ctx,
            "get_official_disaster_incidents",
            {
                "count": len(items),
                "items": items,
                "checked": len(rows),
                "note": (
                    "Only incidents carrying an official confirmation or an official source "
                    f"record are listed; {len(rows) - len(items)} tracked incident(s) had none."
                ),
            },
            detail=f"{len(items)} of {len(rows)} tracked incident(s) are officially confirmed",
            status=_status_for(len(items)),
            asked={"district": district, "incident_type": incident_type, "urgency": urgency},
        )

    @tool
    def get_river_status(district: str = "", station: str = "", limit: int = 10) -> str:
        """River gauge readings from the official hydrology feed: level, unit, the source's
        own threshold state and how old the reading is. Returns what is stored, so an empty
        count means no gauge reported - not that the river is fine."""
        rows = _observation_rows(
            db,
            ObservationKind.RIVER_LEVEL.value,
            district=_district(district),
            since=_since(24 * 7),
            limit=limit,
            center=_point_of(ctx.location()),
        )
        if station:
            wanted = station.lower()
            rows = [row for row in rows if wanted in (row.get("location_name") or "").lower()]
        highest = max((row for row in rows if row.get("value") is not None),
                      key=lambda row: row["value"], default=None)
        alarms = [row for row in rows if (row.get("threshold_state") or "") in {"warning", "danger"}]
        return record_action(
            ctx,
            "get_river_status",
            {
                "count": len(rows),
                "items": rows,
                "above_threshold": len(alarms),
                "note": "threshold_state comes from the publishing agency's own levels; Sanket does not set them",
            },
            detail=(
                f"{len(rows)} gauge reading(s)"
                + (f", highest {highest['value']}{highest['unit'] or ''}" if highest else "")
                + (f", {len(alarms)} at warning or danger" if alarms else "")
            ),
            status=_status_for(len(rows)),
            asked={"district": district, "station": station},
        )

    @tool
    def get_rainfall_status(district: str = "", since_hours: int = 24, limit: int = 12) -> str:
        """Rainfall readings in the window per station, newest first. The millimetre figures
        and their bands are the meteorological service's, not Sanket's judgement."""
        rows = _observation_rows(
            db,
            ObservationKind.RAINFALL.value,
            district=_district(district),
            since=_since(since_hours),
            limit=limit,
            center=_point_of(ctx.location()),
        )
        wettest = max((row for row in rows if row.get("value") is not None),
                      key=lambda row: row["value"], default=None)
        return record_action(
            ctx,
            "get_rainfall_status",
            {
                "count": len(rows),
                "items": rows,
                "window_hours": min(max(since_hours, 1), 24 * 7),
                "note": "readings are what stations reported; an empty count means no reading was received",
            },
            detail=(
                f"{len(rows)} reading(s) in {min(max(since_hours, 1), 24 * 7)} h"
                + (f", wettest {wettest['value']}{wettest['unit'] or ' mm'}" if wettest else "")
            ),
            status=_status_for(len(rows)),
            asked={"district": district, "since_hours": since_hours},
        )

    @tool
    def get_road_status(district: str = "", limit: int = 10) -> str:
        """What the official feeds say about roads and bridges. Nepal publishes no
        machine-readable road-status feed, so this is notice text and metadata: read it as
        'a bulletin mentioned this', never as a confirmed open or closed state."""
        rows = _observation_rows(
            db,
            ObservationKind.ROAD_STATUS.value,
            district=_district(district),
            since=_since(24 * 30),
            limit=limit,
            center=_point_of(ctx.location()),
        )
        return record_action(
            ctx,
            "get_road_status",
            {
                "count": len(rows),
                "items": rows,
                "structured_road_state_available": False,
                "note": (
                    "Sanket holds no live road-status feed. A report that a road is blocked is "
                    "evidence from the caller, and stays attributed to them - do not present it "
                    "as confirmed by an authority."
                ),
            },
            detail=(
                f"{len(rows)} road notice(s) on record"
                + ("" if rows else " - no official road-status source exists to confirm the caller's")
            ),
            status=_status_for(len(rows)),
            asked={"district": district},
        )

    # ------------------------------------------------------------------ what others saw
    @tool
    def get_community_reports(district: str = "", incident_type: str = "", limit: int = 12) -> str:
        """What residents have reported, newest first, each with its own verification state.
        These are people's words, not confirmed facts - a report being numerous does not make
        it true."""
        if not ctx.allowed("reports:read"):
            return refused("reports:read")
        rows = community_service.recent_reports(
            db, district=_district(district), limit=min(max(limit, 1), 40)
        )
        items = [community_service.report_to_dict(db, row) for row in rows]
        if incident_type:
            items = [row for row in items if row.get("incident_type") == incident_type]
        return record_action(
            ctx,
            "get_community_reports",
            {
                "count": len(items),
                "items": items,
                "note": "verification_status 'pending' means no operator has checked it yet",
            },
            detail=f"{len(items)} community report(s)"
            + (f" in {district}" if district else ""),
            status=_status_for(len(items)),
            asked={"district": district, "incident_type": incident_type},
        )

    @tool
    def find_related_reports(
        location_text: str = "",
        district: str = "",
        within_km: int = 25,
        since_hours: int = 72,
        limit: int = 10,
    ) -> str:
        """Reports near the situation, with a correlation score for each. The score is
        computed from distance, time, hazard type and wording by the same deterministic
        matcher the platform uses to group reports - this tool does not decide what counts
        as related, and neither do you."""
        if not ctx.allowed("reports:read"):
            return refused("reports:read")
        from backend.app.geo.correlation import Correlatable, pair_score

        location = ctx.location(location_text)
        center = _point_of(location)
        cutoff = utcnow() - timedelta(hours=min(max(since_hours, 1), 24 * 14))
        anchor = Correlatable(
            id="report",
            kind="report",
            latitude=(center[0] if center else None),
            longitude=(center[1] if center else None),
            moment=cutoff,
            district=location.get("district"),
            text=ctx.report_text,
            incident_type=(_read_types(ctx.report_text) or [""])[0] or None,
        )
        stmt = select(CommunityReport).where(CommunityReport.created_at >= cutoff)
        if district:
            stmt = stmt.where(CommunityReport.district.ilike(district))  # noqa: E711
        stmt = stmt.order_by(CommunityReport.created_at.desc()).limit(120)
        radius = min(max(within_km, 1), 100)
        items: list[dict[str, Any]] = []
        for row in db.execute(stmt).scalars():
            if row.id == ctx.report_id:
                continue
            candidate = Correlatable(
                id=row.id,
                kind="report",
                incident_type=row.incident_type,
                latitude=row.latitude,
                longitude=row.longitude,
                moment=row.created_at,
                district=row.district,
                municipality=row.location_text,
                text=row.message,
            )
            score, components = pair_score(anchor, candidate)
            km = (
                haversine_km(center, (row.latitude, row.longitude))
                if center and row.latitude is not None
                else None
            )
            if km is not None and km > radius:
                continue
            items.append(
                {
                    "report_id": row.id,
                    "message": (row.message or "")[:300],
                    "district": row.district,
                    "location_text": row.location_text,
                    "incident_type": row.incident_type,
                    "urgency": row.urgency,
                    "verification_status": row.verification_status,
                    "distance_km": None if km is None else round(km, 1),
                    "age": humanize_age(row.created_at),
                    "correlation": round(score, 2),
                    "correlation_basis": components,
                }
            )
        items.sort(key=lambda row: (-row["correlation"], row["distance_km"] if row["distance_km"] is not None else 1e9))
        items = items[: min(max(limit, 1), 20)]
        close = [row for row in items if (row["distance_km"] or 1e9) <= radius]
        return record_action(
            ctx,
            "find_related_reports",
            {
                "count": len(items),
                "items": items,
                "radius_km": radius,
                "location": _distance_note(location),
                "note": "correlation is a deterministic 0-1 match score, not a claim that two reports are the same event",
            },
            detail=f"{len(items)} nearby report(s), {len(close)} within {radius} km of the stated place"
            if items
            else "no other report in the window and radius",
            status=_status_for(len(items)),
            asked={"district": district, "within_km": radius, "since_hours": since_hours},
        )

    # ------------------------------------------------------------------ resources
    @tool
    def find_nearby_shelters(
        location_text: str = "", district: str = "", within_km: int = 50, limit: int = 8
    ) -> str:
        """Shelters and camps, ordered by computed distance. Availability is often
        'unknown', which means nobody has confirmed it recently - say that, never 'full' or
        'open'."""
        if not ctx.allowed("resources:read"):
            return refused("resources:read")
        location = ctx.location(location_text)
        items = _nearest_resources(
            db,
            SHELTER_KINDS,
            center=_point_of(location),
            district=_district(district) or location.get("district"),
            within_km=min(max(within_km, 1), 200),
            limit=limit,
        )
        return record_action(
            ctx,
            "find_nearby_shelters",
            {
                "count": len(items),
                "items": items,
                "location": _distance_note(location),
                "note": "catalogue rows only; availability_verified_at says how stale each one is",
            },
            detail=(
                f"{len(items)} shelter(s) within {min(max(within_km, 1), 200)} km"
                + (f", nearest {items[0]['distance_km']} km" if items else "")
            ),
            status=_status_for(len(items)),
            asked={"district": district, "within_km": within_km},
        )

    @tool
    def find_medical_resources(
        location_text: str = "", district: str = "", within_km: int = 50, limit: int = 8
    ) -> str:
        """Hospitals, health posts and ambulances by computed distance. A row is a facility
        we know exists, not a facility that can take a patient now - capability is never
        claimed here."""
        if not ctx.allowed("resources:read"):
            return refused("resources:read")
        location = ctx.location(location_text)
        items = _nearest_resources(
            db,
            MEDICAL_KINDS,
            center=_point_of(location),
            district=_district(district) or location.get("district"),
            within_km=min(max(within_km, 1), 200),
            limit=limit,
        )
        return record_action(
            ctx,
            "find_medical_resources",
            {
                "count": len(items),
                "items": items,
                "location": _distance_note(location),
                "note": (
                    "straight-line distance, not travel time; in mountains a 12 km facility may "
                    "be unreachable - say both if you mention either"
                ),
            },
            detail=(
                f"{len(items)} medical facility(s) within {min(max(within_km, 1), 200)} km"
                + (f", nearest {items[0]['name']} at {items[0]['distance_km']} km" if items else "")
            ),
            status=_status_for(len(items)),
            asked={"district": district, "within_km": within_km},
        )

    @tool
    def find_relief_resources(
        location_text: str = "", district: str = "", within_km: int = 50, limit: int = 8
    ) -> str:
        """Food and water distribution points and camps, ordered by computed distance."""
        if not ctx.allowed("resources:read"):
            return refused("resources:read")
        location = ctx.location(location_text)
        items = _nearest_resources(
            db,
            RELIEF_KINDS,
            center=_point_of(location),
            district=_district(district) or location.get("district"),
            within_km=min(max(within_km, 1), 200),
            limit=limit,
        )
        return record_action(
            ctx,
            "find_relief_resources",
            {
                "count": len(items),
                "items": items,
                "location": _distance_note(location),
                "note": "catalogue rows only",
            },
            detail=(
                f"{len(items)} relief point(s) within {min(max(within_km, 1), 200)} km"
                + (f", nearest {items[0]['distance_km']} km" if items else "")
            ),
            status=_status_for(len(items)),
            asked={"district": district, "within_km": within_km},
        )

    @tool
    def get_incident_details(ref_code: str = "", incident_id: str = "") -> str:
        """One tracked incident as the operator sees it: the score and why, the evidence
        state, how fresh it is and what is attached. The ref code must exist - if it does
        not, say so instead of describing an incident."""
        if not ctx.allowed("incidents:read"):
            return refused("incidents:read")
        incident = db.get(Incident, incident_id) if incident_id else None
        if incident is None:
            incident = _incident_by_ref(db, ref_code)
        if incident is None:
            return record_action(
                ctx,
                "get_incident_details",
                {
                    "error": "not_found",
                    "detail": f"No tracked incident matches {ref_code or incident_id!r}.",
                    "instruction": "do not describe an incident that is not in the system",
                },
                detail=f"no incident matches {ref_code or incident_id or '(nothing given)'}",
                status="error",
                asked={"ref_code": ref_code},
            )
        detail = rc_service.incident_detail(db, incident, ctx.permissions)
        evidence = dict(detail.get("evidence") or {})
        evidence["records"] = (evidence.get("records") or [])[:8]
        payload = {
            "incident": detail.get("incident"),
            "why_prioritized": detail.get("why_prioritized"),
            "evidence": evidence,
            "related_incidents": (detail.get("related_incidents") or [])[:5],
            "alerts": (detail.get("alerts") or [])[:5],
            "open_requests": [
                row.get("ref_code") for row in (detail.get("requests") or []) if row.get("ref_code")
            ][:10],
        }
        summary = payload.get("incident") or {}
        return record_action(
            ctx,
            "get_incident_details",
            payload,
            detail=(
                f"{summary.get('ref_code')} {summary.get('evidence_state')} "
                f"({summary.get('freshness_state')}), impact {summary.get('impact_score')}"
            ),
            asked={"ref_code": ref_code},
        )

    # ------------------------------------------------------------------ the writes
    @tool
    def create_assistance_request(
        request_type: str = AssistanceType.OTHER.value,
        assistance_types: list[str] = [],  # noqa: B006 - strands reads the default, never mutates it
        location_text: str = "",
        people_count: int = 1,
        medical_need: bool = False,
        immediate_danger: bool = False,
        trapped: bool = False,
        minors_involved: bool = False,
        elderly_or_disabled_involved: bool = False,
        evidence_quote: str = "",
        incident_ref: str = "",
    ) -> str:
        """File the help request for this report. Call it once, when the report asks for help.

        What you send is a proposal, not a decision. The risk flags are read from the
        report's own words by fixed rules, so asserting one the text does not carry changes
        nothing and missing one it does carry is corrected - the tool's reply names both. The
        kind of help stands if the words say it or if `evidence_quote` is copied exactly out
        of the report; a quote you composed is reported as unverified. You cannot set the
        urgency, the matched facilities, the status or the description: the description stored
        is the reporter's own words, and the rest is computed by code and returned to you.
        Quote the reference code and the urgency from that reply, never from your memory.
        """
        if not ctx.allowed("assistance:read"):
            return refused("assistance:read")
        proposal = {
            "request_type": request_type,
            "assistance_types": assistance_types,
            "location_text": location_text,
            "people_count": people_count,
            "medical_need": medical_need,
            "immediate_danger": immediate_danger,
            "trapped": trapped,
            "minors_involved": minors_involved,
            "elderly_or_disabled_involved": elderly_or_disabled_involved,
            "evidence_quote": evidence_quote,
            "incident_ref": incident_ref,
        }
        payload, detail = file_request(ctx, proposal)
        return record_action(
            ctx,
            "create_assistance_request",
            payload,
            detail=detail,
            asked={
                "request_type": request_type,
                "assistance_types": list(assistance_types or []),
                "people_count": people_count,
                "medical_need": medical_need,
                "immediate_danger": immediate_danger,
                "trapped": trapped,
                "minors_involved": minors_involved,
                "elderly_or_disabled_involved": elderly_or_disabled_involved,
            },
        )

    @tool
    def update_assistance_request(ref_code: str, note: str = "") -> str:
        """Append an internal investigation note to a case you created or read in this run.
        It cannot change the status, and the person who asked for help does not see it -
        lifecycle moves and victim-visible messages are separate actions with separate
        permissions."""
        if not ctx.allowed("assistance:read"):
            return refused("assistance:read")
        request = _request_by_ref(ctx, ref_code)
        if request is None:
            return record_action(
                ctx,
                "update_assistance_request",
                {"error": "not_found", "detail": f"No request {ref_code!r}."},
                detail=f"no request {ref_code or '(none given)'}",
                status="error",
                asked={"ref_code": ref_code},
            )
        text = (note or "").strip()[:1000]
        if not text:
            return record_action(
                ctx,
                "update_assistance_request",
                {"error": "empty_note", "detail": "Nothing was written."},
                detail="note was empty",
                status="error",
                asked={"ref_code": ref_code},
            )
        assistance_service.add_update(
            db,
            request,
            actor_type="agent",
            actor_id=ctx.operator.id if ctx.operator else None,
            actor_label=f"Sanket agent ({ctx.operator.username})" if ctx.operator else "Sanket agent",
            kind="note",
            message=text,
            visible_to_victim=False,
        )
        audit_service.record(
            db,
            action="request_updated",
            entity_type=audit_service.ENTITY_REQUEST,
            entity_id=request.id,
            actor=ctx.operator,
            actor_kind="agent",
            new={"note": text[:500], "status": request.status},
            reason="agent investigation note",
            commit=True,
        )
        return record_action(
            ctx,
            "update_assistance_request",
            {
                "updated": True,
                "ref_code": request.ref_code,
                "status": request.status,
                "status_changed": False,
                "visible_to_victim": False,
            },
            detail=f"note added to {request.ref_code}; status still {request.status}",
            asked={"ref_code": request.ref_code},
        )

    @tool
    def notify_response_center(
        title: str, body: str = "", severity: str = "information", request_ref: str = "",
        incident_ref: str = "",
    ) -> str:
        """Put a notice in the Response Center queue for a human to open. Filing a request
        already notifies them, so use this only for something the case does not carry - and
        write it as a claim from the reports, not as an instruction to a team. A `request_ref`
        or `incident_ref` that does not exist refuses the call: a notice that cannot say what it
        is about is not filed with the link missing."""
        if not ctx.allowed("incidents:read"):
            return refused("incidents:read")
        request = _request_by_ref(ctx, request_ref) if request_ref else None
        incident = _incident_by_ref(db, incident_ref)
        # A reference that was given and does not resolve is refused rather than ignored. Filed
        # as it was, an unattached notice still reaches the queue looking like a real alert, and
        # the one thing that made it traceable - the case it points at - is quietly gone.
        if request_ref and request is None:
            return record_action(
                ctx,
                "notify_response_center",
                {"error": "not_found", "detail": f"No request {request_ref!r}; nothing was queued."},
                detail=f"no request {request_ref}",
                status="error",
                asked={"title": title[:80], "request_ref": request_ref},
            )
        if incident_ref and incident is None:
            return record_action(
                ctx,
                "notify_response_center",
                {"error": "not_found", "detail": f"No incident {incident_ref!r}; nothing was queued."},
                detail=f"no incident {incident_ref}",
                status="error",
                asked={"title": title[:80], "incident_ref": incident_ref},
            )
        level = severity if severity in {item.value for item in Urgency} else Urgency.INFORMATION.value
        note = notification_service.push(
            db,
            audience=notification_service.AUDIENCE_RESPONSE_CENTER,
            title=(title or "Agent notice")[:200],
            body=(body or "")[:2000],
            kind="agent",
            severity=level,
            link=(f"/requests/{request.ref_code}" if request else None),
            request_id=request.id if request else None,
            incident_id=incident.id if incident else ctx.incident_id,
            district=(request.district if request else None) or (incident.district if incident else None),
        )
        db.commit()
        return record_action(
            ctx,
            "notify_response_center",
            {
                "notified": True,
                "notification_id": note.id,
                "severity": level,
                "attached_to": request.ref_code if request else (incident.ref_code if incident else None),
                "note": "a notice asks a human to look; it dispatches nothing",
            },
            detail=f"notice queued for the Response Center at {level}",
            asked={"title": title[:80], "severity": level, "request_ref": request_ref},
        )

    @tool
    def send_victim_update(ref_code: str, message: str) -> str:
        """Send a message to the person who asked for help. Needs the operator's own
        'message the victim' permission and goes out under their name.

        You may draft the words; what you may not do is tell them anything the run has not
        established. A message containing a figure no tool returned is refused and nothing
        is sent. Say what is real - that a request exists, its reference, what happens next -
        and never promise a time, a team, or an arrival.
        """
        if not ctx.allowed("assistance:message_victim"):
            return refused("assistance:message_victim")
        if ctx.operator is None:
            return record_action(
                ctx,
                "send_victim_update",
                {
                    "error": "no_named_operator",
                    "detail": (
                        "This run is not attached to a person, and a message to someone in "
                        "danger must go out under a named operator. Nothing was sent."
                    ),
                },
                detail="refused: no named operator",
                status="refused",
                asked={"ref_code": ref_code},
            )
        request = _request_by_ref(ctx, ref_code)
        if request is None:
            return record_action(
                ctx,
                "send_victim_update",
                {"error": "not_found", "detail": f"No request {ref_code!r}."},
                detail=f"no request {ref_code or '(none given)'}",
                status="error",
                asked={"ref_code": ref_code},
            )
        from agent.numbers import ungrounded_numbers

        corpus = "\n".join([ctx.report_text, request.ref_code, *ctx.evidence])
        invented = ungrounded_numbers(corpus, message)
        if invented:
            return record_action(
                ctx,
                "send_victim_update",
                {
                    "error": "unverified_numbers",
                    "numbers": invented,
                    "detail": (
                        "The draft states figures no tool returned, so nothing was sent. "
                        "Redraft using only the reference code, the status and what a tool said."
                    ),
                },
                detail=f"refused: {', '.join(invented[:4])} appear in no evidence",
                status="refused",
                asked={"ref_code": ref_code},
            )
        assistance_service.send_victim_update(
            db, request, ctx.operator, message.strip()[:2000], via_agent=True
        )
        return record_action(
            ctx,
            "send_victim_update",
            {
                "sent": True,
                "ref_code": request.ref_code,
                "to": request.user_id or "the reporter on record",
                "sent_by": ctx.operator.username,
                "as_agent_draft": True,
            },
            detail=f"message sent to the reporter on {request.ref_code}",
            asked={"ref_code": request.ref_code},
        )

    return [
        get_recent_earthquakes,
        get_official_disaster_incidents,
        get_river_status,
        get_rainfall_status,
        get_road_status,
        get_community_reports,
        find_related_reports,
        find_nearby_shelters,
        find_medical_resources,
        find_relief_resources,
        get_incident_details,
        create_assistance_request,
        update_assistance_request,
        notify_response_center,
        send_victim_update,
    ]
