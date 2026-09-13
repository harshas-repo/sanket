"""DHM adapters - official rainfall stations and river gauges.

Two separate live endpoints with very different shapes:

* `POST /hydrology/getRainfallFilter` -> JSON, ~377 stations, accumulated mm.
* `GET  /hydrology/river-watch`       -> ~12 MB server-rendered page embedding the
  gauge array inline, with official warning/danger levels per station.

River threshold states (NORMAL/WATCH/WARNING/DANGER/STALE) are computed against the
warning and danger levels *published by DHM itself* - Sanket never invents a
threshold. Rainfall bands are display-only context and are labelled as such: the
official per-station `status` string is always carried through verbatim.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from data_ingestion.http_fetch import SourceMalformed, fetch, inline_json_array
from data_ingestion.normalizers.observation import (
    NormalizedObservation,
    SourceAdapter,
    clean_number,
)
from shared.enums import ObservationKind
from shared.geo import within_nepal
from shared.timeutils import parse_iso

logger = logging.getLogger("sanket.dhm")

# Display-only intensity bands for hourly/daily accumulation. These are presentation
# thresholds, NOT official DHM warning levels, and the UI labels them that way.
RAINFALL_DISPLAY_BANDS: list[tuple[float, str]] = [
    (300, "extremely_heavy"),
    (115, "very_heavy"),
    (67, "heavy"),
    (20, "moderate"),
    (0.1, "light"),
]


def rainfall_display_band(mm: float | None, hours: float = 24) -> str:
    if mm is None or mm <= 0:
        return "trace"
    # Normalise short accumulation windows onto the 24h bands used by the source UI.
    scaled = mm * (24.0 / hours) if hours and hours != 24 else mm
    for threshold, label in RAINFALL_DISPLAY_BANDS:
        if scaled >= threshold:
            return label
    return "trace"


def _utc_hour(moment: datetime) -> int:
    """Which UTC hour a timestamp belongs to, counting this project's naive datetimes as UTC.

    `datetime.timestamp()` on a naive value assumes the *machine's* zone, which here (Nepal,
    UTC+5:45) slid every bucket away from the hour its rows are named for. The row id and the row's
    own time have to be cut from the same cloth, so both go through here.
    """
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return int(aware.timestamp()) // 3600


class DhmRainfallAdapter(SourceAdapter):
    code = "dhm_rainfall"

    def __init__(self, spec=None, settings=None, window_hours: int = 24):
        super().__init__(spec, settings)
        self.window_hours = window_hours

    def fetch_observations(self) -> list[NormalizedObservation]:
        result = fetch(
            self.spec.url,
            method="POST",
            data={"type": "0", "mapValue": "all", "hour": str(self.window_hours)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=60.0,
        )
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)
        try:
            payload = json.loads(result.text)
        except ValueError as exc:
            raise SourceMalformed(self.spec.url, f"invalid JSON ({exc})", result.text) from exc

        data = payload.get("data") or {}
        # The API keys buckets by numeric string ("0", "1", ...) rather than a list.
        stations: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for bucket in data.values():
                if isinstance(bucket, list):
                    stations.extend(bucket)
        elif isinstance(data, list):
            stations = data
        if not stations:
            raise SourceMalformed(
                self.spec.url, "no station records in payload", json.dumps(payload)[:300]
            )

        observed_at = self._observed_at(payload, result.text)
        observations = [
            obs
            for obs in (self._to_observation(row, observed_at) for row in stations)
            if obs
        ]
        logger.info("DHM rainfall returned %d stations", len(observations))
        return observations

    def _observed_at(self, payload: dict, raw_text: str) -> datetime | None:
        stamp = payload.get("rainfall_date_time") or ""
        if stamp:
            for fmt in ("%a, %b %d %Y ,%H:%M", "%a, %b %d %Y, %H:%M", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(str(stamp).strip(), fmt)
                except ValueError:
                    continue
        return None

    def _to_observation(
        self, row: dict[str, Any], observed_at: datetime | None
    ) -> NormalizedObservation | None:
        lat, lng = clean_number(row.get("latitude")), clean_number(row.get("longitude"))
        station = str(row.get("name") or row.get("stationIndex") or "").strip()
        if not station:
            return None
        mm = clean_number(row.get("value"))
        hours = clean_number(row.get("interval")) or float(self.window_hours)
        official_status = str(row.get("status") or "").strip() or None
        external_id = str(row.get("id") or row.get("series_id") or station)
        # This endpoint sends no timestamp anywhere in the response - verified against the live feed:
        # the payload's only top-level keys are `status` and `data`, and a station row carries no date
        # field, so `observed_at` is always None. The row used to be dated with the exact fetch
        # instant, which is different every single poll: all 367 rows "changed" every 30 minutes,
        # bumping `received_at` and re-stamping the rainfall incidents with the dashboard's "last
        # change: just now". Flooring to the hour makes the time say what the key already says - one
        # point per station per hour - so a poll inside the same hour changes nothing.
        event_time = observed_at or datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        return NormalizedObservation(
            source_code=self.code,
            external_id=f"rain-{external_id}-{_utc_hour(event_time)}",
            kind=ObservationKind.RAINFALL,
            title=f"{station}: {mm if mm is not None else 'n/a'} mm / {int(hours)}h",
            summary=(
                f"Rainfall station {station} in {row.get('district') or 'unknown district'} "
                f"recorded {mm} mm over the last {int(hours)} hours."
            ),
            latitude=lat,
            longitude=lng,
            location_name=station,
            district=_titlecase(row.get("district")),
            within_nepal=within_nepal(lat, lng),
            event_time=event_time,
            value=mm,
            unit="mm",
            subtype=f"{int(hours)}h_accumulation",
            threshold_state=_normalise_official_status(official_status),
            source_url=self.spec.url,
            normalized_data={
                "official_status_text": official_status,
                "display_band": rainfall_display_band(mm, hours),
                "display_band_is_official": False,
                # Where the time on this row came from. In practice always `fetch_hour`, and a
                # reader has to be able to tell that from an observation time the agency published
                # rather than trust a timestamp this adapter supplied.
                "timing_basis": "official" if observed_at else "fetch_hour",
                "station_index": row.get("stationIndex"),
                "basin": row.get("basin") or None,
                "series_id": row.get("series_id"),
                "blink_flag": bool(row.get("blink")),
            },
            raw_data=row,
        )


class DhmRiverAdapter(SourceAdapter):
    code = "dhm_rivers"

    def fetch_observations(self) -> list[NormalizedObservation]:
        result = fetch(
            self.spec.url,
            timeout=120.0,
            # The page is ~12 MB; we only need the leading gauge array.
            max_bytes=40_000_000,
        )
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)
        raw = inline_json_array(result.text, "data")
        if not raw:
            raise SourceMalformed(
                self.spec.url, "inline gauge array not found - page structure changed", ""
            )
        try:
            rows = json.loads(raw)
        except ValueError as exc:
            raise SourceMalformed(self.spec.url, f"gauge array invalid ({exc})", raw) from exc
        observations = [obs for obs in (self._to_observation(r) for r in rows) if obs]
        logger.info("DHM river-watch returned %d gauges", len(observations))
        return observations

    def _to_observation(self, row: dict[str, Any]) -> NormalizedObservation | None:
        lat, lng = clean_number(row.get("latitude")), clean_number(row.get("longitude"))
        name = str(row.get("name") or "").strip()
        if not name:
            return None
        level = clean_number(row.get("water_level"))
        warning = clean_number(row.get("warning_level"))
        danger = clean_number(row.get("danger_level"))
        observed = parse_iso(str(row.get("datetime") or "")) or datetime.utcnow()
        series = row.get("timeSeries") or []
        trend = _trend_from_series(series) or _trend_from_steady(row.get("steady"))
        return NormalizedObservation(
            source_code=self.code,
            external_id=f"river-{row.get('id') or name}-{int(observed.timestamp()) // 900}",
            kind=ObservationKind.RIVER_LEVEL,
            title=f"{name}: {level if level is not None else 'n/a'} m",
            summary=(
                f"River gauge {name} ({row.get('basin') or 'unknown basin'}) at "
                f"{level} m against an official warning level of "
                f"{warning if warning is not None else 'unpublished'} m."
            ),
            latitude=lat,
            longitude=lng,
            location_name=name,
            district=_titlecase(row.get("district")),
            within_nepal=within_nepal(lat, lng),
            event_time=observed,
            value=level,
            unit="m",
            trend=trend,
            subtype=str(row.get("basin") or "") or None,
            threshold_state=_normalise_official_status(str(row.get("status") or "") or None),
            source_url=self.spec.url,
            normalized_data={
                "official_status_text": row.get("status"),
                "warning_level": warning,
                "danger_level": danger,
                "display_range": [clean_number(row.get("minValue")), clean_number(row.get("maxValue"))],
                "series_points": len(series) if isinstance(series, list) else 0,
                "series_is_official_thresholds": True,
            },
            raw_data={k: v for k, v in row.items() if k != "timeSeries"},
        )


def _trend_from_series(series: Any) -> str | None:
    if not isinstance(series, list) or len(series) < 4:
        return None
    values = [clean_number(p[1]) for p in series if isinstance(p, (list, tuple)) and len(p) > 1]
    values = [v for v in values if v is not None]
    if len(values) < 4:
        return None
    tail = values[-max(2, len(values) // 3) :]
    delta = tail[-1] - tail[0]
    span = abs(values[-1]) or 1.0
    if delta / span > 0.02:
        return "rising"
    if delta / span < -0.02:
        return "falling"
    return "steady"


def _trend_from_steady(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in {"rising", "falling", "steady"} else None


def _normalise_official_status(status: str | None) -> str | None:
    """Map DHM's own status wording onto a stable token; keep the original text too."""
    if not status:
        return None
    text = status.strip().upper()
    if "ABOVE DANGER" in text or "DANGER LEVEL" in text and "BELOW" not in text:
        return "danger"
    if "ABOVE WARNING" in text or "REACHED WARNING" in text:
        return "warning"
    if "BELOW WARNING" in text:
        return "below_warning"
    return text.lower().replace(" ", "_")[:48]


def _titlecase(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.title() if text else None
