"""Static geographic data: real Nepal boundaries, provinces, districts, rivers.

Fetched once (rarely updated per the performance rules) and cached under
/data/geo. The national border and district shapes come from authoritative
sources - the Department of Hydrology and Meteorology's own published GeoJSON for
districts and rivers, and geoBoundaries (Survey Department of Nepal derived) for the
national and province level. Nothing here is a hand-drawn outline.

Large official files are coordinate-simplified before being served to the browser;
the reduction factor and the tolerance used are recorded in geo/meta.json so the
generalisation is auditable.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_ingestion.http_fetch import fetch
from data_ingestion.sources.catalog import STATIC_GEODATA

logger = logging.getLogger("sanket.static_geo")

GEO_DIR = Path(__file__).resolve().parents[1] / "data" / "geo"

# Simplification tolerance in degrees. ~0.002 deg is about 200 m - invisible at
# national zoom, and it keeps the district layer small enough for low-end phones.
TOLERANCE_BY_LAYER = {
    "districts": 0.002,
    "provinces": 0.002,
    "boundary": 0.001,
    "rivers": 0.0015,
}

NAME_KEYS = ("DISTRICT", "DIST_NAME", "district", "NAME_2", "NAME_1", "NAME", "name", "shapeName")


def _simplify(geojson: dict[str, Any], tolerance: float) -> tuple[dict[str, Any], int, int]:
    try:
        from shapely.geometry import shape

        originals = 0
        kept = 0
        features_out = []
        for feature in geojson.get("features", []):
            geom = feature.get("geometry")
            if not geom:
                continue
            try:
                geometry = shape(geom)
            except Exception:  # noqa: BLE001 - skip an individual bad polygon, keep the layer
                originals += _vertex_count(geom)
                continue
            originals += _vertex_count(geom)
            try:
                simplified = geometry.simplify(tolerance, preserve_topology=True)
            except Exception:  # noqa: BLE001
                simplified = geometry
            if simplified.is_empty:
                kept += 0
                continue
            props = {k: v for k, v in (feature.get("properties") or {}).items() if _is_meaningful(k, v)}
            if "name" not in props:
                for key in NAME_KEYS:
                    for actual in list(props):
                        if actual.lower() == key.lower():
                            props["name"] = props[actual]
                            break
            # Keep the payload tight: the browser only needs a display name.
            trimmed = {"name": props.get("name") or props.get("shapeName") or ""}
            trimmed.update({k: v for k, v in props.items() if k not in ("name", "id", "fid") and len(str(v)) < 48})
            out_geom = _to_geojson(simplified)
            kept += _vertex_count(out_geom)
            features_out.append({"type": "Feature", "properties": trimmed, "geometry": out_geom})
        result = {"type": "FeatureCollection", "features": features_out}
        return result, originals, kept
    except ImportError:
        logger.warning("shapely not installed - storing boundary layer unsimplified")
        return geojson, _total_vertices(geojson), _total_vertices(geojson)


def _to_geojson(geometry) -> dict[str, Any]:
    from shapely.geometry import mapping

    return mapping(geometry)


def _vertex_count(geom: dict[str, Any] | None) -> int:
    if not geom:
        return 0
    count = 0
    stack = [geom.get("coordinates")]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            if node and isinstance(node[0], (int, float)):
                count += 1
            else:
                stack.extend(node)
    return count


def _total_vertices(geojson: dict[str, Any]) -> int:
    return sum(_vertex_count(f.get("geometry")) for f in geojson.get("features", []))


def _is_meaningful(key: str, value: Any) -> bool:
    if key.lower() in ("gid", "ogc_fid", "fid", "the_geom", "geom"):
        return False
    return value not in (None, "", "nan", "NaN")


def fetch_all(force: bool = False) -> dict[str, Any]:
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = GEO_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    report: dict[str, Any] = {}

    for layer, spec in STATIC_GEODATA.items():
        target = GEO_DIR / spec["file"]
        if target.exists() and not force:
            report[layer] = {"status": "cached", "file": spec["file"]}
            continue
        try:
            url = spec["url"]
            if spec["hops"]:
                api = json.loads(fetch(url, timeout=60.0).text)
                url = api.get(spec["hops"]) or api.get("gjDownloadURL")
                if not url:
                    raise RuntimeError("geoBoundaries API did not return a download URL")
            result = fetch(url, timeout=180.0)
            if not result.ok:
                raise RuntimeError(f"HTTP {result.status_code}")
            geojson = json.loads(result.text)
            simplified, before, after = _simplify(geojson, TOLERANCE_BY_LAYER.get(layer, 0.002))
            payload = json.dumps(simplified, separators=(",", ":"))
            target.write_text(payload, encoding="utf-8")
            meta[layer] = {
                "source_url": url,
                "label": spec["label"],
                "file": spec["file"],
                "features": len(simplified.get("features", [])),
                "vertices_before": before,
                "vertices_after": after,
                "simplification_tolerance_deg": TOLERANCE_BY_LAYER.get(layer),
                "bytes": len(payload),
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            report[layer] = {"status": "fetched", **meta[layer]}
            logger.info("%s: %d features, %d bytes", layer, meta[layer]["features"], len(payload))
        except Exception as exc:  # noqa: BLE001 - a missing basemap layer must not stop setup
            report[layer] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            logger.error("static layer %s failed: %s", layer, exc)

    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return report


def load_layer(layer: str) -> dict[str, Any] | None:
    spec = STATIC_GEODATA.get(layer)
    if not spec:
        return None
    path = GEO_DIR / spec["file"]
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def layer_meta() -> dict[str, Any]:
    meta_path = GEO_DIR / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(fetch_all(force="--force" in sys.argv), indent=2)[:4000])
