"""Catalogue of official data sources.

Each entry records what the source *actually* provides and how it is accessed.
The endpoints below were inspected against the live sites during source
discovery - none of them are guessed. `access_notes` records the awkward
realities (plain HTTP only, PHP notices inside JSON, 12 MB pages) so adapters and
operators share the same understanding.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    code: str
    name: str
    organization: str
    source_type: str
    official: bool
    url: str
    refresh_interval_seconds: int
    stale_after_seconds: int
    machine_readable: bool
    access_notes: str
    fields: list[str] = field(default_factory=list)
    portal_url: str = ""
    adapter: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SOURCE_CATALOG: dict[str, SourceSpec] = {
    "usgs": SourceSpec(
        code="usgs",
        name="USGS Earthquake Events (Nepal region)",
        organization="United States Geological Survey",
        source_type="api",
        official=True,
        url="https://earthquake.usgs.gov/fdsnws/event/1/query",
        refresh_interval_seconds=300,
        stale_after_seconds=1800,
        machine_readable=True,
        access_notes=(
            "Official FDSN event service, GeoJSON. Used as a secondary/cross-validation "
            "seismic source and as fallback when NEMRC is unreachable."
        ),
        fields=[
            "magnitude", "place", "time", "latitude", "longitude", "depth",
            "felt_reports", "significance", "tsunami", "status",
        ],
        portal_url="https://earthquake.usgs.gov/earthquakes/map/",
        adapter="data_ingestion.sources.usgs",
    ),
    "nemrc": SourceSpec(
        code="nemrc",
        name="NEMRC Recent Earthquakes (Seismo Nepal)",
        organization="National Earthquake Monitoring and Research Center, Nepal",
        source_type="inline_json",
        official=True,
        url="https://seismonepal.gov.np/en/earthquakes/map",
        refresh_interval_seconds=600,
        stale_after_seconds=86400,
        machine_readable=True,
        access_notes=(
            "No public JSON endpoint. The map page embeds `const earthquakes = [...]` "
            "with BS + AD dates, UTC time, lat/lng, ML magnitude, epicentre and survey. "
            "Parsed from the HTML. `seismo.gov.np` does not resolve; the live host is "
            "`seismonepal.gov.np`."
        ),
        fields=["date_ad", "date", "time", "time_utc", "latitude", "longitude",
                "magnitude", "epicenter", "created_at", "updated_at"],
        portal_url="https://seismonepal.gov.np/en",
        adapter="data_ingestion.sources.nemrc",
    ),
    "dhm_rainfall": SourceSpec(
        code="dhm_rainfall",
        name="DHM Rainfall Stations",
        organization="Department of Hydrology and Meteorology, Nepal",
        source_type="api",
        official=True,
        url="https://dhm.gov.np/hydrology/getRainfallFilter",
        refresh_interval_seconds=1800,
        stale_after_seconds=21600,
        machine_readable=True,
        access_notes=(
            "POST form-encoded {type:0, mapValue:all, hour:24} returns JSON for ~377 "
            "stations with lat/lng, district, basin and accumulated mm. Requires "
            "X-Requested-With: XMLHttpRequest. No history API exists - time series must "
            "be archived by Sanket."
        ),
        fields=["station", "district", "basin", "latitude", "longitude", "value_mm",
                "interval_hours", "status", "observed_at"],
        portal_url="https://www.dhm.gov.np/rainfall-and-temperature-station-data",
        adapter="data_ingestion.sources.dhm",
    ),
    "dhm_rivers": SourceSpec(
        code="dhm_rivers",
        name="DHM River Water Level Gauges",
        organization="Department of Hydrology and Meteorology, Nepal",
        source_type="inline_json",
        official=True,
        url="https://dhm.gov.np/hydrology/river-watch",
        refresh_interval_seconds=900,
        stale_after_seconds=3600,
        machine_readable=True,
        access_notes=(
            "Server-rendered page (~12 MB) embedding `const data = [...]` with 171 "
            "gauges: current level, official warning level, official danger level, "
            "trend and a 15-minute time series. Parsed with a bracket scanner; the "
            "page is never rendered."
        ),
        fields=["station", "basin", "district", "water_level", "warning_level",
                "danger_level", "steady", "status", "datetime", "time_series"],
        portal_url="https://www.dhm.gov.np/hydrology/river-watch",
        adapter="data_ingestion.sources.dhm",
    ),
    "hydrology_alerts": SourceSpec(
        code="hydrology_alerts",
        name="Flood Forecasting & Early Warning Alerts",
        organization="Flood Forecasting and Early Warning Service, DHM",
        source_type="api",
        official=True,
        url="https://hydrology.gov.np/cm/api-public/alerts",
        refresh_interval_seconds=900,
        stale_after_seconds=86400,
        machine_readable=True,
        access_notes=(
            "Clean public JSON API. Returns [] when there is no active alert - that is a "
            "valid live answer, not a failure. `flood.gov.np`/`flood.dhm.gov.np` do not "
            "resolve; the live host is `hydrology.gov.np`."
        ),
        fields=["title", "body", "published", "severity", "districts", "file"],
        portal_url="https://hydrology.gov.np/",
        adapter="data_ingestion.sources.hydrology",
    ),
    "drr": SourceSpec(
        code="drr",
        name="Nepal Disaster Risk Reduction Portal - Incident Register",
        organization="MoHA / Disaster Assistance and Research Division, Nepal",
        source_type="html",
        official=True,
        url="http://drrportal.gov.np/incidentreport/index_ajax",
        refresh_interval_seconds=7200,
        stale_after_seconds=604800,
        machine_readable=True,
        access_notes=(
            "CodeIgniter app. HTTPS fails the TLS handshake, so plain HTTP is used. "
            "POST parameters=<json filter> returns an HTML table fragment (27 columns, "
            "~63k historical records). PHP notices are prepended to responses and must "
            "be stripped. District and incident-type filter vocabularies scraped from the "
            "search form."
        ),
        fields=["district", "local_level", "incident_type", "incident_date", "deaths",
                "missing", "injured", "affected_families", "houses_damaged", "displaced",
                "estimated_loss", "place", "remarks"],
        portal_url="http://drrportal.gov.np/incidentreport",
        adapter="data_ingestion.sources.drr",
    ),
    "drr_highway": SourceSpec(
        code="drr_highway",
        name="Daily Highway / Road Status Bulletin",
        organization="MoHA Disaster Risk Reduction Portal",
        source_type="pdf",
        official=True,
        url="http://drrportal.gov.np/publication",
        refresh_interval_seconds=21600,
        stale_after_seconds=86400,
        machine_readable=False,
        access_notes=(
            "The only routinely-updated official road-status product found. Published as "
            "a PDF daily at 07:00 Nepali time (e.g. document/2882.pdf). Requires a PDF "
            "parser to become structured; until then the adapter records document "
            "presence and links only, and the UI shows 'not machine readable'."
        ),
        fields=["document_id", "title", "published_date", "pdf_url"],
        portal_url="http://drrportal.gov.np/publication",
        adapter="data_ingestion.sources.roads",
    ),
    "dor": SourceSpec(
        code="dor",
        name="Department of Roads Notices",
        organization="Department of Roads, Nepal",
        source_type="html",
        official=True,
        url="https://dor.gov.np/home/notices",
        refresh_interval_seconds=86400,
        stale_after_seconds=604800,
        machine_readable=False,
        access_notes=(
            "NO machine-readable road-status API found. Notices are HTML tables pointing "
            "at PDFs; the 'Road Notice' PDF is the real content. `ssrn.dor.gov.np` was "
            "unreachable from this network and needs re-testing. Adapter therefore emits "
            "observations only from parseable notice metadata and reports the rest as "
            "unavailable."
        ),
        fields=["notice_title", "office", "published_date", "attachment_url"],
        portal_url="https://dor.gov.np/",
        adapter="data_ingestion.sources.roads",
    ),
}

# Rows written by Sanket itself still live in OBSERVATIONS, and `source_id` is a
# foreign key to SOURCES, so they need registered source rows too. They are never
# polled, never marked `official`, and the evidence engine excludes them from
# anything that could confirm a situation.
INTERNAL_SOURCES: dict[str, SourceSpec] = {
    "community": SourceSpec(
        code="community",
        name="Community Reports",
        organization="Sanket users",
        source_type="internal",
        official=False,
        url="/community/report",
        refresh_interval_seconds=0,
        stale_after_seconds=21600,
        machine_readable=True,
        access_notes=(
            "In-app submissions. Stored with their own provenance and correlated into "
            "the shared situation by code; a community report can corroborate but can "
            "never make something officially confirmed."
        ),
        fields=["report_type", "message", "urgency", "verification_status"],
    ),
    "demo": SourceSpec(
        code="demo",
        name="Demo Scenario",
        organization="Sanket demonstration data",
        source_type="internal",
        official=False,
        url="/api/demo",
        refresh_interval_seconds=0,
        stale_after_seconds=86400,
        machine_readable=True,
        access_notes=(
            "Synthetic rows created only while demo mode is armed. Every one is labelled "
            "'Demo Data' in the interface and they are removed when demo mode is cleared."
        ),
        fields=["scenario_id", "label"],
    ),
}

STATIC_GEODATA: dict[str, dict[str, str]] = {
    "districts": {
        "label": "Nepal 77 district boundaries (official DHM)",
        "url": "https://dhm.gov.np/assets/frontend/geo/district77.geojson",
        "file": "nepal_districts.geojson",
        "hops": None,
    },
    "boundary": {
        "label": "Nepal national boundary (geoBoundaries ADM0, public domain)",
        "url": "https://www.geoboundaries.org/api/current/gbOpen/NPL/ADM0/",
        "file": "nepal_boundary.geojson",
        "hops": "gjDownloadURL",
    },
    "provinces": {
        "label": "Nepal province boundaries (geoBoundaries ADM1, public domain)",
        "url": "https://www.geoboundaries.org/api/current/gbOpen/NPL/ADM1/",
        "file": "nepal_provinces.geojson",
        "hops": "gjDownloadURL",
    },
    "rivers": {
        "label": "Nepal river network (official DHM)",
        "url": "https://dhm.gov.np/assets/frontend/geo/River_All.geojson",
        "file": "nepal_rivers.geojson",
        "hops": None,
    },
}


def catalog_dict() -> dict[str, dict[str, Any]]:
    return {code: spec.as_dict() for code, spec in SOURCE_CATALOG.items()}
