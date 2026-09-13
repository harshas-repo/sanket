"""Incident reads and the map feed.

The map is a projection of the same incidents the Response Center works on - one
source of truth, two layouts. Every feature carries its provenance and location
precision, because a marker placed on a district centroid must not look like a
surveyed coordinate.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.config import REPO_ROOT
from backend.app.deps import current_user, get_db, granted_permissions, has_permission, require_permission
from backend.app.models.core import Incident, User
from backend.app.services import community as community_service
from backend.app.services import incidents as incident_service
from backend.app.services import resources as resource_service
from backend.app.services import response_center as rc_service
from backend.app.services import signals as signal_service
from shared.timeutils import humanize_age, iso, utcnow

router = APIRouter(tags=["incidents"])


def _load(db: Session, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such incident")
    return incident


@router.get("/incidents")
def list_incidents(
    incident_type: str | None = None,
    district: str | None = None,
    urgency: str | None = None,
    evidence_state: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    only_within_nepal: bool = False,
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = rc_service.list_incidents(
        db,
        incident_type=incident_type,
        district=district,
        urgency=urgency,
        evidence_state=evidence_state,
        q=q,
        include_archived=include_archived and has_permission(user, "incidents:read"),
        only_within_nepal=only_within_nepal,
        limit=limit,
    )
    full = has_permission(user, "incidents:read")
    items = [
        rc_service.incident_summary(db, row) if full else _public(row)
        for row in rows
        if full or row.official_confirmation
    ]
    return {"count": len(items), "items": items, "generated_at": iso(utcnow())}


def _public(incident: Incident) -> dict[str, Any]:
    """The most a community account may see about an incident."""
    return {
        "id": incident.id,
        "ref_code": incident.ref_code,
        "title": incident.title,
        "incident_type": incident.incident_type,
        "district": incident.district,
        "province": incident.province,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "location_precision": incident.location_precision,
        "evidence_state": incident.evidence_state,
        "official_confirmation": incident.official_confirmation,
        "event_time": iso(incident.event_time),
        "last_updated_at": iso(incident.last_updated_at),
        "demo": incident.provenance == "demo",
    }


@router.get("/incidents/{incident_id}")
def incident_detail(
    incident_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load(db, incident_id)
    if has_permission(user, "incidents:read"):
        return rc_service.incident_detail(db, incident, granted_permissions(user))
    if not incident.official_confirmation:
        # A situation only the public reported is not published to other users:
        # showing it as fact is exactly the rumour this system must not amplify.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This incident is community-reported and is not published to community accounts yet",
        )
    return {"incident": _public(incident), "visibility": "official_only"}


@router.get("/incidents/{incident_id}/timeline")
def incident_timeline(
    incident_id: str,
    user: User = Depends(require_permission("incidents:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load(db, incident_id)
    return {"incident_id": incident.id, "events": incident_service.timeline(db, incident)}


@router.get("/incidents/{incident_id}/reports")
def incident_reports(
    incident_id: str,
    include_duplicates: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = _load(db, incident_id)
    rows = community_service.recent_reports(
        db, incident_id=incident.id, include_duplicates=include_duplicates, limit=limit
    )
    can_see_private = has_permission(user, "reports:read")
    items = [community_service.report_to_dict(db, row) for row in rows]
    if not can_see_private:
        items = [
            {
                "id": item["id"],
                "message": item["message"],
                "incident_type": item.get("incident_type"),
                "district": item.get("district"),
                "created_at": item.get("created_at"),
                "verification_status": item.get("verification_status"),
            }
            for item in items
        ]
    return {"count": len(items), "items": items}


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
@router.get("/map/incidents.geojson")
def map_incidents(
    hours: int = Query(default=168, ge=1, le=24 * 365, description="Only incidents updated in this window"),
    incident_type: str | None = None,
    district: str | None = None,
    bbox: str | None = Query(default=None, description="minLat,minLng,maxLat,maxLng"),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = rc_service.list_incidents(
        db, incident_type=incident_type, district=district, limit=limit
    )
    window = utcnow() - timedelta(hours=hours)
    box = _parse_bbox(bbox)
    official_only = not has_permission(user, "incidents:read")
    features: list[dict[str, Any]] = []
    for incident in rows:
        if incident.latitude is None or incident.longitude is None:
            continue
        if official_only and not incident.official_confirmation:
            continue
        if incident.last_updated_at is None or incident.last_updated_at < window:
            continue
        if box and not _in_bbox(incident.latitude, incident.longitude, box):
            continue
        impact = incident.impact or {}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [incident.longitude, incident.latitude],
                },
                "properties": {
                    "id": incident.id,
                    "ref_code": incident.ref_code,
                    "title": incident.title,
                    "incident_type": incident.incident_type,
                    "status": incident.status,
                    "severity": incident.severity,
                    "urgency": incident.urgency,
                    "evidence_state": incident.evidence_state,
                    "official_confirmation": incident.official_confirmation,
                    "impact_score": incident.impact_score,
                    "score_band": rc_service.impact_band(incident.impact_score or 0.0),
                    "freshness_state": impact.get("freshness_state", "unknown"),
                    "magnitude": incident.magnitude,
                    "deaths": impact.get("deaths", 0),
                    "injured": impact.get("injured", 0),
                    "affected_people": impact.get("affected_people", 0),
                    "district": incident.district,
                    "province": incident.province,
                    "location_precision": incident.location_precision,
                    "within_nepal": incident.within_nepal,
                    "community_report_count": incident.community_report_count,
                    "open_assistance_count": incident.open_assistance_count,
                    "needs_review": incident.needs_review,
                    "event_time": iso(incident.event_time),
                    # The two labels the incident payloads carry, repeated here on purpose: this
                    # is the other place a person asks "how old is this", and a browser cannot
                    # answer it. A rehearsal runs on a simulated clock, so only the server knows
                    # what "2 hours ago" measures against. Null when there is no stamp, rather
                    # than `humanize_age`'s English "no timestamp" sentence.
                    "event_time_label": (
                        humanize_age(incident.event_time) if incident.event_time else None
                    ),
                    "last_updated_at": iso(incident.last_updated_at),
                    "updated_label": (
                        humanize_age(incident.last_updated_at)
                        if incident.last_updated_at
                        else None
                    ),
                    "demo": incident.provenance == "demo",
                    # Where the record lives, not where to navigate. This one layer feeds both
                    # surfaces, and only the client knows whether it is drawing the console or
                    # the phone screen, so the screen route is composed there. It used to be
                    # called `detail_url`, which read like a link to open and would have taken
                    # a user to raw JSON.
                    "api_url": f"/api/incidents/{incident.id}",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "generated_at": iso(utcnow()),
        "meta": {
            "window_hours": hours,
            "returned": len(features),
            # What the client is told to encode, and what it actually does. This used to say
            # `colored_by: incident_type`; the markers are filled by urgency, because that is
            # the question a dispatcher asks of a dot, and the hazard kind is written next to it
            # in words. A claim about the rendering that the rendering does not honour is worse
            # than no claim, since someone will eventually build a legend from it.
            "sized_by": "impact_score",
            "colored_by": "urgency",
            "opacity_rule": "location_precision = district_centroid renders at reduced opacity",
        },
    }


@router.get("/map/signals.geojson")
def map_signals(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """District-level risk signals: conditions, not events. Rendered as polygons /
    hatched areas rather than markers so they are never mistaken for incidents."""
    active = signal_service.active_signals(db)
    features: list[dict[str, Any]] = []
    unplaced: list[str] = []
    for signal in active:
        if signal.latitude is None or signal.longitude is None:
            # A national roll-up has no single point. It is reported as unplaced instead
            # of being parked on Kathmandu, which would read as a claim about the valley.
            unplaced.append(signal.district or "National")
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [signal.longitude, signal.latitude],
                },
                "properties": signal_service.signal_to_dict(signal),
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "active_signals": len(active),
            "placed": len(features),
            "unplaced": unplaced,
            "note": "risk signals describe conditions in an area, not an event at a point",
        },
    }


@router.get("/map/resources.geojson")
def map_resources(
    resource_type: str | None = None,
    district: str | None = None,
    availability: str | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Facility layer. An empty catalogue says so instead of pretending the map is
    finished - the layer being switchable is not evidence that it has data."""
    rows = resource_service.list_resources(
        db, resource_type=resource_type, district=district, availability=availability, limit=limit
    )
    collection = resource_service.geojson(rows)
    total = resource_service.counts(db)
    collection["generated_at"] = iso(utcnow())
    collection["meta"] = {
        "returned": len(collection["features"]),
        "in_catalogue": total["total"],
        "unplaced_in_page": len(rows) - len(collection["features"]),
        "catalogue_counts": total,
        "seed": resource_service.seed_status(),
        "availability_note": (
            f"availability older than {resource_service.AVAILABILITY_TRUST_HOURS}h is "
            "reported as 'unknown'; never show an unconfirmed facility as open"
        ),
    }
    if not collection["features"]:
        collection["meta"]["empty_reason"] = (
            "No facility has been seeded or entered yet. Run POST /api/rc/resources/seed "
            "or add facilities in the Response Center."
        )
    return collection


