"""USGS earthquake adapter (official FDSN event service)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from data_ingestion.http_fetch import SourceMalformed, fetch
from data_ingestion.normalizers.observation import NormalizedObservation, SourceAdapter, clean_number
from shared.enums import IncidentType, ObservationKind, Severity
from shared.geo import within_nepal
from shared.timeutils import epoch_ms_to_utc, to_utc

logger = logging.getLogger("sanket.usgs")

# Bounding box covering Nepal plus adjacent seismic source zones.
NEPAL_BBOX = {"minlongitude": 80.0, "maxlongitude": 88.3, "minlatitude": 25.8, "maxlatitude": 31.0}


def severity_for_magnitude(mag: float | None) -> str:
    if mag is None:
        return Severity.UNKNOWN.value
    if mag >= 6.5:
        return Severity.SEVERE.value
    if mag >= 5.5:
        return Severity.HIGH.value
    if mag >= 4.5:
        return Severity.MODERATE.value
    return Severity.LOW.value


class UsgsEarthquakeAdapter(SourceAdapter):
    code = "usgs"

    def __init__(self, spec=None, settings=None, lookback_days: int = 7, min_magnitude: float = 3.0):
        super().__init__(spec, settings)
        self.lookback_days = lookback_days
        self.min_magnitude = min_magnitude

    def build_params(self, now: datetime | None = None) -> dict[str, Any]:
        end = to_utc(now) or datetime.utcnow()
        start = end - timedelta(days=self.lookback_days)
        params = dict(NEPAL_BBOX)
        params.update(
            {
                "format": "geojson",
                "starttime": start.strftime("%Y-%m-%d"),
                "endtime": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
                "minmagnitude": self.min_magnitude,
                "orderby": "time",
            }
        )
        return params

    def fetch_observations(self) -> list[NormalizedObservation]:
        params = self.build_params()
        result = fetch(self.spec.url, params=params, timeout=45.0)
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)
        try:
            payload = json.loads(result.text)
        except ValueError as exc:
            raise SourceMalformed(self.spec.url, f"invalid GeoJSON ({exc})", result.text) from exc

        features = payload.get("features")
        if features is None:
            raise SourceMalformed(self.spec.url, "GeoJSON without 'features'", result.text[:300])

        observations: list[NormalizedObservation] = []
        for feature in features:
            obs = self._to_observation(feature)
            if obs:
                observations.append(obs)
        logger.info("USGS returned %d events", len(observations))
        return observations

    def _to_observation(self, feature: dict[str, Any]) -> NormalizedObservation | None:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            return None
        lng, lat = clean_number(coords[0]), clean_number(coords[1])
        depth = clean_number(coords[2]) if len(coords) > 2 else None
        if lat is None or lng is None:
            return None
        event_id = str(props.get("id") or feature.get("id") or "").strip()
        if not event_id:
            return None
        mag = clean_number(props.get("mag"))
        place = str(props.get("place") or "").strip() or "Unlocated event"
        time_utc = epoch_ms_to_utc(props.get("time")) or epoch_ms_to_utc(props.get("hour"))
        felt = props.get("felt")
        cdi = clean_number(props.get("cdi"))
        mmi = clean_number(props.get("mmi"))
        # `time`/`url` are the authoritative ids for provenance.
        return NormalizedObservation(
            source_code=self.code,
            external_id=event_id,
            kind=ObservationKind.EARTHQUAKE,
            title=f"M{mag:.1f} - {place}" if mag is not None else place,
            summary=(
                f"Recorded earthquake of magnitude {mag} at {place}. "
                f"Depth {depth:.0f} km."
                if mag is not None and depth is not None
                else f"Recorded earthquake of magnitude {mag} at {place}."
                if mag is not None
                else f"Seismic event recorded at {place}."
            ),
            latitude=lat,
            longitude=lng,
            location_name=place,
            incident_type=IncidentType.EARTHQUAKE,
            event_time=time_utc,
            severity=severity_for_magnitude(mag),
            magnitude=mag,
            depth_km=depth,
            source_url=props.get("url") or self.spec.url,
            subtype=str(props.get("type") or "earthquake"),
            within_nepal=within_nepal(lat, lng),
            normalized_data={
                "magnitude_type": props.get("magType"),
                "felt_reports": int(felt) if felt is not None else None,
                "cdi": cdi,
                "mmi": mmi,
                "tsunami_flag": bool(props.get("tsunami")),
                "significance": clean_number(props.get("sig")),
                "status": props.get("status"),
                "review_status": props.get("review"),
                "nearest_district_hint": _nearest_place_hint(place),
                "source_recorded_utc": time_utc,
            },
            raw_data={k: v for k, v in props.items() if k not in ("sources", "titles")},
        )


def _nearest_place_hint(place: str) -> str | None:
    """USGS writes '90 km NNE of Chitre, Nepal' - pull the named place after 'of'."""
    if not place:
        return None
    lowered = place.lower()
    if " of " in lowered:
        tail = place[lowered.index(" of ") + 4 :]
        return tail.split(",")[0].strip() or None
    return place.split(",")[0].strip() or None
