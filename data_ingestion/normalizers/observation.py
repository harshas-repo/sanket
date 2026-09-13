"""Normalized observation record - the single internal shape every adapter emits.

Adapters never write to the database directly and never invent fields: anything
the source did not provide stays None, so the UI can say "depth not reported"
instead of showing a plausible-looking zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shared.enums import IncidentType, ObservationKind


@dataclass
class NormalizedObservation:
    source_code: str
    external_id: str
    kind: ObservationKind
    title: str = ""
    summary: str = ""
    latitude: float | None = None
    longitude: float | None = None
    location_name: str | None = None
    district: str | None = None
    province: str | None = None
    local_municipality: str | None = None
    within_nepal: bool = False
    incident_type: IncidentType | None = None
    event_time: datetime | None = None
    severity: str | None = None
    magnitude: float | None = None
    depth_km: float | None = None
    value: float | None = None
    unit: str | None = None
    threshold_state: str | None = None
    trend: str | None = None
    source_url: str | None = None
    subtype: str | None = None
    deaths: int = 0
    missing: int = 0
    injured: int = 0
    affected_people: int = 0
    houses_damaged: int = 0
    provenance: str = "official"
    raw_data: dict[str, Any] = field(default_factory=dict)
    normalized_data: dict[str, Any] = field(default_factory=dict)

    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def key(self) -> tuple[str, str]:
        return (self.source_code, self.external_id)


def clean_number(value: Any) -> float | None:
    if value in (None, "", "-", "--", "N/A", "null"):
        return None
    try:
        out = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # drop NaN


def clean_int(value: Any) -> int:
    number = clean_number(value)
    if number is None:
        return 0
    try:
        return int(round(number))
    except (OverflowError, ValueError):
        return 0


class SourceAdapter:
    """Base class. Subclasses implement `fetch_observations()`."""

    code: str = ""

    def __init__(self, spec: Any | None = None, settings: Any | None = None):
        from data_ingestion.sources.catalog import SOURCE_CATALOG

        self.spec = spec or SOURCE_CATALOG[self.code]
        self.settings = settings

    def fetch_observations(self) -> list[NormalizedObservation]:  # pragma: no cover - interface
        raise NotImplementedError

    @staticmethod
    def norm(value: NormalizedObservation) -> NormalizedObservation:
        return value
