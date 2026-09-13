"""Adapter registry - keeps source-specific logic isolated and replaceable."""

from __future__ import annotations

from data_ingestion.normalizers.observation import NormalizedObservation, SourceAdapter
from data_ingestion.sources.catalog import INTERNAL_SOURCES, SOURCE_CATALOG, SourceSpec
from data_ingestion.sources.dhm import DhmRainfallAdapter, DhmRiverAdapter
from data_ingestion.sources.drr import DrrIncidentAdapter
from data_ingestion.sources.hydrology import HydrologyAlertAdapter
from data_ingestion.sources.nemrc import NemrcEarthquakeAdapter
from data_ingestion.sources.roads import DorNoticeAdapter, DrrHighwayBulletinAdapter
from data_ingestion.sources.usgs import UsgsEarthquakeAdapter

ADAPTER_CLASSES: dict[str, type[SourceAdapter]] = {
    "usgs": UsgsEarthquakeAdapter,
    "nemrc": NemrcEarthquakeAdapter,
    "dhm_rainfall": DhmRainfallAdapter,
    "dhm_rivers": DhmRiverAdapter,
    "hydrology_alerts": HydrologyAlertAdapter,
    "drr": DrrIncidentAdapter,
    "drr_highway": DrrHighwayBulletinAdapter,
    "dor": DorNoticeAdapter,
}

__all__ = [
    "ADAPTER_CLASSES",
    "SOURCE_CATALOG",
    "INTERNAL_SOURCES",
    "SourceSpec",
    "NormalizedObservation",
    "SourceAdapter",
    "build_adapter",
    "build_all_adapters",
]


def build_adapter(code: str, settings=None) -> SourceAdapter | None:
    cls = ADAPTER_CLASSES.get(code)
    spec = SOURCE_CATALOG.get(code)
    if not cls or not spec:
        return None
    kwargs: dict[str, object] = {"spec": spec, "settings": settings}
    if cls is UsgsEarthquakeAdapter and settings is not None:
        kwargs.update(
            lookback_days=getattr(settings, "usgs_lookback_days", 7),
            min_magnitude=getattr(settings, "usgs_min_magnitude", 3.0),
        )
    if cls is DrrIncidentAdapter and settings is not None:
        kwargs.update(lookback_days=getattr(settings, "drr_lookback_days", 45))
    return cls(**kwargs)


def build_all_adapters(settings=None) -> list[tuple[SourceSpec, SourceAdapter]]:
    pairs: list[tuple[SourceSpec, SourceAdapter]] = []
    for code in SOURCE_CATALOG:
        adapter = build_adapter(code, settings)
        if adapter:
            pairs.append((SOURCE_CATALOG[code], adapter))
    return pairs
