"""Ad-hoc inspection of the hydrology.gov.np public API shapes.

Kept because the endpoint returns no date field and the bulletin title is the
only reliable timestamp - this is the evidence behind that decision.

Usage: python scripts/inspect_hydrology.py
"""

from __future__ import annotations

import json
import sys

from _bootstrap import prepare

prepare()

from data_ingestion.http_fetch import fetch  # noqa: E402

BUCKETS = ["alerts", "current_forecast", "notice"]


def main() -> int:
    for bucket in BUCKETS:
        url = f"https://hydrology.gov.np/cm/api-public/{bucket}"
        result = fetch(url, timeout=45.0)
        print(f"\n=== {bucket} HTTP {result.status_code} {result.content_type}")
        if not result.ok:
            print("   unavailable:", result.status_code)
            continue
        try:
            payload = json.loads(result.text)
        except ValueError:
            print("   not JSON:", ascii(result.text[:200]))
            continue
        if isinstance(payload, dict):
            print("   dict keys:", sorted(payload)[:10])
            payload = payload.get("data") or payload.get("rows") or []
        print(f"   rows={len(payload)}")
        for row in payload[:3]:
            print("   ", ascii(json.dumps(row, ensure_ascii=False))[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
