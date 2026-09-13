"""Import + route + pure-function check for the resource catalogue (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.main import app  # noqa: E402
from backend.app.services import resources as rs  # noqa: E402

ISSUES: list[str] = []

# FastAPI 0.141 keeps included routers lazy, so app.routes does not list them. The
# OpenAPI tree is the only complete view of what the server will actually answer.
paths = set(app.openapi()["paths"])
for want in [
    "/api/rc/resources",
    "/api/rc/resources/{resource_id}/availability",
    "/api/rc/resources/seed",
    "/api/map/resources.geojson",
]:
    if want not in paths:
        ISSUES.append(f"missing route {want}")

# build_query must be a legal Overpass QL shape for every advertised type
for name, tags, limit in rs.TYPE_QUERIES:
    ql = rs.build_query(tags, limit)
    if f'"{list(tags)[0]}"="{tags[list(tags)[0]]}"' not in ql:
        ISSUES.append(f"query for {name} does not filter on {tags}")
    if "out center" not in ql:
        ISSUES.append(f"query for {name} has no 'out center' - ways would have no coordinate")
    # Overpass needs a statement terminator inside the union block; this exact omission
    # is what made the first real seed run come back 400. Split on "out center", not on
    # "out" - the preamble `[out:json]` would otherwise truncate the query.
    head = ql.split("out center")[0].replace(" ", "")
    if not any(part.endswith(");") for part in head.split("(")):
        ISSUES.append(f"query for {name} has an unterminated statement inside the union")
    if ql.count("(") != ql.count(")"):
        ISSUES.append(f"query for {name} has unbalanced parentheses")

# unlocated / unnamed OSM elements must be refused, not guessed at
if rs._osm_element_to_fields("node", {"id": 1, "tags": {"amenity": "hospital"}}) is not None:
    ISSUES.append("unnamed OSM element was accepted")
if rs._osm_element_to_fields("way", {"id": 2, "tags": {"name": "X", "amenity": "hospital"}}) is not None:
    ISSUES.append("unlocated OSM way was accepted")

print(f"routes checked: {len(paths)}   types: {len(rs.TYPE_QUERIES)}")
if ISSUES:
    print("ISSUES:")
    for issue in ISSUES:
        print("  -", issue)
    raise SystemExit(1)
print("OK")
