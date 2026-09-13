"""Deterministic impact scoring.

The score is a documented, reproducible weighted sum. There is no learned model
and no LLM involvement; given the same incident state the same number always
comes out, and every point is explainable in the UI.

FORMULA
-------
    impact_score = 100 * clamp01( SUM(components) / MAX_TOTAL ) * freshness_multiplier

Components (each already clamped to [0, 1] before weighting):

    severity        w = 0.28   low .18 / moderate .45 / high .78 / severe 1.0 / unknown 0
    fatalities      w = 0.25   log10(1 + deaths) / 2
    missing         w = 0.10   log10(1 + missing) / 1.7
    injured         w = 0.10   log10(1 + injured) / 2.3
    affected        w = 0.08   log10(1 + affected_people) / 3.5
    infrastructure  w = 0.07   log10(1 + houses_damaged) / 2.7
    urgency         w = 0.12   critical 1.0 / urgent .65 / attention .3 / information .05
    evidence        w = 0.06   officially_confirmed 1.0 / officially_reported .8 /
                               corroborated .55 / community_reported .3 / unverified 0
    community_volume w = 0.06  log10(1 + report_count) / 2
    open_requests   w = 0.08   min(1, open_assistance / 8)

    MAX_TOTAL = 1.20

Log scaling is used for population counters so that 10 deaths does not drown out
a 500-person affected population and the score stays comparable across hazard
types. `freshness_multiplier` (see freshness.py) is applied last: identical
information that is 3 days old must rank below the same information when live.

Marker radius/intensity on the map is a monotone function of this score plus
magnitude for earthquakes - see the frontend `markerScale.ts`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.app.scoring import freshness as freshness_mod
from shared.enums import EvidenceState, FreshnessState, Severity, Urgency

_SEVERITY_VALUE = {
    Severity.LOW: 0.18,
    Severity.MODERATE: 0.45,
    Severity.HIGH: 0.78,
    Severity.SEVERE: 1.0,
    Severity.UNKNOWN: 0.0,
}

_URGENCY_VALUE = {
    Urgency.CRITICAL: 1.0,
    Urgency.URGENT: 0.65,
    Urgency.ATTENTION: 0.30,
    Urgency.INFORMATION: 0.05,
}

_EVIDENCE_VALUE = {
    EvidenceState.OFFICIALLY_CONFIRMED: 1.0,
    EvidenceState.OFFICIALLY_REPORTED: 0.8,
    EvidenceState.CORROBORATED: 0.55,
    EvidenceState.COMMUNITY_REPORTED: 0.3,
    EvidenceState.UNVERIFIED: 0.0,
    EvidenceState.CONFLICTING: 0.15,
}

WEIGHTS: dict[str, float] = {
    "severity": 0.28,
    "fatalities": 0.25,
    "missing": 0.10,
    "injured": 0.10,
    "affected": 0.08,
    "infrastructure": 0.07,
    "urgency": 0.12,
    "evidence": 0.06,
    "community_volume": 0.06,
    "open_requests": 0.08,
}
MAX_TOTAL = sum(WEIGHTS.values())


def _log_scale(value: float | None, divisor: float) -> float:
    if not value or value <= 0:
        return 0.0
    return min(1.0, math.log10(1.0 + float(value)) / divisor)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


@dataclass
class ImpactInput:
    severity: str = Severity.UNKNOWN.value
    urgency: str = Urgency.INFORMATION.value
    evidence_state: str = EvidenceState.UNVERIFIED.value
    freshness_state: str = FreshnessState.UNKNOWN.value
    deaths: int = 0
    missing: int = 0
    injured: int = 0
    affected_people: int = 0
    houses_damaged: int = 0
    community_reports: int = 0
    open_assistance: int = 0
    supporting_signals: int = 0
    magnitude: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_incident(cls, incident: Any) -> ImpactInput:
        impact = incident.impact or {}
        return cls(
            severity=incident.severity or Severity.UNKNOWN.value,
            urgency=incident.urgency or Urgency.INFORMATION.value,
            evidence_state=incident.evidence_state or EvidenceState.UNVERIFIED.value,
            freshness_state=impact.get("freshness_state", FreshnessState.UNKNOWN.value),
            deaths=int(impact.get("deaths") or 0),
            missing=int(impact.get("missing") or 0),
            injured=int(impact.get("injured") or 0),
            affected_people=int(impact.get("affected_people") or 0),
            houses_damaged=int(impact.get("houses_damaged") or 0),
            community_reports=int(incident.community_report_count or 0),
            open_assistance=int(incident.open_assistance_count or 0),
            supporting_signals=int(incident.supporting_signal_count or 0),
            magnitude=incident.magnitude,
        )


def score_components(data: ImpactInput) -> dict[str, dict[str, float]]:
    severity_raw = _SEVERITY_VALUE.get(_enum_of(Severity, data.severity, Severity.UNKNOWN), 0.0)
    urgency_raw = _URGENCY_VALUE.get(_enum_of(Urgency, data.urgency, Urgency.INFORMATION), 0.05)
    evidence_raw = _EVIDENCE_VALUE.get(
        _enum_of(EvidenceState, data.evidence_state, EvidenceState.UNVERIFIED), 0.0
    )

    # Seismic events carry their own physical severity signal.
    if data.magnitude is not None and data.magnitude > 0:
        seismic = _clamp01((float(data.magnitude) - 3.0) / 5.0)  # M3 -> 0, M8+ -> 1
        severity_raw = max(severity_raw, seismic)

    parts = {
        "severity": {
            "raw": round(severity_raw, 4),
            "weight": WEIGHTS["severity"],
            "contribution": round(severity_raw * WEIGHTS["severity"], 4),
        },
        "fatalities": _part(_log_scale(data.deaths, 2.0), "fatalities"),
        "missing": _part(_log_scale(data.missing, 1.7), "missing"),
        "injured": _part(_log_scale(data.injured, 2.3), "injured"),
        "affected": _part(_log_scale(data.affected_people, 3.5), "affected"),
        "infrastructure": _part(_log_scale(data.houses_damaged, 2.7), "infrastructure"),
        "urgency": {"raw": round(urgency_raw, 4), "weight": WEIGHTS["urgency"],
                    "contribution": round(urgency_raw * WEIGHTS["urgency"], 4)},
        "evidence": {"raw": round(evidence_raw, 4), "weight": WEIGHTS["evidence"],
                     "contribution": round(evidence_raw * WEIGHTS["evidence"], 4)},
        "community_volume": _part(_log_scale(data.community_reports, 2.0), "community_volume"),
        "open_requests": _part(_clamp01(data.open_assistance / 8.0), "open_requests"),
    }
    return parts


def _part(raw: float, key: str) -> dict[str, float]:
    return {
        "raw": round(raw, 4),
        "weight": WEIGHTS[key],
        "contribution": round(raw * WEIGHTS[key], 4),
    }


def _enum_of(enum_cls, value: str | None, default):
    try:
        return enum_cls((value or default.value).lower())
    except ValueError:
        return default


def calculate(data: ImpactInput) -> tuple[float, dict[str, Any]]:
    """Return (score 0-100, breakdown). Breakdown is what the UI shows under
    'Why Sanket prioritized this' - numbers, not narrative."""
    components = score_components(data)
    total = sum(c["contribution"] for c in components.values())
    multiplier = freshness_mod.freshness_multiplier(
        _enum_of(FreshnessState, data.freshness_state, FreshnessState.UNKNOWN)
    )
    normalised = _clamp01(total / MAX_TOTAL)
    score = round(100 * normalised * multiplier, 2)
    breakdown = {
        "score": score,
        "raw_total": round(total, 4),
        "max_total": round(MAX_TOTAL, 4),
        "normalised": round(normalised, 4),
        "freshness_state": data.freshness_state,
        "freshness_multiplier": multiplier,
        "components": components,
        "formula": "100 * clamp01(sum(raw_i * weight_i) / max_total) * freshness_multiplier",
        "weights": WEIGHTS,
    }
    return score, breakdown


def band(score: float) -> str:
    """Coarse bands drive marker colour intensity and queue grouping."""
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 25:
        return "moderate"
    if score > 0:
        return "low"
    return "minimal"
