"""Incident derivation and recomputation.

This module owns the "shared situation" object. Given normalized observations and
community reports it decides whether they belong to an existing incident, creates
new incidents, and recomputes every derived field (evidence state, impact score,
urgency, prioritisation reasons, counters).

Everything here is deterministic. The agent may *propose* a link, and proposals
are stored with provenance, but only this module decides the stored state.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.geo.boundaries import normalize_district
from backend.app.geo.correlation import (
    AMBIGUOUS_LOW,
    Correlatable,
    pair_score,
    report_radius_km,
)
from backend.app.models.core import (
    AssistanceRequest,
    CommunityReport,
    Incident,
    IncidentObservation,
    Observation,
    RiskSignal,
)
from backend.app.scoring import freshness as freshness_mod
from backend.app.scoring import impact as impact_mod
from backend.app.scoring import urgency as urgency_mod
from backend.app.scoring.evidence import EvidenceInputs, compute_state
from shared.enums import (
    AssistanceStatus,
    EvidenceState,
    FreshnessState,
    IncidentStatus,
    IncidentType,
    ObservationKind,
    Severity,
    Urgency,
)
from shared.geo import haversine_km
from shared.timeutils import iso, utcnow

logger = logging.getLogger("sanket.incidents")

# Cross-validation windows. Earthquake catalogues from different agencies locate
# epicentres loosely and timestamp them to the minute, so the window is generous.
EARTHQUAKE_MERGE_KM = 30.0
EARTHQUAKE_MERGE_HOURS = 6.0
GENERIC_MERGE_KM = 8.0
GENERIC_MERGE_HOURS = 48.0
DISTRICT_FALLBACK_WINDOW_DAYS = 3

NATIONAL_SEISMIC_AUTHORITY = "nemrc"
SIGNAL_KINDS = {
    ObservationKind.RAINFALL.value,
    ObservationKind.RIVER_LEVEL.value,
    ObservationKind.ROAD_STATUS.value,
    ObservationKind.FELT_REPORT.value,
}
DIRECT_OFFICIAL_KINDS = {
    ObservationKind.OFFICIAL_INCIDENT.value,
    ObservationKind.OFFICIAL_ALERT.value,
}

_ref_lock_counter = 0


def new_ref_code(prefix: str = "INC") -> str:
    """Readable, collision-resistant reference shown to operators."""
    global _ref_lock_counter
    _ref_lock_counter = (_ref_lock_counter + 1) % 10000
    stamp = utcnow()
    return f"{prefix}-{stamp:%Y%m%d}-{_ref_lock_counter:04d}-{uuid.uuid4().hex[:4]}"


# --------------------------------------------------------------------------- #
# Linking / creation
# --------------------------------------------------------------------------- #
def find_incident_for_observation(db: Session, obs: Observation) -> Incident | None:
    """Deterministic candidate lookup: exact external link first, then geography +
    hazard + time, then (for register rows with centroid-only locations) district +
    hazard + date."""
    existing = db.execute(
        select(IncidentObservation).where(IncidentObservation.observation_id == obs.id).limit(1)
    ).scalar_one_or_none()
    if existing:
        return db.get(Incident, existing.incident_id)

    if obs.latitude is None or obs.longitude is None:
        return _match_by_district(db, obs)

    window = timedelta(hours=EARTHQUAKE_MERGE_HOURS if obs.kind == ObservationKind.EARTHQUAKE.value else GENERIC_MERGE_HOURS)
    radius = EARTHQUAKE_MERGE_KM if obs.kind == ObservationKind.EARTHQUAKE.value else GENERIC_MERGE_KM
    reference_time = obs.event_time or obs.received_at

    stmt = (
        select(Incident)
        .where(
            Incident.archived.is_(False),
            Incident.duplicate_of.is_(None),
            Incident.latitude.is_not(None),
        )
        .order_by(Incident.last_updated_at.desc())
        .limit(600)
    )
    best: tuple[float, Incident] | None = None
    for incident in db.execute(stmt).scalars():
        if obs.incident_type and incident.incident_type and incident.incident_type != obs.incident_type:
            # Downstream hazards (road blockage from a landslide) may still merge,
            # but only through the affinity table, never blindly.
            from backend.app.geo.correlation import TYPE_AFFINITY

            if incident.incident_type not in TYPE_AFFINITY.get(obs.incident_type, set()):
                continue
        dist = haversine_km((obs.latitude, obs.longitude), (incident.latitude, incident.longitude))
        if dist is None or dist > radius:
            continue
        if reference_time and incident.event_time:
            if abs((incident.event_time - reference_time).total_seconds()) > window.total_seconds():
                continue
        score = 1.0 - (dist / (radius * 1.6))
        if best is None or score > best[0]:
            best = (score, incident)
    if best:
        return best[1]
    return _match_by_district(db, obs)


def _match_by_district(db: Session, obs: Observation) -> Incident | None:
    if not obs.district or not obs.incident_type:
        return None
    reference = obs.event_time or obs.received_at
    stmt = (
        select(Incident)
        .where(
            Incident.archived.is_(False),
            Incident.incident_type == obs.incident_type,
            Incident.district == obs.district,
        )
        .order_by(Incident.last_updated_at.desc())
        .limit(40)
    )
    for incident in db.execute(stmt).scalars():
        moment = incident.event_time or incident.first_detected_at
        if moment and reference and abs((moment - reference).days) > DISTRICT_FALLBACK_WINDOW_DAYS:
            continue
        if (incident.location_precision or "") == "district_centroid" or obs.latitude is None:
            return incident
    return None


def link(db: Session, incident: Incident, obs: Observation, role: str = "supporting",
         link_source: str = "system:ingestion") -> bool:
    exists = db.execute(
        select(IncidentObservation).where(
            IncidentObservation.incident_id == incident.id,
            IncidentObservation.observation_id == obs.id,
        )
    ).scalar_one_or_none()
    if exists:
        if exists.role != role:
            exists.role = role
            return True
        return False
    db.add(
        IncidentObservation(
            incident_id=incident.id,
            observation_id=obs.id,
            role=role,
            link_source=link_source,
            linked_at=utcnow(),
        )
    )
    return True


def create_incident_from_observation(db: Session, obs: Observation) -> Incident:
    incident = Incident(
        ref_code=new_ref_code("INC"),
        incident_type=obs.incident_type or IncidentType.OTHER.value,
        title=obs.title or f"{obs.kind} recorded",
        description=obs.summary or "",
        status=IncidentStatus.ACTIVE.value,
        severity=obs.severity or Severity.UNKNOWN.value,
        latitude=obs.latitude,
        longitude=obs.longitude,
        location_name=obs.location_name,
        district=normalize_district(obs.district),
        province=obs.province,
        local_municipality=obs.local_municipality,
        magnitude=obs.magnitude,
        depth_km=obs.depth_km,
        event_time=obs.event_time,
        first_detected_at=obs.received_at or utcnow(),
        last_updated_at=utcnow(),
        provenance=obs.provenance,
        within_nepal=bool(obs.within_nepal),
        location_precision=(obs.normalized_data or {}).get("location_precision")
        or "source_coordinate",
        impact=_impact_from_observation(obs),
    )
    db.add(incident)
    db.flush()
    link(db, incident, obs, role="primary")
    return incident


def _impact_from_observation(obs: Observation) -> dict[str, Any]:
    impact: dict[str, Any] = {
        "deaths": obs.deaths or 0,
        "missing": obs.missing or 0,
        "injured": obs.injured or 0,
        "affected_people": obs.affected_people or 0,
        "houses_damaged": obs.houses_damaged or 0,
    }
    normalized = obs.normalized_data or {}
    for key in (
        "affected_families",
        "displaced_persons",
        "estimated_loss_text",
        "felt_reports",
        "cdi",
        "mmi",
        "significance",
        "magnitude_type",
        "official_status_text",
        "warning_level",
        "danger_level",
        "document_id",
        "pdf_url",
        "structured_road_state_available",
    ):
        if normalized.get(key) is not None:
            impact[key] = normalized[key]
    if normalized.get("location_precision"):
        impact["location_precision"] = normalized["location_precision"]
    return impact


def _outside_creation_window(obs: Observation) -> bool:
    """Old catalogue entries stay as observations (real data, still queryable as
    historical context) but do not open an incident the queue has to carry."""
    limit = settings.incident_creation_window_days
    if not limit or limit <= 0:
        return False
    moment = obs.event_time or obs.received_at
    if moment is None:
        return False
    return (utcnow() - moment).days > limit


def absorb_observation(db: Session, obs: Observation) -> Incident | None:
    """Attach an observation to the incident picture, creating one when needed.

    Environmental signals (rainfall readings, routine river gauges) are *not*
    incidents on their own - they become signals and corroborate existing
    incidents. Only event-bearing kinds create incidents.
    """
    if obs.kind in SIGNAL_KINDS:
        incident = find_incident_for_observation(db, obs)
        if incident:
            link(db, incident, obs, role="supporting")
        return incident
    incident = find_incident_for_observation(db, obs)
    if incident is None:
        if _outside_creation_window(obs):
            return None
        incident = create_incident_from_observation(db, obs)
    else:
        _merge_official_fields(incident, obs)
        link(db, incident, obs, role="supporting")
        incident.last_updated_at = utcnow()
    return incident


def _merge_official_fields(incident: Incident, obs: Observation) -> None:
    """Fill gaps from newer official records; never downgrade a known value."""
    impact = dict(incident.impact or {})
    for key, value in (
        ("deaths", obs.deaths),
        ("missing", obs.missing),
        ("injured", obs.injured),
        ("affected_people", obs.affected_people),
        ("houses_damaged", obs.houses_damaged),
    ):
        if value and int(impact.get(key) or 0) < int(value):
            impact[key] = int(value)
    for key, value in (_impact_from_observation(obs)).items():
        if value in (None, 0, "", {}) and key not in impact:
            continue
        if key not in impact or impact.get(key) in (None, "", 0):
            impact[key] = value
    incident.impact = impact
    if incident.magnitude in (None, 0) and obs.magnitude:
        incident.magnitude = obs.magnitude
    if incident.depth_km is None and obs.depth_km is not None:
        incident.depth_km = obs.depth_km
    if (incident.severity or Severity.UNKNOWN.value) == Severity.UNKNOWN.value and obs.severity:
        incident.severity = obs.severity
    if not incident.district and obs.district:
        incident.district = normalize_district(obs.district)
    if obs.within_nepal:
        incident.within_nepal = True
    if incident.latitude is None and obs.latitude is not None:
        incident.latitude = obs.latitude
        incident.longitude = obs.longitude
        incident.location_precision = (obs.normalized_data or {}).get("location_precision")


# --------------------------------------------------------------------------- #
# Recomputation
# --------------------------------------------------------------------------- #
def recompute(db: Session, incident: Incident, write: bool = True) -> Incident:
    links = list(
        db.execute(
            select(IncidentObservation).where(IncidentObservation.incident_id == incident.id)
        ).scalars()
    )
    observations: list[Observation] = []
    for row in links:
        obs = row.observation or db.get(Observation, row.observation_id)
        if not obs:
            continue
        observations.append(obs)

    reports = list(
        db.execute(
            select(CommunityReport)
            .where(CommunityReport.incident_id == incident.id)
            .where(CommunityReport.duplicate_status != "duplicate")
        ).scalars()
    )
    requests = list(
        db.execute(
            select(AssistanceRequest).where(AssistanceRequest.incident_id == incident.id)
        ).scalars()
    )
    open_requests = [r for r in requests if r.status not in {AssistanceStatus.RESOLVED.value, AssistanceStatus.CANCELLED.value}]
    unique_reporters = {r.user_id or r.location_text or r.id for r in reports}

    official_direct = [o for o in observations if o.kind in DIRECT_OFFICIAL_KINDS]
    official_signals = [o for o in observations if o.kind in SIGNAL_KINDS]
    seismic_official = [o for o in observations if o.kind == ObservationKind.EARTHQUAKE.value]
    distinct_official_sources = {o.source_id for o in observations if o.provenance == "official" and o.source_id}

    authoritative = bool(official_direct) or bool(
        seismic_official and (
            NATIONAL_SEISMIC_AUTHORITY in distinct_official_sources
            or len(distinct_official_sources) >= 2
        )
    )

    state, reasons = compute_state(
        EvidenceInputs(
            # A single agency catalogue entry makes the event officially *reported*;
            # only the national authority or two agreeing agencies confirm it.
            official_observation_kinds=[o.kind for o in official_direct]
            + ([ObservationKind.EARTHQUAKE.value] if seismic_official else []),
            official_sources=sorted(distinct_official_sources),
            supporting_signal_kinds=[o.kind for o in official_signals],
            community_report_count=len(reports),
            unique_reporter_count=len(unique_reporters),
            conflicting_count=incident.conflicting_signal_count or _count_conflicts(observations, reports),
            authoritative_confirmation=authoritative,
            # Operator verification is an explicit, audited act - it is never implied
            # by the derived `official_confirmation` flag, or every recomputation
            # would promote its own conclusion.
            operator_verified=bool(incident.verified_by),
            provenance=incident.provenance,
        )
    )

    freshness = _incident_freshness(incident, observations, reports)
    impact = dict(incident.impact or {})
    impact["freshness_state"] = freshness.value
    impact["official_source_count"] = len(distinct_official_sources)
    impact["cross_validated"] = len(distinct_official_sources) >= 2
    impact["report_count"] = len(reports)
    incident.impact = impact

    incident.evidence_state = state.value
    incident.official_confirmation = state in {
        EvidenceState.OFFICIALLY_CONFIRMED,
        EvidenceState.OFFICIALLY_REPORTED,
    }
    if state == EvidenceState.OFFICIALLY_CONFIRMED and incident.confirmed_by_source is None:
        if authoritative:
            incident.confirmed_by_source = (
                NATIONAL_SEISMIC_AUTHORITY
                if NATIONAL_SEISMIC_AUTHORITY in distinct_official_sources
                else (", ".join(sorted(distinct_official_sources)) or None)
            )
        elif incident.verified_by:
            incident.confirmed_by_source = "response_center_operator"
    elif state != EvidenceState.OFFICIALLY_CONFIRMED and incident.confirmed_by_source not in (
        None,
        "response_center_operator",
    ):
        # Evidence walked back (source record removed): drop the stale attribution.
        incident.confirmed_by_source = None

    incident.community_report_count = len(reports)
    incident.assistance_request_count = len(requests)
    incident.open_assistance_count = len(open_requests)
    incident.supporting_signal_count = len(official_signals) + len(official_direct)
    incident.conflicting_signal_count = _count_conflicts(observations, reports)

    score, breakdown = impact_mod.calculate(
        impact_mod.ImpactInput.from_incident(
            _TempIncident(incident, freshness, breakdown_impact=impact)
        )
    )
    incident.impact_score = score
    incident.score_breakdown = breakdown

    base_urgency = _base_urgency(incident, observations)
    escalated = urgency_mod.escalate_from_volume(
        base_urgency, len(reports), len(open_requests)
    )
    if state == EvidenceState.CONFLICTING and escalated not in {Urgency.CRITICAL.value, Urgency.URGENT.value}:
        escalated = Urgency.URGENT
    incident.urgency = escalated if isinstance(escalated, str) else escalated.value

    incident.prioritization_reasons = _reasons(
        incident, reports, requests, observations, breakdown, state, freshness
    )
    incident.needs_review = _needs_review(incident, state, reports, len(distinct_official_sources))
    if incident.needs_review:
        incident.review_reason = _review_reason(incident, state, reports)

    if write:
        incident.last_updated_at = utcnow()
        db.flush()
    return incident


class _TempIncident:
    """Adapter so impact.calculate() can read a freshness state that we computed
    here rather than one already persisted on the row."""

    def __init__(self, incident: Incident, freshness: FreshnessState, breakdown_impact: dict[str, Any]):
        self._incident = incident
        self.impact = {**breakdown_impact, "freshness_state": freshness.value}

    def __getattr__(self, item: str):
        return getattr(self._incident, item)


def _incident_freshness(
    incident: Incident, observations: list[Observation], reports: list[CommunityReport]
) -> FreshnessState:
    moments: list[datetime] = []
    if incident.event_time:
        moments.append(incident.event_time)
    moments.extend(o.event_time or o.received_at for o in observations)
    moments.extend(r.created_at for r in reports)
    moments = [m for m in moments if m]
    if not moments:
        return freshness_mod.classify(incident.last_updated_at, 86_400)
    newest = max(moments)
    budget = 7 * 86_400 if incident.incident_type not in {IncidentType.FLOOD.value, IncidentType.LANDSLIDE.value} else 2 * 86_400
    return freshness_mod.classify(newest, budget)


def _count_conflicts(observations: list[Observation], reports: list[CommunityReport]) -> int:
    """A conflict is concrete: an official record saying a road is open while other
    evidence in the same cluster says it is blocked, or magnitude disagreement
    between seismic agencies beyond 1.0 units."""
    conflicts = 0
    road_states = {
        (o.normalized_data or {}).get("official_status_text") or o.threshold_state
        for o in observations
        if o.kind == ObservationKind.ROAD_STATUS.value
    }
    if any(s and "open" in str(s).lower() for s in road_states) and any(
        s and ("clos" in str(s).lower() or "block" in str(s).lower()) for s in road_states
    ):
        conflicts += 1
    magnitudes = [o.magnitude for o in observations if o.magnitude]
    if len(magnitudes) >= 2 and (max(magnitudes) - min(magnitudes)) > 1.0:
        conflicts += 1
    severity_claims = {r.severity for r in reports if r.severity}
    if len(severity_claims) >= 2 and "severe" in severity_claims and "low" in severity_claims:
        conflicts += 1
    return conflicts


def _base_urgency(incident: Incident, observations: list[Observation]) -> Urgency:
    impact = incident.impact or {}
    if int(impact.get("deaths") or 0) > 0 or int(impact.get("missing") or 0) > 0:
        return Urgency.CRITICAL
    if incident.incident_type == IncidentType.EARTHQUAKE.value:
        mag = incident.magnitude or 0
        if mag >= 6.5:
            return Urgency.CRITICAL
        if mag >= 5.0:
            return Urgency.URGENT
        if mag >= 4.0:
            return Urgency.ATTENTION
        return Urgency.INFORMATION
    if incident.severity == Severity.SEVERE.value:
        return Urgency.URGENT
    if incident.severity == Severity.HIGH.value:
        return Urgency.ATTENTION
    if int(impact.get("injured") or 0) > 0:
        return Urgency.URGENT
    return Urgency.INFORMATION


def _reasons(
    incident: Incident,
    reports: list[CommunityReport],
    requests: list[AssistanceRequest],
    observations: list[Observation],
    breakdown: dict[str, Any],
    state: EvidenceState,
    freshness: FreshnessState,
) -> list[str]:
    """Deterministic explanation for 'Why Sanket prioritized this'. Concise facts -
    never model chain-of-thought."""
    reasons: list[str] = []
    impact = incident.impact or {}
    deaths = int(impact.get("deaths") or 0)
    missing = int(impact.get("missing") or 0)
    injured = int(impact.get("injured") or 0)
    affected = int(impact.get("affected_people") or 0)
    if deaths:
        reasons.append(f"{deaths} death{'s' if deaths != 1 else ''} in the official record")
    if missing:
        reasons.append(f"{missing} person{'s' if missing != 1 else ''} reported missing")
    if injured:
        reasons.append(f"{injured} injured")
    if affected:
        families = impact.get("affected_families")
        reasons.append(
            f"~{affected} people affected" + (f" ({families} families)" if families else "")
        )
    if incident.magnitude:
        reasons.append(f"M{incident.magnitude:.1f} recorded earthquake")
    if reports:
        recent = [r for r in reports if (utcnow() - r.created_at) < timedelta(hours=6)]
        near = [r.distance_to_incident_km for r in reports if r.distance_to_incident_km is not None]
        text = f"{len(reports)} community report{'s' if len(reports) != 1 else ''}"
        if len(recent) != len(reports):
            text += f" ({len(recent)} in last 6h)"
        if near:
            text += f", median distance {sorted(near)[len(near) // 2]:.1f} km"
        reasons.append(text)
    open_requests = [r for r in requests if r.status not in {AssistanceStatus.RESOLVED.value, AssistanceStatus.CANCELLED.value}]
    if open_requests:
        critical = [r for r in open_requests if r.urgency == Urgency.CRITICAL.value]
        medical = [r for r in open_requests if r.medical_need]
        label = f"{len(open_requests)} unresolved assistance request{'s' if len(open_requests) != 1 else ''}"
        extras = []
        if critical:
            extras.append(f"{len(critical)} critical")
        if medical:
            extras.append(f"{len(medical)} medical")
        if extras:
            label += " (" + ", ".join(extras) + ")"
        reasons.append(label)
    official = [o for o in observations if o.provenance == "official"]
    if official:
        kinds = sorted({o.kind.replace("_", " ") for o in official})
        reasons.append("official data present: " + ", ".join(kinds[:4]))
    if impact.get("cross_validated"):
        reasons.append("cross-validated by " + str(impact.get("official_source_count")) + " official sources")
    reasons.append(f"evidence: {state.value.replace('_', ' ')}")
    if freshness == FreshnessState.STALE:
        reasons.append("information is stale - verify before dispatch")
    top = sorted(
        (k, v["contribution"]) for k, v in breakdown.get("components", {}).items()
    )
    top = [k for k, c in top if c >= 0.05][:4]
    if top:
        reasons.append("score drivers: " + ", ".join(top))
    return reasons


def _needs_review(incident: Incident, state: EvidenceState, reports: list[CommunityReport], official_source_count: int) -> bool:
    """Deterministic 'this needs a human' flag for the Action Center."""
    if state == EvidenceState.CONFLICTING:
        return True
    if len(reports) >= 3 and official_source_count == 0:
        return True
    if any(r.verification_status == "pending" and r.urgency == Urgency.CRITICAL.value for r in reports):
        return True
    if (incident.location_precision or "") == "district_centroid" and len(reports) >= 5:
        return True
    return False


def _review_reason(incident: Incident, state: EvidenceState, reports: list[CommunityReport]) -> str | None:
    if state == EvidenceState.CONFLICTING:
        return "Sources disagree - reconcile before acting"
    if len(reports) >= 3 and state == EvidenceState.COMMUNITY_REPORTED:
        return f"{len(reports)} community reports with no official backing"
    if (incident.location_precision or "") == "district_centroid":
        return "Location is a district centroid, not a surveyed coordinate"
    return None


# --------------------------------------------------------------------------- #
# Community report intake
# --------------------------------------------------------------------------- #
def attach_report(db: Session, report: CommunityReport) -> tuple[Incident | None, float | None]:
    """Deterministic report -> incident association, plus duplicate handling.

    Distance from the report to the incident is computed here (code, not the LLM)
    and persisted because it is shown verbatim in 'why this was prioritized'.
    """
    candidate = _find_incident_for_report(db, report)
    if candidate is None:
        return None, None
    distance = haversine_km(
        (report.latitude, report.longitude) if report.latitude is not None else None,
        (candidate.latitude, candidate.longitude) if candidate.latitude is not None else None,
    )
    report.incident_id = candidate.id
    report.distance_to_incident_km = None if distance is None else round(distance, 2)
    duplicates: list[CommunityReport] = []
    corroborating: list[CommunityReport] = []
    for existing in db.execute(
        select(CommunityReport).where(
            CommunityReport.incident_id == candidate.id, CommunityReport.id != report.id
        )
    ).scalars():
        if _is_duplicate(report, existing):
            duplicates.append(existing)
        elif _is_corroborating(report, existing):
            corroborating.append(existing)
    # The most recent match is the one the person is actually re-sending into. Pointing
    # at the oldest would attach a fresh plea to a case that was closed an hour ago,
    # and the queue would never learn that somebody is waiting again.
    if duplicates:
        newest = max(duplicates, key=lambda row: row.created_at)
        report.duplicate_status = "duplicate"
        report.duplicate_of_report_id = newest.id
    for existing in corroborating:
        if existing.id not in report.corroborating_report_ids:
            report.corroborating_report_ids = [*report.corroborating_report_ids, existing.id]
        if report.id not in existing.corroborating_report_ids:
            existing.corroborating_report_ids = [*existing.corroborating_report_ids, report.id]
    link_report_as_observation(db, candidate, report)
    return candidate, distance


def _find_incident_for_report(db: Session, report: CommunityReport) -> Incident | None:
    reference = Correlatable(
        id=report.id,
        kind="report",
        incident_type=report.incident_type,
        latitude=report.latitude,
        longitude=report.longitude,
        # A report's timestamp records when somebody typed it, not when the event
        # happened - people report an earthquake hours or days after feeling it. So the
        # time component is dropped here (pair_score renormalises over the components
        # present) and replaced by the one physical check that does hold below.
        moment=None,
        district=report.district,
        text=report.message,
    )
    # An official record sits at the event; a resident reports from where they are
    # standing, which for shaking is routinely tens of kilometres from the epicentre.
    radius_km = report_radius_km(report.incident_type)
    stmt = (
        select(Incident)
        .where(Incident.archived.is_(False), Incident.duplicate_of.is_(None))
        .order_by(Incident.last_updated_at.desc())
        .limit(500)
    )
    best: tuple[float, Incident] | None = None
    for incident in db.execute(stmt).scalars():
        moment = incident.event_time or incident.first_detected_at
        if (
            moment is not None
            and report.created_at is not None
            and (moment - report.created_at).total_seconds() > 6 * 3600
        ):
            # Nobody describes an event before it occurs; that is a different incident.
            continue
        other = Correlatable(
            id=incident.id,
            kind="incident",
            incident_type=incident.incident_type,
            latitude=incident.latitude,
            longitude=incident.longitude,
            moment=moment,
            district=incident.district,
            text=f"{incident.title} {incident.description}",
        )
        score, _detail = pair_score(reference, other, max_distance_km=radius_km)
        if score >= AMBIGUOUS_LOW and (best is None or score > best[0]):
            best = (score, incident)
    return best[1] if best else None


def _same_place(a: CommunityReport, b: CommunityReport) -> bool:
    dist = haversine_km(
        (a.latitude, a.longitude) if a.latitude is not None else None,
        (b.latitude, b.longitude) if b.latitude is not None else None,
    )
    if dist is not None:
        return dist <= 1.5
    return bool(a.district and b.district and a.district.lower() == b.district.lower())


def _is_duplicate(a: CommunityReport, b: CommunityReport) -> bool:
    if a.id == b.id:
        return False
    if (a.incident_type or "") != (b.incident_type or ""):
        return False
    if not _same_place(a, b):
        return False
    if abs((a.created_at - b.created_at).total_seconds()) > 6 * 3600:
        return False
    from backend.app.geo.correlation import _tokens, semantic_component

    tokens_a, tokens_b = _tokens(a.message), _tokens(b.message)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))
    return overlap > 0.8 or semantic_component(
        Correlatable(id=a.id, kind="report", text=a.message),
        Correlatable(id=b.id, kind="report", text=b.message),
    ) > 0.9


def _is_corroborating(a: CommunityReport, b: CommunityReport) -> bool:
    if a.id == b.id or (a.user_id and b.user_id and a.user_id == b.user_id):
        return False
    if (a.incident_type or "") != (b.incident_type or ""):
        return False
    if not _same_place(a, b):
        return False
    return abs((a.created_at - b.created_at).total_seconds()) <= 12 * 3600


def link_report_as_observation(
    db: Session,
    incident: Incident,
    report: CommunityReport,
    link_source: str = "system:correlation",
) -> None:
    """Community reports get an observation row too, so the provenance graph holds
    both kinds of evidence in one table. `link_source` records whether the system
    correlated it or an operator placed it here by hand."""
    external_id = f"report-{report.id}"
    obs = db.execute(
        select(Observation).where(
            Observation.source_id == "community", Observation.external_id == external_id
        )
    ).scalar_one_or_none()
    if obs is None:
        obs = Observation(
            source_id="community",
            external_id=external_id,
            kind=ObservationKind.FELT_REPORT.value,
            title=(report.message or "")[:480],
            summary=(report.message or "")[:2000],
            latitude=report.latitude,
            longitude=report.longitude,
            location_name=report.location_text,
            district=report.district,
            province=report.province,
            event_time=report.client_timestamp or report.created_at,
            received_at=report.created_at,
            severity=report.severity,
            # The observation inherits the report's provenance. Hardcoding "community" here
            # made a demo report's derived observation look like real citizen evidence, so it
            # survived demo cleanup while the report itself was deleted.
            provenance=report.provenance or "community",
            within_nepal=bool(report.latitude),
            normalized_data={
                "report_type": report.report_type,
                "urgency": report.urgency,
                "medical_need": report.medical_need,
                "people_count": report.people_count,
                "verification_status": report.verification_status,
                "location_precision": report.location_confidence,
                "language": report.language,
            },
            raw_data={"report_id": report.id},
        )
        db.add(obs)
        db.flush()
    link(db, incident, obs, role="community", link_source=link_source)


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #
def timeline(db: Session, incident: Incident) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    observation_ids = [
        row.observation_id
        for row in db.execute(
            select(IncidentObservation).where(IncidentObservation.incident_id == incident.id)
        ).scalars()
    ]
    if observation_ids:
        for obs in db.execute(select(Observation).where(Observation.id.in_(observation_ids))).scalars():
            label = {
                ObservationKind.EARTHQUAKE.value: "Seismic event recorded",
                ObservationKind.OFFICIAL_INCIDENT.value: "Official incident record",
                ObservationKind.OFFICIAL_ALERT.value: "Official alert issued",
                ObservationKind.RAINFALL.value: "Rainfall reading",
                ObservationKind.RIVER_LEVEL.value: "River gauge reading",
                ObservationKind.ROAD_STATUS.value: "Road status information",
                ObservationKind.FELT_REPORT.value: "Community observation",
            }.get(obs.kind, "Observation")
            if obs.source_id == "community":
                label = "Community report"
            events.append(
                {
                    "at": iso(obs.event_time or obs.received_at),
                    "received_at": iso(obs.received_at),
                    "kind": "observation",
                    "label": label,
                    "detail": obs.title,
                    "source": obs.source_id,
                    "provenance": obs.provenance,
                    "entity_id": obs.id,
                }
            )
    for report in db.execute(
        select(CommunityReport).where(CommunityReport.incident_id == incident.id)
    ).scalars():
        events.append(
            {
                "at": iso(report.client_timestamp or report.created_at),
                "received_at": iso(report.created_at),
                "kind": "report",
                "label": "Community report",
                "detail": report.message[:240],
                "source": "community",
                "provenance": "community",
                "entity_id": report.id,
            }
        )
    for request in db.execute(
        select(AssistanceRequest).where(AssistanceRequest.incident_id == incident.id)
    ).scalars():
        events.append(
            {
                "at": iso(request.created_at),
                "received_at": iso(request.created_at),
                "kind": "assistance",
                "label": f"Assistance request {request.ref_code}",
                "detail": f"{request.urgency} - {', '.join(request.assistance_types) or request.request_type}",
                "source": "community",
                "provenance": request.provenance,
                "entity_id": request.id,
            }
        )
    from backend.app.models.core import AuditEvent

    for audit in db.execute(
        select(AuditEvent).where(AuditEvent.entity_id == incident.id).order_by(AuditEvent.created_at)
    ).scalars():
        events.append(
            {
                "at": iso(audit.created_at),
                "received_at": iso(audit.created_at),
                "kind": "operator",
                "label": audit.action.replace("_", " ").title(),
                "detail": audit.reason or "",
                "source": audit.actor_label,
                "provenance": "derived",
                "entity_id": audit.id,
            }
        )
    for signal in db.execute(
        select(RiskSignal).where(
            RiskSignal.district == incident.district, RiskSignal.active.is_(True)
        )
    ).scalars():
        events.append(
            {
                "at": iso(signal.observed_at),
                "received_at": iso(signal.created_at),
                "kind": "signal",
                "label": f"{signal.hazard.replace('_', ' ')} signal",
                "detail": signal.statement,
                "source": "derived",
                "provenance": signal.provenance,
                "entity_id": signal.id,
            }
        )
    events.sort(key=lambda e: e["at"] or "")
    return events


def related_reports(db: Session, incident: Incident, limit: int = 50) -> list[CommunityReport]:
    return list(
        db.execute(
            select(CommunityReport)
            .where(CommunityReport.incident_id == incident.id)
            .order_by(CommunityReport.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def incidents_for_codes(db: Session, codes: Iterable[str]) -> list[Incident]:
    codes = list(codes)
    if not codes:
        return []
    return list(db.execute(select(Incident).where(Incident.ref_code.in_(codes))).scalars())
