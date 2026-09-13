"""Geospatial intelligence layer: boundary access and coordinate -> location resolution.

Coordinate lookups go against the official DHM 77-district polygons (cached under
/data/geo). When those files have not been fetched yet the layer degrades to the
district gazetteer and reports `precision = "gazetteer"`, so callers always know how
much to trust a place label.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from data_ingestion import static_geo
from shared.nepal_places import resolve_place

logger = logging.getLogger("sanket.geo")

_DISTRICT_ALIASES: dict[str, str] = {
    "chitawan": "Chitwan",
    "chitwan": "Chitwan",
    "makwanpur": "Makwanpur",
    "makawanpur": "Makwanpur",
    "makwanpure": "Makwanpur",
    "kapilbastu": "Kapilvastu",
    "kapilvastu": "Kapilvastu",
    "kathmandu": "Kathmandu",
    "lalitpur": "Lalitpur",
    "bhaktapur": "Bhaktapur",
    "kaski": "Kaski",
    "lamjung": "Lamjung",
    "tanahu": "Tanahun",
    "tanahun": "Tanahun",
    "sindhupalchowk": "Sindhupalchok",
    "sindhupalchok": "Sindhupalchok",
    "dorpa": "Dolpa",
    "dolpa": "Dolpa",
    "jumla": "Jumla",
    "jumli": "Jumla",
    "rukum": "Western Rukum",
    "west rukum": "Western Rukum",
    "east rukum": "Rukum East",
    "nawalparasi": "Nawalparasi East",
    "nawalpur": "Nawalparasi East",
    "parsa": "Parsa",
    "bardiya": "Bardiya",
    "banke": "Banke",
    "bakeygang": "Banke",
    "surkhet": "Surkhet",
    "sorkhet": "Surkhet",
    "dailekh": "Dailekh",
    "dadelda": "Dailekh",
    "achham": "Achham",
    "mahaakali": "Doti",
    "darchula": "Darchula",
    "maahakali": "Darchula",
    "kailali": "Kailali",
    "kanlandan": "Kanchanpur",
    "kanchanpur": "Kanchanpur",
    "baitadi": "Baitadi",
    "byas": "Myagdi",
    "myagdi": "Myagdi",
    "baglung": "Baglung",
    "mustang": "Mustang",
    "manang": "Manang",
    "mustang2": "Mustang",
    "solukhumbu": "Solukhumbu",
    "supa": "Solukhumbu",
    "khumlawar": "Solukhumbu",
    "okhaldhunga": "Okhaldhunga",
    "khotang": "Khotang",
    "bhojpur": "Bhojpur",
    "terathum": "Terhathum",
    "terhathum": "Terhathum",
    "dhanuta": "Dhankuta",
    "dhankuta": "Dhankuta",
    "taplejung": "Taplejung",
    "panchthar": "Panchthar",
    "tapethar": "Panchthar",
    "ilam": "Ilam",
    "jhapa": "Jhapa",
    "morang": "Morang",
    "sunsari": "Sunsari",
    "saptari": "Saptari",
    "dhankus": "Dhanusha",
    "dhanusha": "Dhanusha",
    "rautahat": "Rautahat",
    "sarlahi": "Sarlahi",
    "mahottari": "Mahottari",
    "jaleshwar": "Siraha",
    "siraha": "Siraha",
    "bara": "Bara",
    "parsa2": "Parsa",
    "simra": "Parsa",
    "biratnagar": "Morang",
    "ganesh": "Dolakha",
    "charikot": "Dolakha",
    "dolakhha": "Dolakha",
    "dolakha": "Dolakha",
    "ramechhap": "Ramechhap",
    "manthali": "Ramechhap",
    "kavre": "Kavrepalanchok",
    "kavrepalanchok": "Kavrepalanchok",
    "banepa": "Kavrepalanchok",
    "rasuwa": "Rasuwa",
    "dhading": "Dhading",
    "dilingsa": "Dhading",
    "nuwakot": "Nuwakot",
    "bidur": "Nuwakot",
    "gorkha": "Gorkha",
    "palpa": "Palpa",
    "tansen": "Palpa",
    "gulmi": "Gulmi",
    "tamghas": "Gulmi",
    "arghakhanchi": "Arghakhanchi",
    "galkot": "Arghakhanchi",
    "pyuthan": "Gulmi",
    "rupandehi": "Rupandehi",
    "butwal": "Rupandehi",
    "tulsipur": "Dang",
    "dang": "Dang",
    "gaur": "Rautahat",
    "kalaiya": "Saptari",
    "janakpur": "Dhanusha",
    "ephrata": "Bhojpur",
    "rungli": "Solukhumbu",
    "salleri": "Taplejung",
    "hileshe": "Sankhuwasabha",
    "khandbari": "Sankhuwasabha",
    "thulging": "Dolpa",
    "sinja": "Humla",
    "simikot": "Humla",
    "mugu": "Mugu",
    "gamgadhi": "Mugu",
    "chhayangjes": "Rukum East",
    "wallichetam": "Jajarkot",
    "thalcatan": "Jajarkot",
    "salyan": "Salyan",
    "sumsalla": "Salyan",
    "rataneswore": "Salyan",
    "kalikot": "Kalikot",
    "manama": "Kalikot",
    "jangmeshwore": "Doti",
    "doti": "Doti",
    "purchaudi": "Doti",
    "sharada": "Baitadi",
    "martial": "Bajhang",
    "bajhang": "Bajhang",
    "jajarkot": "Jajarkot",
    "sanni": "Tanahun",
    "bandipur": "Tanahun",
    "besishahar": "Lamjung",
    "damauli": "Tanahun",
    "pokhara": "Kaski",
    "hetauda": "Makwanpur",
    "birgunj": "Parsa",
    "nepalgunj": "Banke",
    "dhangadhi": "Kailali",
    "bhairahawa": "Rupandehi",
    "sitalkhop": "Rupandehi",
    "mugling": "Chitwan",
    "narayanghat": "Chitwan",
    "kurintal": "Chitwan",
    "trijughat": "Gorkha",
    "premkhandi": "Sindhupalchok",
    "barhabise": "Sindhupalchok",
    "kodari": "Dhading",
    "feriwani": "Dhanusha",
    "gaighat": "Bardiya",
    "thakurdwara": "Bardiya",
    "chisapani": "Bardiya",
    "mahendranagar": "Kanchanpur",
    "dasharath": "Kanchanpur",
    "bhimdatta": "Kanchanpur",
    "martadi": "Darchula",
    "jhilmila": "Darchula",
    "bedhani": "Jhapa",
    "gadmai": "Jhapa",
    "damak": "Morang",
    "birtamod": "Jhapa",
    "itahari": "Sunsari",
    "inaruwa": "Saptari",
    "kankar": "Dhanusha",
    "phulbani": "Kavrepalanchok",
}


@dataclass
class LocationResolution:
    district: str | None
    province: str | None
    precision: str  # district_polygon | gazetteer | none
    confidence: float


class BoundaryIndex:
    """Thread-safe lazy index over the cached boundary layers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._districts: list[tuple[str, Any, Any]] = []
        self._provinces: list[tuple[str, Any, Any]] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                from shapely.geometry import shape

                layer = static_geo.load_layer("districts") or {"features": []}
                for feature in layer.get("features", []):
                    geometry = feature.get("geometry")
                    if not geometry:
                        continue
                    name = _feature_name(feature)
                    try:
                        self._districts.append((name, shape(geometry), _centroid_of(geometry)))
                    except Exception:  # noqa: BLE001 - ignore an unparseable polygon
                        continue
                layer = static_geo.load_layer("provinces") or {"features": []}
                for feature in layer.get("features", []):
                    geometry = feature.get("geometry")
                    if not geometry:
                        continue
                    name = _feature_name(feature)
                    try:
                        self._provinces.append((name, shape(geometry), _centroid_of(geometry)))
                    except Exception:  # noqa: BLE001
                        continue
                logger.info(
                    "boundary index loaded: %d districts, %d provinces",
                    len(self._districts),
                    len(self._provinces),
                )
            except ImportError:  # pragma: no cover - shapely is a declared dependency
                logger.warning("shapely unavailable - polygon reverse geocoding disabled")
            except Exception as exc:  # noqa: BLE001
                logger.error("boundary index failed to load: %s", exc)
            self._loaded = True

    def resolve_point(self, lat: float | None, lng: float | None) -> LocationResolution:
        if lat is None or lng is None:
            return LocationResolution(None, None, "none", 0.0)
        self._ensure_loaded()
        if self._districts:
            from shapely.geometry import Point

            point = Point(float(lng), float(lat))
            for name, polygon, _centroid in self._districts:
                try:
                    if polygon.contains(point) or polygon.distance(point) < 0.02:
                        return LocationResolution(name, self._province_of(point), "district_polygon", 0.95)
                except Exception:  # noqa: BLE001
                    continue
            return LocationResolution(None, self._province_of(point), "outside_known_districts", 0.4)
        return LocationResolution(None, None, "none", 0.0)

    def _province_of(self, point) -> str | None:
        from shapely.geometry import Point  # noqa: F401  (kept for clarity of type)

        for name, polygon, _c in self._provinces:
            try:
                if polygon.contains(point):
                    return name
            except Exception:  # noqa: BLE001
                continue
        return None

    def district_centroid(self, district: str | None) -> tuple[float, float] | None:
        if not district:
            return None
        self._ensure_loaded()
        target = normalize_district(district)
        for name, _polygon, centroid in self._districts:
            if normalize_district(name) == target:
                return centroid
        match = resolve_place(district)
        return (match.lat, match.lng) if match else None

    def district_names(self) -> list[str]:
        self._ensure_loaded()
        return sorted({name for name, _p, _c in self._districts if name})

    def stats(self) -> dict[str, int]:
        self._ensure_loaded()
        return {"districts": len(self._districts), "provinces": len(self._provinces)}


