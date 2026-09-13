"""Flood Forecasting and Early Warning Service (hydrology.gov.np) adapter.

This is the one Nepali source with a proper public JSON API. `GET /cm/api-public/alerts`
returns `[]` when nothing is active - a valid live answer, never treated as a failure.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from data_ingestion.http_fetch import SourceMalformed, fetch
from data_ingestion.normalizers.observation import (
    NormalizedObservation,
    SourceAdapter,
    clean_number,
)
from shared.enums import IncidentType, ObservationKind, Severity
from shared.nepal_places import resolve_place
from shared.timeutils import parse_iso, utcnow

logger = logging.getLogger("sanket.hydrology")

ALERT_ENDPOINTS = {
    "alerts": "https://hydrology.gov.np/cm/api-public/alerts",
    "current_forecast": "https://hydrology.gov.np/cm/api-public/current_forecast",
    "notice": "https://hydrology.gov.np/cm/api-public/notice",
}

# Verified against the live API: `alerts` rows carry no date at all and
# `current_forecast` carries none either - only the bulletin title states when it
# was issued ("Flood Bulletin_15_Jun_2024_7AM (असार-६१)"). `notice` does have
# `published_date`/`expiry_date`. When no date can be read from the record the
# observation keeps event_time = None so freshness reports UNKNOWN rather than
# pretending a years-old PDF is live information.
_TITLE_DATE = re.compile(
    r"(\d{1,2})[ _-]([A-Za-z]{3,9})[ _-](\d{4})", re.IGNORECASE
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class HydrologyAlertAdapter(SourceAdapter):
    code = "hydrology_alerts"

    def fetch_observations(self) -> list[NormalizedObservation]:
        observations: list[NormalizedObservation] = []
        errors: list[str] = []
        for bucket, url in ALERT_ENDPOINTS.items():
            try:
                rows = self._fetch_list(url)
            except (SourceMalformed, Exception) as exc:  # noqa: BLE001 - one sub-endpoint must not sink the source
                errors.append(f"{bucket}: {exc}")
                continue
            observations.extend(self._to_observations(bucket, url, rows))
        if not observations and errors and len(errors) == len(ALERT_ENDPOINTS):
            raise SourceMalformed(self.spec.url, "; ".join(errors)[:400], "")
        if errors:
            logger.warning("hydrology partial: %s", "; ".join(errors))
        return observations

    def _fetch_list(self, url: str) -> list[dict]:
        result = fetch(url, timeout=45.0)
        if not result.ok:
            raise SourceMalformed(url, f"HTTP {result.status_code}", result.text)
        try:
            payload = json.loads(result.text)
        except ValueError as exc:
            raise SourceMalformed(url, f"invalid JSON ({exc})", result.text) from exc
        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("rows") or []
        return payload if isinstance(payload, list) else []

    def _to_observations(self, bucket: str, url: str, rows: list[dict]) -> list[NormalizedObservation]:
        out: list[NormalizedObservation] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(
                row.get("title") or row.get("title_ne") or row.get("name") or ""
            ).strip()
            if not title:
                continue
            external_id = str(row.get("id") or f"{bucket}-{title[:40]}")
            body = str(row.get("description") or row.get("body") or row.get("content") or "").strip()
            published, date_source = _published_at(row, title)
            expiry, _ = _field_datetime(row.get("expiry_date"))
            place_match = resolve_place(f"{title} {body}")
            severity = _severity_for(title, body)
            out.append(
                NormalizedObservation(
                    source_code=self.code,
                    external_id=f"{bucket}-{external_id}",
                    kind=ObservationKind.OFFICIAL_ALERT,
                    subtype=bucket,
                    title=title[:480],
                    summary=(body or title)[:1800],
                    latitude=place_match.lat if place_match else None,
                    longitude=place_match.lng if place_match else None,
                    location_name=place_match.name if place_match else None,
                    district=place_match.district if place_match else None,
                    province=place_match.province if place_match else None,
                    incident_type=IncidentType.FLOOD,
                    event_time=published,
                    severity=severity.value,
                    source_url=url,
                    within_nepal=bool(place_match),
                    normalized_data={
                        "bulletin_type": bucket,
                        "treat_as_live": bucket == "alerts",
                        "file_name": row.get("file_name"),
                        "is_pdf_bulletin": bool(row.get("file_name")),
                        "published_date_source": date_source,
                        "expiry_date": expiry.isoformat() if expiry else None,
                        "location_precision": "named_place" if place_match else "unlocated",
                    },
                    raw_data=row,
                )
            )
        return out


def _field_datetime(value) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    parsed = parse_iso(str(value))
    return (parsed, "field") if parsed else (None, None)


def _published_at(row: dict, title: str) -> tuple[datetime | None, str]:
    """Real published time, or None. Never defaulted to 'now'.

    Some rows on this API carry Bikram Sambat calendar dates (BS 2085 = AD 2028),
    which land years ahead. A bulletin cannot be newer than the moment we read it,
    so a future date is dropped instead of trusted: the row then surfaces with no
    published time and freshness UNKNOWN rather than jumping to the top of a feed.
    """
    moment, origin = _read_published(row, title)
    if moment is not None and moment > utcnow() + timedelta(days=2):
        return None, f"future_dated:{origin}"
    return moment, origin


def _read_published(row: dict, title: str) -> tuple[datetime | None, str]:
    for field_name in ("published_date", "published_at", "created_at", "date"):
        moment, hit = _field_datetime(row.get(field_name))
        if moment:
            return moment, f"field:{field_name}"
    match = _TITLE_DATE.search(title or "")
    if match:
        day, month_text, year = match.group(1), match.group(2)[:3].lower(), match.group(3)
        month = _MONTHS.get(month_text)
        if month:
            try:
                return datetime(int(year), month, int(day)), "title"
            except ValueError:
                return None, "unparseable"
    return None, "absent"


def _severity_for(title: str, body: str) -> Severity:
    text = f"{title} {body}".lower()
    if any(k in text for k in ("danger", "extremely", "very heavy", "evacuat")):
        return Severity.SEVERE
    if any(k in text for k in ("warning", "heavy rain", "flood possible", "above warning")):
        return Severity.HIGH
    if "watch" in text or "light" in text or "notice" in text:
        return Severity.MODERATE
    return Severity.UNKNOWN


class HydrologyLevelAdapter:
    """Placeholder kept out of the catalogue: the gauge levels themselves come from
    DHM river-watch, which is the authoritative reading (see dhm.DhmRiverAdapter)."""

    @staticmethod
    def level_to_number(value) -> float | None:
        return clean_number(value)