# Published as URLs, not file paths: the boundary files used to be described as
# "Data/geo/nepal_districts.geojson (official DHM)", which a browser cannot open, and the
# `available` flag means the map never discovers a missing boundary by hitting a 404.
_BOUNDARY_FILES = [
    ("districts", "District boundaries", "nepal_districts.geojson", "Survey Department / DHM boundary"),
    ("provinces", "Province boundaries", "nepal_provinces.geojson", "geoBoundaries ADM1"),
    ("boundary", "National boundary", "nepal_boundary.geojson", "geoBoundaries ADM0"),
    ("rivers", "River network", "nepal_rivers.geojson", "OSM river lines, for context only"),
]


def _vector_layers() -> list[dict[str, Any]]:
    layers = []
    for layer_id, label, filename, provenance in _BOUNDARY_FILES:
        path = REPO_ROOT / "Data" / "geo" / filename
        layers.append(
            {
                "id": layer_id,
                "label": label,
                "url": f"/geo/{filename}" if path.is_file() else None,
                "provenance": provenance,
                "available": path.is_file(),
            }
        )
    return layers


@router.get("/map/layers")
def map_layers() -> dict[str, Any]:
    """Layer catalogue the map builds itself from - one place to change a legend."""
    return {
        "basemap": {
            "id": "osm-raster",
            "label": "OpenStreetMap tiles",
            "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "© OpenStreetMap contributors",
            "note": "Raster tiles need the internet. Offline mode shows boundaries only.",
        },
        "vector_layers": _vector_layers(),
        # Every overlay names the URL it draws from. Three of them used to be listed by name
        # only, which left a map to invent a path or draw nothing; `geometry` says what to
        # read when the response is a JSON list rather than a GeoJSON layer, and
        # `staff_only` marks the ones a community account cannot fetch.
        "overlays": [
            {"id": "incidents", "label": "Incidents (sized by impact)", "default": True,
             "url": "/api/map/incidents.geojson"},
            {"id": "signals", "label": "Risk signals by district", "default": True,
             "url": "/api/map/signals.geojson"},
            {"id": "resources", "label": "Verified facilities", "default": False,
             "url": "/api/map/resources.geojson"},
            # 100 is this endpoint's own ceiling (`le=100`); asking for more is a 422, and a
            # layer URL that does not answer is worse than no URL at all.
            {"id": "alerts", "label": "Official alerts", "default": False,
             "url": "/api/alerts?limit=100", "geometry": "point from the alert's own coordinates, when it has any",
             "note": "alerts describe an area in words; there is no alert footprint to draw"},
            {"id": "reports", "label": "Community reports", "default": False,
             "url": "/api/rc/reports?limit=200", "geometry": "latitude / longitude on each item",
             "staff_only": True},
            {"id": "requests", "label": "Open help requests", "default": False,
             "url": "/api/rc/requests?limit=200", "geometry": "latitude / longitude on each item",
             "staff_only": True},
        ],
        "legend": {
            "evidence_states": [
                "officially_confirmed",
                "officially_reported",
                "corroborated",
                "community_reported",
                "conflicting",
                "unverified",
            ],
            "location_precision": [
                "source_coordinate",
                "named_place",
                "local_level",
                "district_centroid",
                "user_shared",
                "unlocated",
            ],
            "freshness_states": ["fresh", "recent", "aging", "stale", "unknown"],
        },
    }


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    try:
        parts = [float(piece) for piece in value.split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    min_lat, min_lng, max_lat, max_lng = parts
    return min_lat, min_lng, max_lat, max_lng


def _in_bbox(lat: float, lng: float, box: tuple[float, float, float, float]) -> bool:
    min_lat, min_lng, max_lat, max_lng = box
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng
