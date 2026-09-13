"""Risk / signal engine.

Kept strictly separate from the incident store. A signal is *converging evidence
about conditions*; an incident is *something that happened*. The product never
merges them, and the wording here is deliberately limited to what the data
supports:

    heavy rainfall + river near warning level + road disruption + community reports
        -> "ELEVATED CONCERN", never "landslide will occur"
    recorded seismic event
        -> "RECORDED EARTHQUAKE", never a prediction

Susceptibility is not invented: if no official hazard layer is loaded for an area,
the corresponding factor is simply absent from `contributing_factors`.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.geo.boundaries import boundary_index, normalize_district
from backend.app.models.core import CommunityReport, Incident, Observation, RiskSignal
from backend.app.scoring import freshness as freshness_mod
from shared.enums import (
    FreshnessState,
    IncidentType,
    ObservationKind,
    RiverState,
    SignalLevel,
)
from shared.timeutils import iso, utcnow

logger = logging.getLogger("sanket.signals")

LOOKBACK = timedelta(hours=36)
# Rainfall bands that justify concern. These are our own display bands; the
# official DHM station status string is carried alongside whenever present.
RAINFALL_CONCERN_MM = 60.0
RAINFALL_HIGH_MM = 115.0

SIGNAL_CODE_PREFIX = "SIG"


def rebuild_signals(db: Session, commit: bool = True) -> dict[str, Any]:
    """Recompute district-level flood/landslide concern from current observations.

    Existing auto-derived signals are deactivated rather than deleted, so the
    Action Center can show 'signal cleared' history.
    """
    now = utcnow()
    cutoff = now - LOOKBACK

    rainfall = _recent(db, ObservationKind.RAINFALL.value, cutoff)
    rivers = _recent(db, ObservationKind.RIVER_LEVEL.value, cutoff)
    road = _recent(db, ObservationKind.ROAD_STATUS.value, cutoff)
    alerts = _recent(db, ObservationKind.OFFICIAL_ALERT.value, cutoff)

    districts: dict[str, dict[str, Any]] = {}
    for obs in rainfall:
        key = normalize_district(obs.district) or "Unknown"
        entry = districts.setdefault(key, {"rain": [], "river": [], "road": [], "alert": []})
        entry["rain"].append(obs)
    for obs in rivers:
        key = normalize_district(obs.district) or "Unknown"
        entry = districts.setdefault(key, {"rain": [], "river": [], "road": [], "alert": []})
        entry["river"].append(obs)
    for obs in road:
        entry = districts.setdefault("National", {"rain": [], "river": [], "road": [], "alert": []})
        entry["road"].append(obs)
        if obs.district:
            key = normalize_district(obs.district) or "Unknown"
            districts.setdefault(key, {"rain": [], "river": [], "road": [], "alert": []})["road"].append(obs)
    for obs in alerts:
        key = normalize_district(obs.district) or "National"
        districts.setdefault(key, {"rain": [], "river": [], "road": [], "alert": []})["alert"].append(obs)

    report_counts: dict[str, int] = {}
    for report in db.execute(
        select(CommunityReport).where(
            CommunityReport.created_at >= cutoff,
            CommunityReport.incident_type.in_(
                [IncidentType.LANDSLIDE.value, IncidentType.FLOOD.value, IncidentType.HEAVY_RAINFALL.value, IncidentType.ROAD_BLOCKAGE.value]
            ),
        )
    ).scalars():
        key = normalize_district(report.district) or "Unknown"
        report_counts[key] = report_counts.get(key, 0) + 1

    active_codes: list[str] = []
    created = 0
    for district, buckets in sorted(districts.items()):
        signal = _evaluate(district, buckets, report_counts.get(district, 0), now)
        if not signal:
            continue
        code = signal.pop("code")
        active_codes.append(code)
        existing = db.execute(select(RiskSignal).where(RiskSignal.code == code)).scalar_one_or_none()
        if existing:
            for field, value in signal.items():
                setattr(existing, field, value)
            existing.active = True
        else:
            db.add(RiskSignal(code=code, **signal))
            created += 1

    deactivated = 0
    for signal in db.execute(select(RiskSignal).where(RiskSignal.active.is_(True))).scalars():
        if signal.code not in active_codes:
            signal.active = False
            deactivated += 1

    if commit:
        db.commit()
    return {
        "districts_evaluated": len(districts),
        "signals_active": len(active_codes),
        "signals_created": created,
        "signals_deactivated": deactivated,
    }


def _locate(district: str, sample: Observation | None) -> tuple[float | None, float | None, str]:
    """Place a district-level signal.

    DHM river and rainfall rows arrive as station *names* with no coordinates, so the
    usual answer is the district centroid from the official boundary file. That is an
    approximation and is labelled as one; a national roll-up has no single point and is
    deliberately left unplaced rather than parked on Kathmandu.
    """
    if sample is not None and sample.latitude is not None and sample.longitude is not None:
        return sample.latitude, sample.longitude, "observation_point"
    if district != "National":
        centroid = boundary_index.district_centroid(district)
        if centroid is not None:
            return centroid[0], centroid[1], "district_centroid"
    return None, None, "unlocated"


def _recent(db: Session, kind: str, cutoff) -> list[Observation]:
    return list(
        db.execute(
            select(Observation).where(
                Observation.kind == kind, Observation.received_at >= cutoff
            )
        ).scalars()
    )


def _evaluate(district: str, buckets: dict[str, list[Observation]], report_count: int, now) -> dict[str, Any] | None:
    factors: list[dict[str, Any]] = []
    hazard = "flood"
    level = SignalLevel.NONE

    rain_values = [o.value for o in buckets["rain"] if o.value is not None]
    if rain_values:
        peak = max(rain_values)
        station = max(buckets["rain"], key=lambda o: o.value or 0)
        state = freshness_mod.classify(station.event_time, 21_600, now)
        if peak >= RAINFALL_CONCERN_MM and state is not FreshnessState.STALE:
            factors.append(
                {
                    "kind": "heavy_rainfall",
                    "statement": f"{peak:.0f} mm in 24h at {station.location_name}",
                    "official_status": (station.normalized_data or {}).get("official_status_text"),
                    "display_band": (station.normalized_data or {}).get("display_band"),
                    "is_official_threshold": False,
                    "freshness": state.value,
                    "source": station.source_id,
                    "observed_at": iso(station.event_time),
                }
            )
            if peak >= RAINFALL_HIGH_MM:
                level = _raise(level, SignalLevel.HIGH_CONCERN)

    river_best = None
    river_state = RiverState.NORMAL
    for obs in buckets["river"]:
        normalized = obs.normalized_data or {}
        state = freshness_mod.river_state(
            obs.value, normalized.get("warning_level"), normalized.get("danger_level"),
            freshness_mod.classify(obs.event_time, 3600, now),
        )
        if _RIVER_RANK[state] > _RIVER_RANK[river_state] or river_best is None:
            river_state = state
            river_best = obs
    if river_state in {RiverState.WATCH, RiverState.WARNING, RiverState.DANGER} and river_best:
        normalized = river_best.normalized_data or {}
        factors.append(
            {
                "kind": "river_level",
                "statement": (
                    f"{river_best.location_name} at {river_best.value} m "
                    f"(official warning {normalized.get('warning_level')} m, "
                    f"danger {normalized.get('danger_level')} m) - {river_state.value}"
                ),
                "state": river_state.value,
                "thresholds_are_official": True,
                "trend": river_best.trend,
                "source": river_best.source_id,
                "observed_at": iso(river_best.event_time),
            }
        )
        if river_state == RiverState.DANGER:
            level = _raise(level, SignalLevel.HIGH_CONCERN)
        else:
            level = _raise(level, SignalLevel.ELEVATED_CONCERN)

    if buckets["road"]:
        road = buckets["road"][0]
        factors.append(
            {
                "kind": "road_disruption",
                "statement": f"{len(buckets['road'])} official road-status record(s) in range",
                "structured_state_available": (road.normalized_data or {}).get(
                    "structured_road_state_available", False
                ),
                "source": road.source_id,
                "observed_at": iso(road.event_time),
            }
        )

    if report_count:
        factors.append(
            {
                "kind": "community_reports",
                "statement": f"{report_count} community report(s) of flooding, landslide, heavy rain or road blockage",
                "source": "community",
            }
        )

    if buckets["alert"]:
        alert = buckets["alert"][0]
        factors.append(
            {
                "kind": "official_alert",
                "statement": alert.title[:200],
                "source": alert.source_id,
                "observed_at": iso(alert.event_time),
            }
        )
        level = _raise(level, SignalLevel.HIGH_CONCERN)

    if not factors:
        return None
    if level == SignalLevel.NONE:
        # Two or more independent converging factors is what earns 'elevated'.
        if len(factors) >= 2:
            level = SignalLevel.ELEVATED_CONCERN
        else:
            return None

    hazard = _dominant_hazard(factors)
    label = {
        SignalLevel.ELEVATED_CONCERN: "Elevated concern",
        SignalLevel.HIGH_CONCERN: "High concern",
    }[level]
    sample = next((o for o in (buckets["river"] + buckets["rain"])), None)
    latitude, longitude, precision = _locate(district, sample)
    return {
        "code": f"{SIGNAL_CODE_PREFIX}-{district.replace(' ', '-')[:18].lower()}",
        "hazard": hazard,
        "level": level.value,
        "label": label,
        "statement": _statement(label, hazard, district, factors),
        "latitude": latitude,
        "longitude": longitude,
        "location_precision": precision,
        "district": None if district == "National" else district,
        "province": sample.province if sample else None,
        "contributing_factors": factors,
        "freshness_state": _worst_freshness(factors),
        "observed_at": _newest_moment(factors),
        "expires_at": now + timedelta(hours=12),
        "provenance": "derived",
    }


_RIVER_RANK = {
    RiverState.STALE: -1,
    RiverState.NORMAL: 0,
    RiverState.WATCH: 1,
    RiverState.WARNING: 2,
    RiverState.DANGER: 3,
}


def _raise(current: SignalLevel, candidate: SignalLevel) -> SignalLevel:
    order = [SignalLevel.NONE, SignalLevel.ELEVATED_CONCERN, SignalLevel.HIGH_CONCERN]
    return candidate if order.index(candidate) > order.index(current) else current


def _dominant_hazard(factors: list[dict[str, Any]]) -> str:
    kinds = {f["kind"] for f in factors}
    if "river_level" in kinds or ("heavy_rainfall" in kinds and "official_alert" in kinds):
        return "flood"
    if "heavy_rainfall" in kinds and ("road_disruption" in kinds or "community_reports" in kinds):
        return "landslide"
    if "road_disruption" in kinds:
        return "road"
    return "rainfall"


def _statement(label: str, hazard: str, district: str, factors: list[dict[str, Any]]) -> str:
    kinds = ", ".join(sorted({f["kind"].replace("_", " ") for f in factors}))
    return (
        f"{label}: multiple signals indicate elevated {hazard} concern for {district}. "
        f"Converging signals - {kinds}. This is a condition indicator derived from official "
        "data, not a forecast of a specific event."
    )


def _worst_freshness(factors: list[dict[str, Any]]) -> str:
    states = [f.get("freshness") for f in factors if f.get("freshness")]
    order = [FreshnessState.FRESH, FreshnessState.RECENT, FreshnessState.AGING, FreshnessState.STALE]
    worst = FreshnessState.RECENT
    for state in states:
        try:
            if order.index(FreshnessState(state)) > order.index(worst):
                worst = FreshnessState(state)
        except ValueError:
            continue
    return worst.value


def _newest_moment(factors: list[dict[str, Any]]):
    """Newest contributing observation, so a signal never looks fresher than its
    underlying data. Falls back to 'now' only when nothing carries a time."""
    values = sorted([f["observed_at"] for f in factors if f.get("observed_at")])
    return _parse_last(values[-1]) if values else utcnow()


def _parse_last(value: str):
    from shared.timeutils import parse_iso

    return parse_iso(value) or utcnow()


def active_signals(db: Session, limit: int = 200) -> list[RiskSignal]:
    return list(
        db.execute(
            select(RiskSignal)
            .where(RiskSignal.active.is_(True))
            .order_by(RiskSignal.observed_at.desc())
            .limit(limit)
        ).scalars()
    )


def signal_to_dict(signal: RiskSignal) -> dict[str, Any]:
    return {
        "code": signal.code,
        "hazard": signal.hazard,
        "level": signal.level,
        "label": signal.label,
        "statement": signal.statement,
        "district": signal.district,
        "province": signal.province,
        "latitude": signal.latitude,
        "longitude": signal.longitude,
        "location_precision": signal.location_precision,
        "contributing_factors": signal.contributing_factors,
        "freshness_state": signal.freshness_state,
        "observed_at": iso(signal.observed_at),
        "provenance": signal.provenance,
        "is_prediction": False,
    }


def related_incidents(db: Session, signal: RiskSignal, radius_km: float = 40.0) -> list[Incident]:
    from shared.geo import haversine_km

    if signal.latitude is None:
        return []
    out: list[Incident] = []
    stmt = select(Incident).where(Incident.archived.is_(False)).limit(600)
    for incident in db.execute(stmt).scalars():
        if incident.latitude is None:
            continue
        dist = haversine_km((signal.latitude, signal.longitude), (incident.latitude, incident.longitude))
        if dist is not None and dist <= radius_km:
            out.append(incident)
    return out
