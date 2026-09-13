"""Resource catalogue: facilities, teams and the answer to "where do we send them".

The rule that shapes this whole module is that a *missing* resource is better than an
invented one. A Response Center that believes there is a 200-bed hospital at a
coordinate will dispatch to it. So:

* rows come from OpenStreetMap through Overpass, or from an identified operator - never
  from a model, and never from a plausible-looking default;
* a contact is shown only with the source it came from and `contact_verified=False`
  until a human has actually rung it;
* capacity is only ever what a dataset or an operator stated;
* availability that nobody has confirmed decays to `unknown` instead of lingering as a
  cheerful "available".

An empty catalogue is reported as empty. `match_resources()` returns nothing at all
rather than padding the list.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.geo.boundaries import boundary_index
from backend.app.models.core import Resource, User
from backend.app.services import audit
from data_ingestion.http_fetch import SourceMalformed, SourceUnavailable, fetch
from shared.enums import AuditAction, ResourceType
from shared.timeutils import humanize_age, iso, utcnow

logger = logging.getLogger("sanket.resources")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nepal's bounding box, generous enough to catch stations just over the borders that
# people in border districts actually reach for.
NEPAL_BBOX = (26.35, 80.00, 30.45, 88.25)

# How many of each kind a seed run pulls in. Overpass is a shared public service and a
# nationwide `amenity=hospital` query is already tens of thousands of elements.
TYPE_QUERIES: list[tuple[str, dict[str, str], int]] = [
    (ResourceType.HOSPITAL.value, {"amenity": "hospital"}, 400),
    (ResourceType.HEALTH_POST.value, {"amenity": "clinic"}, 400),
    (ResourceType.POLICE.value, {"amenity": "police"}, 400),
    (ResourceType.FIRE.value, {"amenity": "fire_station"}, 200),
    (ResourceType.SHELTER.value, {"emergency": "shelter"}, 400),
    (ResourceType.HELIPAD.value, {"aeroway": "helipad"}, 200),
    (ResourceType.WATER_SUPPLY.value, {"man_made": "water_tower"}, 200),
]

# Availability stops being believable after this long without a human confirming it.
AVAILABILITY_TRUST_HOURS = 12

PROVENANCE_OPEN_DATA = "open_data"
PROVENANCE_OPERATOR = "operator"
# Only the demo engine may produce these. A synthetic facility has to be separable from
# a real one in the database itself, not only in a UI label.
PROVENANCE_DEMO = "demo"


def _bbox_filter() -> str:
    south, west, north, east = NEPAL_BBOX
    return f'({south},{west},{north},{east})'


def build_query(tags: dict[str, str], limit: int) -> str:
    conditions = ", ".join(f'"{key}"="{value}"' for key, value in tags.items())
    # Every statement inside a union block must end with ';'. Without it Overpass answers
    # 400 "';' expected - ')' found", and `out center` is needed because a hospital mapped
    # as a building *way* carries no node of its own.
    return (
        f'[out:json][timeout:60];'
        f'('
        f'nwr[{conditions}]{_bbox_filter()};'
        f');out center {limit};'
    )


def _osm_element_to_fields(kind: str, element: dict[str, Any]) -> dict[str, Any] | None:
    lat = element.get("lat")
    lng = element.get("lon")
    if lat is None or lng is None:
        center = element.get("center") or {}
        lat, lng = center.get("lat"), center.get("lon")
    if lat is None or lng is None:
        return None  # an unlocated facility cannot be dispatched to
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("name:en") or "").strip()
    if not name:
        return None  # anonymous nodes are noise; a map of "hospital" x 400 helps nobody
    capacity: int | None = None
    for key in ("beds", "capacity"):
        raw = tags.get(key)
        if raw and str(raw).isdigit():
            capacity = int(raw)
            break
    osm_type, osm_id = element.get("type"), element.get("id")
    return {
        "latitude": float(lat),
        "longitude": float(lng),
        "name": name[:256],
        "description": " ".join(
            value for value in (tags.get("operator"), tags.get("addr:street")) if value
        )[:1000],
        "address": ", ".join(
            value
            for value in (
                tags.get("addr:street"),
                tags.get("addr:city"),
                tags.get("addr:district"),
            )
            if value
        )
        or None,
        "contact": (tags.get("phone") or tags.get("contact") or None),
        "capacity": capacity,
        "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        "attributes": {
            "osm_type": osm_type,
            "osm_id": osm_id,
            "osm_tags": {k: v for k, v in tags.items() if len(k) < 40},
            "seeded_via": "overpass",
            "seeded_query_kind": kind,
        },
    }


def _error_excerpt(body: str) -> str:
    """Overpass explains a rejected query as XHTML. Keep the sentence, drop the markup -
    the operator has to be able to read why a kind of facility is missing."""
    text = " ".join(re.sub(r"<[^>]+>", " ", body or "").split())
    for marker in ("Error", "error"):
        at = text.find(marker)
        if at >= 0:
            return text[at : at + 240]
    return text[:240]


def seed_from_overpass(
    db: Session,
    *,
    actor_id: str | None = None,
    types: list[str] | None = None,
    timeout: float = 90.0,
    pause_seconds: float = 20.0,
) -> dict[str, Any]:
    """Fill the catalogue from OpenStreetMap. Reports exactly what it managed to do.

    Never raises for an unreachable Overpass: the caller has to be able to show the
    operator "seed failed, here is why" instead of an empty screen.

    Overpass is a shared public service and it throttles nationwide bounding-box queries
    (429 "Dispatcher_Client::request_read_and_idx::rate_limit" was seen on the third
    back-to-back request in one run). So the kinds are spaced apart and a throttle is
    retried with a backoff instead of being written off as a failure.
    """
    selected = [row for row in TYPE_QUERIES if types is None or row[0] in set(types)]
    result: dict[str, Any] = {
        "ok": True,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "per_type": {},
        "failures": [],
        "started_at": iso(utcnow()),
    }
    known = _osm_index(db)
    for index, (resource_type, tags, limit) in enumerate(selected):
        if index:
            time.sleep(pause_seconds)
        query = build_query(tags, limit)
        try:
            response = fetch(
                OVERPASS_URL,
                method="POST",
                data={"data": query},
                timeout=timeout,
                retries=2,
                retry_statuses=(429, 503, 504),
            )
            if not response.ok:
                raise SourceMalformed(
                    OVERPASS_URL,
                    f"HTTP {response.status_code} - {_error_excerpt(response.text)}",
                    response.text[:400],
                )
            payload = json.loads(response.text)
        except (SourceUnavailable, SourceMalformed, ValueError) as exc:
            # One kind failing must not erase the kinds that worked.
            result["failures"].append({"resource_type": resource_type, "error": str(exc)[:300]})
            logger.warning("overpass seed failed for %s: %s", resource_type, exc)
            continue

        created = skipped = 0
        updated = 0
        for element in payload.get("elements", []):
            fields = _osm_element_to_fields(resource_type, element)
            if fields is None:
                skipped += 1
                continue
            osm_type = element.get("type")
            existed = known.get((str(osm_type), str(element.get("id"))))
            if existed is None:
                resolution = boundary_index.resolve_point(fields["latitude"], fields["longitude"])
                fields["attributes"] = {**fields["attributes"], "district_from": resolution.precision}
                resource = Resource(
                    resource_type=resource_type,
                    district=resolution.district,
                    province=resolution.province,
                    availability="unknown",
                    source="openstreetmap",
                    provenance=PROVENANCE_OPEN_DATA,
                    contact_verified=False,
                    last_updated=utcnow(),
                    **fields,
                )
                db.add(resource)
                known[(str(osm_type), str(element.get("id")))] = resource
                created += 1
            else:
                for key, value in fields.items():
                    if key != "attributes" and value:
                        setattr(existed, key, value)
                existed.attributes = fields["attributes"]
                existed.last_updated = utcnow()
                updated += 1
        db.commit()
        result["created"] += created
        result["updated"] += updated
        result["skipped"] += skipped
        result["per_type"][resource_type] = {"created": created, "updated": updated, "skipped": skipped}

    result["ok"] = not result["failures"]
    # A run where 3 of 7 kinds died saved some facilities and lost the rest. Calling that
    # "complete" is how a half-empty map gets presented as a finished one.
    result["partial"] = bool(result["failures"]) and (result["created"] + result["updated"]) > 0
    result["attempted"] = len(selected)
    # The actor is re-read in this session: an instance attached to the request's
    # session cannot be carried into a worker thread.
    actor = db.get(User, actor_id) if actor_id else None
    audit.record(
        db,
        action=AuditAction.RESOURCE_UPDATE,
        entity_type=audit.ENTITY_SOURCE,
        entity_id="overpass",
        actor=actor,
        actor_kind="operator" if actor else "system",
        new={
            "created": result["created"],
            "updated": result["updated"],
            "failures": [row["resource_type"] for row in result["failures"]],
        },
        reason="seeded facility catalogue from OpenStreetMap",
        commit=True,
    )
    return result


def _osm_index(db: Session) -> dict[tuple[str, str], Resource]:
    """(osm_type, osm_id) -> row, built once per seed run.

    OpenStreetMap identities are the only stable key a re-seed can match on. Looking this
    up per element would re-scan the table thousands of times, so it is loaded as a dict
    and extended as the run inserts new rows.
    """
    index: dict[tuple[str, str], Resource] = {}
    for row in db.execute(select(Resource).where(Resource.source == "openstreetmap")).scalars():
        attributes = row.attributes or {}
        if attributes.get("osm_id") is not None:
            index[(str(attributes.get("osm_type")), str(attributes.get("osm_id")))] = row
    return index


# --------------------------------------------------------------------------- #
# Seeding as a background task
# --------------------------------------------------------------------------- #
# A nationwide Overpass pull takes minutes, which is too long for an HTTP request and
# too important to fail silently. It runs on a daemon thread of this process and the
# Response Center polls what that thread last said. That is deliberately *not* a job
# queue: one operator, one laptop, one seed at a time - `start_seed` says so if a run is
# already going rather than queueing a second hammer on a shared public service.

_SEED_LOCK = threading.Lock()
_SEED_RUN: dict[str, Any] = {"state": "idle", "started_at": None, "finished_at": None, "result": None}


def seed_status() -> dict[str, Any]:
    status = {**_SEED_RUN, "state_label": _STATE_LABELS.get(_SEED_RUN["state"], _SEED_RUN["state"])}
    result = _SEED_RUN.get("result") or {}
    if result.get("failures"):
        status["failed_types"] = [row["resource_type"] for row in result["failures"]]
    return status


_STATE_LABELS = {
    "idle": "no seed has run since this process started",
    "running": "seeding OpenStreetMap now",
    "complete": "every facility kind was fetched",
    "partial": "some facility kinds failed - the catalogue is incomplete",
    "failed": "seeding did not produce any facilities",
}


def _seed_state(outcome: dict[str, Any]) -> str:
    if outcome.get("ok"):
        return "complete"
    return "partial" if outcome.get("partial") else "failed"


def start_seed(
    *, actor_id: str | None = None, types: list[str] | None = None, timeout: float = 90.0
) -> dict[str, Any]:
    if _SEED_RUN["state"] == "running":
        return {"started": False, "reason": "a seed run is already in progress", **seed_status()}

    def work() -> None:
        from backend.app.db import SessionLocal

        session = SessionLocal()
        try:
            outcome = seed_from_overpass(session, actor_id=actor_id, types=types, timeout=timeout)
            with _SEED_LOCK:
                _SEED_RUN.update(
                    state=_seed_state(outcome),
                    finished_at=iso(utcnow()),
                    result=outcome,
                )
        except Exception as exc:  # a thread that dies quietly is the worst possible failure
            logger.exception("resource seeding crashed")
            with _SEED_LOCK:
                _SEED_RUN.update(
                    state="failed", finished_at=iso(utcnow()), result={"error": str(exc)[:400]}
                )
        finally:
            session.close()

    with _SEED_LOCK:
        _SEED_RUN.update(state="running", started_at=iso(utcnow()), finished_at=None, result=None)
    threading.Thread(target=work, name="sanket-seed-resources", daemon=True).start()
    return {"started": True, **seed_status()}


def create(
    db: Session,
    *,
    actor: User,
    resource_type: str,
    name: str,
    latitude: float | None = None,
    longitude: float | None = None,
    address: str | None = None,
    contact: str | None = None,
    capacity: int | None = None,
    availability: str = "unknown",
    description: str = "",
    district: str | None = None,
    attributes: dict[str, Any] | None = None,
    provenance: str = PROVENANCE_OPERATOR,
) -> Resource:
    """An operator typing in a facility they know about.

    Recorded as `operator` provenance, not as official open data: if this turns out to be
    wrong, the audit log says whose judgement it was.
    """
    resolution = boundary_index.resolve_point(latitude, longitude)
    resource = Resource(
        resource_type=resource_type,
        name=name.strip()[:256],
        description=description.strip()[:1000],
        latitude=latitude,
        longitude=longitude,
        address=address,
        district=district or resolution.district,
        province=resolution.province,
        contact=contact,
        contact_verified=bool(contact),
        capacity=capacity,
        availability=availability,
        availability_verified_at=utcnow() if availability != "unknown" else None,
        source="operator",
        provenance=provenance,
        attributes={**(attributes or {}), "entered_by": actor.display_name or actor.username},
        last_updated=utcnow(),
    )
    db.add(resource)
    db.flush()
    audit.record(
        db,
        action=AuditAction.RESOURCE_UPDATE,
        entity_type=audit.ENTITY_RESOURCE,
        entity_id=resource.id,
        actor=actor,
        actor_kind="operator",
        new={"name": resource.name, "resource_type": resource.resource_type, "capacity": capacity},
        reason="operator-entered facility",
    )
    db.commit()
    db.refresh(resource)
    return resource


def set_availability(
    db: Session, resource: Resource, actor: User, availability: str, *, capacity_left: int | None = None,
    contact_verified: bool | None = None, reason: str = "",
) -> Resource:
    previous = {
        "availability": resource.availability,
        "capacity": resource.capacity,
        "contact_verified": resource.contact_verified,
    }
    resource.availability = availability
    resource.availability_verified_at = utcnow()
    if capacity_left is not None:
        resource.capacity = capacity_left
    if contact_verified is not None:
        resource.contact_verified = contact_verified
    resource.last_updated = utcnow()
    audit.record(
        db,
        action=AuditAction.RESOURCE_UPDATE,
        entity_type=audit.ENTITY_RESOURCE,
        entity_id=resource.id,
        actor=actor,
        actor_kind="operator",
        previous=previous,
        new={
            "availability": resource.availability,
            "capacity": resource.capacity,
            "contact_verified": resource.contact_verified,
        },
        reason=reason or None,
        commit=True,
    )
    return resource


def deactivate(
    db: Session, resource: Resource, actor: User, *, reason: str = "", commit: bool = True
) -> Resource:
    """Retire a facility without deleting the evidence that it was ever listed.

    A wrong entry has to stop appearing on the map, but the row stays so the audit trail
    can still say who listed it and who took it back down.
    """
    previous = {"active": resource.active, "availability": resource.availability}
    resource.active = False
    # Nothing retired from the map may still claim to be open somewhere else.
    resource.availability = "unknown"
    resource.last_updated = utcnow()
    audit.record(
        db,
        action=AuditAction.RESOURCE_UPDATE,
        entity_type=audit.ENTITY_RESOURCE,
        entity_id=resource.id,
        actor=actor,
        actor_kind="operator",
        previous=previous,
        new={"active": False, "availability": "unknown"},
        reason=reason or "facility retired",
        commit=commit,
    )
    if commit:
        db.commit()
    db.refresh(resource)
    return resource


def decay_stale_availability(db: Session) -> int:
    """An unconfirmed "available" is a guess with an expiry date on it."""
    cutoff = utcnow() - timedelta(hours=AVAILABILITY_TRUST_HOURS)
    rows = list(
        db.execute(
            select(Resource).where(
                Resource.availability != "unknown",
                Resource.active.is_(True),
                func.coalesce(Resource.availability_verified_at, Resource.last_updated) < cutoff,
            )
        ).scalars()
    )
    for resource in rows:
        resource.attributes = {
            **(resource.attributes or {}),
            "availability_before_decay": resource.availability,
            "availability_decay_reason": f"unconfirmed for over {AVAILABILITY_TRUST_HOURS}h",
        }
        resource.availability = "unknown"
    if rows:
        db.commit()
    return len(rows)


def list_resources(
    db: Session,
    *,
    resource_type: str | None = None,
    district: str | None = None,
    availability: str | None = None,
    include_inactive: bool = False,
    limit: int = 500,
) -> list[Resource]:
    stmt = select(Resource)
    if not include_inactive:
        stmt = stmt.where(Resource.active.is_(True))
    if resource_type:
        stmt = stmt.where(Resource.resource_type == resource_type)
    if district:
        stmt = stmt.where(func.lower(Resource.district) == district.strip().lower())
    if availability:
        stmt = stmt.where(Resource.availability == availability)
    return list(
        db.execute(stmt.order_by(Resource.district.asc().nullslast(), Resource.name.asc()).limit(limit)).scalars()
    )


def counts(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(Resource.resource_type, Resource.availability, func.count())
        .group_by(Resource.resource_type, Resource.availability)
    ).all()
    by_type: dict[str, int] = {}
    by_availability: dict[str, int] = {}
    for resource_type, availability, total in rows:
        by_type[resource_type] = by_type.get(resource_type, 0) + int(total)
        by_availability[availability] = by_availability.get(availability, 0) + int(total)
    latest = db.execute(select(func.max(Resource.last_updated))).scalar()
    return {
        "total": sum(by_type.values()),
        "by_type": dict(sorted(by_type.items())),
        "by_availability": dict(sorted(by_availability.items())),
        "last_change": iso(latest) if latest else None,
        "last_change_age": humanize_age(latest) if latest else None,
        "empty": not by_type,
    }


def to_dict(resource: Resource) -> dict[str, Any]:
    """Every fact here carries where it came from and how old the confirmation is."""
    attributes = resource.attributes or {}
    return {
        "id": resource.id,
        "resource_type": resource.resource_type,
        "name": resource.name,
        "description": resource.description,
        "latitude": resource.latitude,
        "longitude": resource.longitude,
        "address": resource.address,
        "district": resource.district,
        "province": resource.province,
        "contact": resource.contact,
        "contact_verified": resource.contact_verified,
        "capacity": resource.capacity,
        "availability": resource.availability,
        "availability_verified_at": iso(resource.availability_verified_at),
        "availability_age": humanize_age(resource.availability_verified_at),
        "source": resource.source,
        "source_url": resource.source_url,
        "provenance": resource.provenance,
        "osm_id": attributes.get("osm_id"),
        "district_from": attributes.get("district_from"),
        "in_nepal": bool(resource.district),
        "has_location": resource.latitude is not None and resource.longitude is not None,
        "at": iso(resource.last_updated),
        "age": humanize_age(resource.last_updated),
        "demo": resource.provenance == "demo",
    }


def geojson(resources: list[Resource]) -> dict[str, Any]:
    features = []
    for resource in resources:
        attributes = resource.attributes or {}
        if resource.latitude is None or resource.longitude is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [resource.longitude, resource.latitude]},
                "properties": {
                    "id": resource.id,
                    "resource_type": resource.resource_type,
                    "name": resource.name,
                    "district": resource.district,
                    # The generous Nepal bbox catches Indian border towns. A hospital in
                    # Kushinagar renders as a pin on the same map, so the layer has to say
                    # whether this side of the border it is on.
                    "district_from": attributes.get("district_from"),
                    "in_nepal": bool(resource.district),
                    "availability": resource.availability,
                    "capacity": resource.capacity,
                    "provenance": resource.provenance,
                    "source": resource.source,
                    "contact_verified": resource.contact_verified,
                    "at": iso(resource.last_updated),
                    "demo": resource.provenance == "demo",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