boundary_index = BoundaryIndex()


def normalize_district(name: str | None) -> str | None:
    if not name:
        return None
    text = str(name).strip().lower()
    text = text.replace("district", "").replace(" jilla", "").strip()
    alias = _DISTRICT_ALIASES.get(text)
    if alias:
        return alias
    # Fall back to a leading-token match ("Kosi Tower, Sunsari" -> Sunsari handled upstream)
    for key, canonical in _DISTRICT_ALIASES.items():
        if len(key) > 4 and (text.startswith(key) or key.startswith(text)) and len(text) > 4:
            return canonical
    return str(name).strip().title()


def geocode_text(text: str | None) -> LocationResolution | None:
    match = resolve_place(text or "")
    if not match:
        return None
    return LocationResolution(match.district, match.province, "gazetteer", 0.6)


def layer_geojson(layer: str) -> dict[str, Any] | None:
    """Serve a cached static layer, flattening GeometryCollections so MapLibre can
    render it without a custom parser."""
    data = static_geo.load_layer(layer)
    if not data:
        return None
    features = data.get("features", [])
    if any((f.get("geometry") or {}).get("type") == "GeometryCollection" for f in features):
        flattened: list[dict[str, Any]] = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            if geometry.get("type") == "GeometryCollection":
                for sub in geometry.get("geometries", []):
                    if sub and sub.get("coordinates"):
                        flattened.append(
                            {"type": "Feature", "properties": feature.get("properties") or {}, "geometry": sub}
                        )
            else:
                flattened.append(feature)
        return {"type": "FeatureCollection", "features": flattened}
    return data


def _feature_name(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    for key in ("name", "NAME", "DISTRICT", "shapeName", "PROVINCE", "NAME_1", "NAME_2"):
        for actual in props:
            if actual.lower() == key.lower() and str(props[actual]).strip():
                return str(props[actual]).strip()
    for value in props.values():
        if isinstance(value, str) and 2 < len(value) < 48:
            return value.strip()
    return ""


def _centroid_of(geometry: dict[str, Any]) -> tuple[float, float] | None:
    try:
        from shapely.geometry import shape

        geom = shape(geometry)
        if geom.is_empty:
            return None
        point = geom.representative_point() if not geom.is_valid else geom.centroid
        return (float(point.y), float(point.x))
    except Exception:  # noqa: BLE001
        return None
