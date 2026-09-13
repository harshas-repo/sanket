"""First vertical slice smoke test: REAL EARTHQUAKE DATA -> NORMALIZED INCIDENT ->
evidence / impact / freshness. Also exercises DRR + DHM + signals so we know the
whole deterministic chain runs against live sources.

Usage:  python scripts/smoke_slice.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import prepare

prepare()

from sqlalchemy import func, select  # noqa: E402

from backend.app.db import SessionLocal, init_db  # noqa: E402
from backend.app.models.core import Incident, Observation, RiskSignal  # noqa: E402
from backend.app.services import ingestion  # noqa: E402
from backend.app.services import signals as signal_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="skip live fetching")
    parser.add_argument("--limit", type=int, default=5, help="incidents to print")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    print(f"sources registered: {ingestion.ensure_sources(db)}")

    if not args.offline:
        for code in ["usgs", "nemrc", "drr", "dhm_rainfall", "hydrology_alerts", "dhm_rivers"]:
            report = ingestion.run_source(db, code)
            print(f"  {code:18s} {report['status']:12s} {json.dumps({k: v for k, v in report.items() if k not in {'source', 'status'}})[:180]}")

    total_obs = db.execute(select(func.count(Observation.id))).scalar_one()
    by_kind = db.execute(select(Observation.kind, func.count(Observation.id)).group_by(Observation.kind)).all()
    total_inc = db.execute(select(func.count(Incident.id))).scalar_one()
    print(f"\nobservations={total_obs} incidents={total_inc}")
    for kind, count in by_kind:
        print(f"  {kind:22s} {count}")

    signal_service.rebuild_signals(db)
    print(f"risk signals={db.execute(select(func.count(RiskSignal.id)).where(RiskSignal.active.is_(True))).scalar_one()}")

    rows = db.execute(
        select(Incident).where(Incident.duplicate_of.is_(None)).order_by(Incident.impact_score.desc()).limit(args.limit)
    ).scalars().all()
    print(f"\ntop {len(rows)} incidents by deterministic impact score:")
    for inc in rows:
        print(f"  {inc.ref_code} [{inc.incident_type}] {inc.title[:60]}")
        print(f"     evidence={inc.evidence_state} score={inc.impact_score} urgency={inc.urgency} "
              f"severity={inc.severity} freshness={inc.impact.get('freshness_state')}")
        print(f"     location={inc.location_name} / {inc.district} precision={inc.location_precision}")
        print(f"     impact={json.dumps(inc.impact.get('counters', {}))}")
        for reason in inc.prioritization_reasons[:4]:
            print(f"       - {reason}")

    seismic = db.execute(
        select(func.count(Incident.id)).where(Incident.incident_type == "earthquake")
    ).scalar_one()
    print(f"\nearthquake incidents derived from real catalogues: {seismic}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
