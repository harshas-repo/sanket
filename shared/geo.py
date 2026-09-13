"""Deterministic geographic helpers.

Everything here is plain arithmetic: distances, bounding boxes and
point-in-polygon tests. The LLM is never asked to compute geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088

# Nepal bounding box (national extent including a small margin).
NEPAL_BBOX = (80.01, 26.33, 88.20, 30.45)  # west, south, east, north
NEPAL_CENTRE = (84.2, 28.39)
NEPAL_ZOOM = 6.2


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


def haversine_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    """Great-circle distance between two (lat, lng) pairs. None if either missing."""
    if not a or not b:
        return None
    lat1, lng1 = float(a[0]), float(a[1])
    lat2, lng2 = float(b[0]), float(b[1])
    if not all(math.isfinite(v) for v in (lat1, lng1, lat2, lng2)):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float | None:
    if not a or not b:
        return None
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlmb = lng2 - lng1
    y = math.sin(dlmb) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def point_in_ring(lat: float, lng: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon for a single linear ring ([lng, lat] pairs)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lat: float, lng: float, polygon: list[list[list[float]]]) -> bool:
    """Polygon = list of rings; first ring is the outer boundary, rest are holes."""
    if not polygon:
        return False
    if not point_in_ring(lat, lng, polygon[0]):
        return False
    for hole in polygon[1:]:
        if point_in_ring(lat, lng, hole):
            return False
    return True


def ring_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    lngs = [p[0] for p in ring if len(p) >= 2]
    lats = [p[1] for p in ring if len(p) >= 2]
    return (min(lngs), min(lats), max(lngs), max(lats))


def geometry_bbox(geom: dict) -> tuple[float, float, float, float] | None:
    rings = iter_rings(geom)
    lngs: list[float] = []
    lats: list[float] = []
    for ring in rings:
        lngs.extend(p[0] for p in ring)
        lats.extend(p[1] for p in ring)
    if not lngs:
        return None
    return (min(lngs), min(lats), max(lngs), max(lats))


def iter_rings(geom: dict | None):
    """Yield every linear ring inside Point/MultiPoint/LineString/MultiLineString/
    Polygon/MultiPoint/GeometryCollection geometries."""
    if not geom:
        return
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype in ("Polygon", "MultiLineString") and coords:
        for part in coords:
            yield part
    elif gtype == "MultiPolygon" and coords:
        for poly in coords:
            for ring in poly:
                yield ring
    elif gtype in ("LineString", "LinearRing") and coords:
        yield coords
    elif gtype == "GeometryCollection":
        for sub in geom.get("geometries", []):
            yield from iter_rings(sub)


def within_nepal(lat: float | None, lng: float | None, margin_km: float = 60.0) -> bool:
    """Used only for labelling, never to drop data: events just outside the border
    (e.g. Tibetan epicentres) are still relevant to Nepal."""
    if lat is None or lng is None:
        return False
    west, south, east, north = NEPAL_BBOX
    deg_margin = margin_km / 111.0
    return (
        west - deg_margin <= lng <= east + deg_margin
        and south - deg_margin <= lat <= north + deg_margin
    )


def centroid(geom: dict) -> tuple[float, float] | None:
    rings = list(iter_rings(geom))
    if not rings:
        c = geom.get("coordinates")
        if isinstance(c, list) and len(c) >= 2:
            return (float(c[1]), float(c[0]))
        return None
    lngs = [p[0] for r in rings for p in r]
    lats = [p[1] for r in rings for p in r]
    return (sum(lats) / len(lats), sum(lngs) / len(lngs))
