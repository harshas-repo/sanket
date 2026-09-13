"""Ad-hoc adapter smoke test: run each source adapter against the live endpoint.

    python scripts/check_sources.py [code ...]

Reports real counts and a sample record, or the exact failure. Never prints a
synthetic success.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _bootstrap import prepare  # noqa: E402

# The portals write in Nepali, and this script's entire job is to print what a feed actually
# returned - so a cp1252 console used to abort the run partway through with a UnicodeEncodeError on
# a highway bulletin. `prepare()` is the project's own answer to that and every other script here
# already calls it.
prepare()

from backend.app.config import settings  # noqa: E402
from data_ingestion.sources import SOURCE_CATALOG, build_adapter  # noqa: E402


def main(codes: list[str]) -> int:
    for code in codes:
        spec = SOURCE_CATALOG.get(code)
        if not spec:
            print(f"[skip] unknown source '{code}'")
            continue
        adapter = build_adapter(code, settings)
        print(f"\n=== {code} :: {spec.name}")
        print(f"    url: {spec.url}")
        try:
            observations = adapter.fetch_observations()
        except Exception as exc:  # noqa: BLE001 - this IS the report
            print(f"    FAILED {type(exc).__name__}: {exc}")
            continue
        print(f"    OK {len(observations)} observations")
        located = [o for o in observations if o.has_coordinates()]
        print(f"    with coordinates: {len(located)}")
        for obs in observations[:3]:
            print(
                f"      - [{obs.kind.value}] {obs.title[:70]} | "
                f"{obs.district or '-'} | {obs.event_time} | mag={obs.magnitude} "
                f"val={obs.value}{obs.unit or ''} state={obs.threshold_state}"
            )
    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or ["usgs", "nemrc", "drr", "dhm_rainfall", "hydrology_alerts"]
    sys.exit(main(args))
