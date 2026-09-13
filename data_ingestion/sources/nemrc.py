"""NEMRC (Seismo Nepal) adapter.

The National Earthquake Monitoring and Research Center publishes no JSON endpoint.
Its map page embeds the recent-earthquake catalogue as an inline JS array, which is
the cleanest legitimate machine-readable access to the official national record.

Nepal time is UTC+05:45; the page carries both the Bikram Sambat date and a Gregorian
`date_ad` plus `time_utc`, so we always key off the AD/UTC pair and keep the BS date as
display metadata for Nepali-language users.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from data_ingestion.http_fetch import SourceMalformed, fetch, inline_json_array
from data_ingestion.normalizers.observation import NormalizedObservation, SourceAdapter, clean_number
from data_ingestion.sources.usgs import severity_for_magnitude
from shared.enums import IncidentType, ObservationKind
from shared.geo import within_nepal
from shared.timeutils import parse_iso

logger = logging.getLogger("sanket.nemrc")

VARIABLE = "earthquakes"


class NemrcEarthquakeAdapter(SourceAdapter):
    code = "nemrc"

    def fetch_observations(self) -> list[NormalizedObservation]:
        result = fetch(self.spec.url, timeout=45.0)
        if not result.ok:
            raise SourceMalformed(self.spec.url, f"HTTP {result.status_code}", result.text)

        raw = inline_json_array(result.text, VARIABLE)
        if not raw:
            raise SourceMalformed(
                self.spec.url,
                f"inline `const {VARIABLE}` array not found - page structure changed",
                result.text[:300],
            )
        try:
            rows = json.loads(raw)
        except ValueError as exc:
            raise SourceMalformed(self.spec.url, f"inline array not valid JSON ({exc})", raw) from exc
        if not isinstance(rows, list):
            raise SourceMalformed(self.spec.url, "inline array was not a list", raw[:300])

        observations = [obs for obs in (self._to_observation(row) for row in rows) if obs]
        logger.info("NEMRC returned %d events", len(observations))
        return observations

    def _to_observation(self, row: dict) -> NormalizedObservation | None:
        lat = clean_number(row.get("latitude"))
        lng = clean_number(row.get("longitude"))
        if lat is None or lng is None:
            return None
        event_time = self._event_time(row)
        magnitude = clean_number(row.get("magnitude"))
        epicenter = str(row.get("epicenter") or "").strip() or "Nepal region"
        external_id = str(row.get("id") or f"{event_time.isoformat() if event_time else 'x'}-{lat}-{lng}")
        return NormalizedObservation(
            source_code=self.code,
            external_id=external_id,
            kind=ObservationKind.EARTHQUAKE,
            title=f"M{magnitude:.1f} - {epicenter}" if magnitude is not None else epicenter,
            summary=(
                "Recorded earthquake per the national monitoring authority. "
                + (f"Occured {row.get('date_ad')} at {row.get('time_utc')} UTC." if row.get("date_ad") else "")
            ).strip(),
            latitude=lat,
            longitude=lng,
            location_name=epicenter,
            incident_type=IncidentType.EARTHQUAKE,
            event_time=event_time,
            severity=severity_for_magnitude(magnitude),
            magnitude=magnitude,
            source_url=self.spec.url,
            subtype="ml",
            within_nepal=within_nepal(lat, lng),
            normalized_data={
                "magnitude_label": "ML (local)",
                "date_ad": row.get("date_ad"),
                "time_utc": row.get("time_utc"),
                "date_bikram_sambat": row.get("date"),
                "local_time": row.get("time"),
                "survey": row.get("survey"),
                "source_published_at": row.get("created_at"),
                "source_record_updated_at": row.get("updated_at"),
            },
            raw_data=row,
        )

    def _event_time(self, row: dict) -> datetime | None:
        date_ad = str(row.get("date_ad") or "").strip()
        time_utc = str(row.get("time_utc") or "").strip()
        if date_ad:
            combined = f"{date_ad}T{time_utc or '00:00:00'}+00:00"
            parsed = parse_iso(combined)
            if parsed:
                return parsed
        fallback = parse_iso(str(row.get("created_at") or ""))
        return fallback
