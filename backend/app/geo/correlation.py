"""Incident correlation: deterministic first pass, agent for the ambiguous remainder.

Two records are candidates for the same incident when they agree on geography,
time and hazard. The score is a documented weighted sum, and the thresholds below
are the only places correlation behaviour is tuned.

STRANDS' role starts where this table stops: pairs scoring in the ambiguous band
(`AMBIGUOUS_LOW <= score < MATCH_THRESHOLD`) are handed to the agent as a
correlation task, and its answer is recorded as a *proposal* with provenance. A
proposal never silently rewrites evidence state - an operator or a later official
record has to accept it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shared.enums import IncidentType
from shared.geo import haversine_km
from shared.timeutils import age_seconds

MATCH_THRESHOLD = 0.72
AMBIGUOUS_LOW = 0.50
MAX_DISTANCE_KM = 12.0
MAX_TIME_GAP_HOURS = 36.0

# How far from a hazard's own point a resident's report about it is still plausible.
# An official record is located *at* the event; a person reports from where they are
# standing, and for shaking that can be a hundred kilometres away. Only the
# report -> incident pass uses these; observation clustering keeps MAX_DISTANCE_KM.
REPORT_RADIUS_KM: dict[str, float] = {
    IncidentType.EARTHQUAKE.value: 120.0,   # felt area, not epicentre
    IncidentType.FLOOD.value: 30.0,         # a flooded ward is reported from the ward
    IncidentType.HEAVY_RAINFALL.value: 30.0,
    IncidentType.LANDSLIDE.value: 20.0,
    IncidentType.ROAD_BLOCKAGE.value: 20.0,
    IncidentType.INFRASTRUCTURE_DAMAGE.value: 15.0,
    IncidentType.STORM.value: 25.0,
    IncidentType.LIGHTNING.value: 10.0,
    IncidentType.FIRE.value: 5.0,           # a fire is reported from next door
}
DEFAULT_REPORT_RADIUS_KM = 15.0

W_DISTANCE = 0.40
W_TIME = 0.20
W_TYPE = 0.25
W_ADMIN = 0.10
W_SEMANTIC = 0.05

# Hazards that are physically downstream of each other: a landslide report and a
# road-blockage report on the same corridor at the same time are one event.
TYPE_AFFINITY: dict[str, set[str]] = {
    IncidentType.LANDSLIDE.value: {IncidentType.ROAD_BLOCKAGE.value, IncidentType.INFRASTRUCTURE_DAMAGE.value, IncidentType.HEAVY_RAINFALL.value, IncidentType.FLOOD.value},
    IncidentType.ROAD_BLOCKAGE.value: {IncidentType.LANDSLIDE.value, IncidentType.FLOOD.value, IncidentType.INFRASTRUCTURE_DAMAGE.value},
    IncidentType.FLOOD.value: {IncidentType.HEAVY_RAINFALL.value, IncidentType.LANDSLIDE.value, IncidentType.ROAD_BLOCKAGE.value, IncidentType.INFRASTRUCTURE_DAMAGE.value},
    IncidentType.HEAVY_RAINFALL.value: {IncidentType.FLOOD.value, IncidentType.LANDSLIDE.value, IncidentType.STORM.value, IncidentType.LIGHTNING.value},
    IncidentType.STORM.value: {IncidentType.HEAVY_RAINFALL.value, IncidentType.LIGHTNING.value, IncidentType.INFRASTRUCTURE_DAMAGE.value},
    IncidentType.EARTHQUAKE.value: {IncidentType.INFRASTRUCTURE_DAMAGE.value, IncidentType.LANDSLIDE.value},
    IncidentType.INFRASTRUCTURE_DAMAGE.value: {IncidentType.EARTHQUAKE.value, IncidentType.FLOOD.value, IncidentType.FIRE.value},
    IncidentType.FIRE.value: {IncidentType.INFRASTRUCTURE_DAMAGE.value},
    IncidentType.LIGHTNING.value: {IncidentType.STORM.value, IncidentType.FIRE.value},
}

_STOPWORDS = re.compile(r"\b(\w{1,3})\b")


@dataclass
class Correlatable:
    """Minimal projection of an observation/report/incident for correlation."""

    id: str
    kind: str  # observation | report | incident
    incident_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    moment: datetime | None = None
    district: str | None = None
    municipality: str | None = None
    source_code: str | None = None
    text: str = ""
    magnitude: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def point(self) -> tuple[float, float] | None:
        if self.latitude is None or self.longitude is None:
            return None
        return (self.latitude, self.longitude)


def distance_component(
    a: Correlatable, b: Correlatable, max_distance_km: float = MAX_DISTANCE_KM
) -> tuple[float | None, float | None]:
    """Returns (component, distance_km). None component means undecidable."""
    dist = haversine_km(a.point(), b.point())
    if dist is None:
        return None, None
    # 0 km -> 1.0, max_distance_km -> 0.0 with a mild falloff so adjacent villages
    # in the same valley are not treated as identical locations.
    component = max(0.0, 1.0 - (dist / max_distance_km)) ** 1.5
    return component, dist


def time_component(a: Correlatable, b: Correlatable) -> float | None:
    if not a.moment or not b.moment:
        return None
    gap = abs((a.moment - b.moment).total_seconds()) / 3600.0
    if gap > MAX_TIME_GAP_HOURS:
        return 0.0
    return max(0.0, 1.0 - (gap / MAX_TIME_GAP_HOURS))


def type_component(a: Correlatable, b: Correlatable) -> float:
    if not a.incident_type or not b.incident_type:
        return 0.35  # unknown hazard should not block a geographically strong match
    if a.incident_type == b.incident_type:
        return 1.0
    if b.incident_type in TYPE_AFFINITY.get(a.incident_type, set()):
        return 0.7
    return 0.05


def administrative_component(a: Correlatable, b: Correlatable) -> float:
    if a.district and b.district:
        if a.district.strip().lower() == b.district.strip().lower():
            if a.municipality and b.municipality and a.municipality.strip().lower() == b.municipality.strip().lower():
                return 1.0
            return 0.75
        return 0.0
    return 0.4  # one side missing admin info: weakly permissive


def semantic_component(a: Correlatable, b: Correlatable) -> float:
    ta, tb = _tokens(a.text), _tokens(b.text)
    if not ta or not tb:
        return 0.4
    intersection = len(ta & tb)
    union = len(ta | tb) or 1
    return min(1.0, intersection / math.sqrt(len(ta) * len(tb))) * 0.8 + (
        0.2 if intersection / union > 0.15 else 0.0
    )


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z\u0900-\u097f']+", (text or "").lower())
    return {w for w in words if len(w) > 3 and not _STOPWORDS.fullmatch(w)}


def report_radius_km(incident_type: str | None) -> float:
    """How far from a hazard's own point a resident's report about it is plausible."""
    return REPORT_RADIUS_KM.get(incident_type or "", DEFAULT_REPORT_RADIUS_KM)


def pair_score(
    a: Correlatable, b: Correlatable, max_distance_km: float = MAX_DISTANCE_KM
) -> tuple[float, dict[str, Any]]:
    """Weighted sum with renormalisation over the components we actually have.

    Missing components (no coordinates, no timestamp) are dropped from the
    denominator rather than counted as zero, so sparse official register rows can
    still correlate - but the result carries `confidence` so callers can tell.
    """
    dist_component, dist_km = distance_component(a, b, max_distance_km)
    parts: dict[str, float] = {
        "distance": dist_component,
        "time": time_component(a, b),
        "type": type_component(a, b),
        "admin": administrative_component(a, b),
        "semantic": semantic_component(a, b),
    }
    weights = {
        "distance": W_DISTANCE,
        "time": W_TIME,
        "type": W_TYPE,
        "admin": W_ADMIN,
        "semantic": W_SEMANTIC,
    }
    available = {k: v for k, v in parts.items() if v is not None}
    if not available:
        return 0.0, {"components": parts, "weight_used": 0.0, "distance_km": dist_km}
    total_weight = sum(weights[k] for k in available)
    score = sum(available[k] * weights[k] for k in available) / total_weight
    return round(score, 4), {
        "components": {k: (None if v is None else round(v, 3)) for k, v in parts.items()},
        "weight_used": round(total_weight, 3),
        "distance_km": None if dist_km is None else round(dist_km, 2),
        "radius_km": max_distance_km,
    }


@dataclass
class Cluster:
    cluster_id: str
    anchor_id: str
    members: list[str]
    scores: dict[str, dict[str, Any]]
    average_score: float
    ambiguous: list[str]


def correlate(items: list[Correlatable], threshold: float = MATCH_THRESHOLD) -> list[Cluster]:
    """Greedy single-linkage clustering: the earliest record anchors a cluster and
    everything matching it joins; ambiguous matches are recorded, not merged."""
    if not items:
        return []
    ordered = sorted(items, key=lambda i: (i.moment or datetime.min, i.id))
    # Earthquakes are located precisely and should anchor clusters ahead of
    # district-centroid register rows.
    ordered.sort(key=lambda i: 0 if i.incident_type == IncidentType.EARTHQUAKE.value else 1, kind="stable")

    assigned: set[str] = set()
    clusters: list[Cluster] = []
    for candidate in ordered:
        if candidate.id in assigned:
            continue
        members = [candidate.id]
        scores: dict[str, dict[str, Any]] = {}
        ambiguous: list[str] = []
        assigned.add(candidate.id)
        for other in ordered:
            if other.id in assigned or other.id == candidate.id:
                continue
            score, detail = pair_score(candidate, other)
            if score >= threshold:
                members.append(other.id)
                scores[other.id] = {"score": score, **detail}
                assigned.add(other.id)
            elif score >= AMBIGUOUS_LOW:
                ambiguous.append(other.id)
                scores[other.id] = {"score": score, "ambiguous": True, **detail}
        average = (
            round(sum(s["score"] for s in scores.values() if "score" in s) / len(scores), 3)
            if scores
            else 1.0
        )
        clusters.append(
            Cluster(
                cluster_id=members[0],
                anchor_id=members[0],
                members=members,
                scores=scores,
                average_score=average,
                ambiguous=ambiguous,
            )
        )
    return clusters


def freshness_of(moment: datetime | None, now: datetime | None = None) -> float:
    """Decay factor used when ranking candidate merges for the agent."""
    secs = age_seconds(moment, now)
    if secs is None:
        return 0.5
    return max(0.1, 1.0 - min(1.0, secs / (7 * 86400)))
