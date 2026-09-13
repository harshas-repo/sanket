"""Print what is actually in the database right now.

Every summary in the README and in docs/known-issues.md quotes numbers. Numbers written by
hand go stale and quietly turn a report into a claim, so this exists: run it, and the
summaries can be checked rather than trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from backend.app.db import SessionLocal  # noqa: E402
from backend.app.models.core import (  # noqa: E402
    AgentInvestigation,
    AssistanceRequest,
    AuditEvent,
    CommunityReport,
    Incident,
    IngestionRun,
    Notification,
    Observation,
    Resource,
)

TABLES = [
    ("observations", Observation),
    ("incidents", Incident),
    ("community_reports", CommunityReport),
    ("assistance_requests", AssistanceRequest),
    ("resources", Resource),
    ("agent_investigations", AgentInvestigation),
    ("notifications", Notification),
    ("audit_events", AuditEvent),
]


def main() -> int:
    db = SessionLocal()
    try:
        print("rows in the working database")
        for name, model in TABLES:
            total = int(db.execute(select(func.count(model.id))).scalar_one() or 0)
            demo = 0
            if hasattr(model, "provenance"):
                demo = int(
                    db.execute(
                        select(func.count(model.id)).where(model.provenance == "demo")
                    ).scalar_one()
                    or 0
                )
            print(f"  {name:24s} {total:6d}" + (f"  (demo: {demo})" if demo else ""))

        print("\nincidents by evidence state")
        for state, count in db.execute(
            select(Incident.evidence_state, func.count(Incident.id)).group_by(Incident.evidence_state)
        ).all():
            print(f"  {str(state):24s} {count:6d}")

        print("\ningestion runs, newest attempt per source")
        latest: dict[str, IngestionRun] = {}
        for row in db.execute(select(IngestionRun).order_by(IngestionRun.started_at.desc())).scalars():
            latest.setdefault(row.source_code, row)
        by_status: dict[str, int] = {}
        for row in latest.values():
            by_status[row.status] = by_status.get(row.status, 0) + 1
        print(f"  {len(latest)} sources have run; statuses {by_status}")
        for code in sorted(latest):
            row = latest[code]
            if row.status == "ok":
                note = f"  {row.records_new} new / {row.records_updated} updated of {row.records_found}"
            else:
                note = f"  {(row.error or '')[:70]}"
            print(f"  {code:22s} {row.status:8s} {str(row.started_at)[:19]}{note}")

        from backend.app.main import app

        print(f"\napi paths exposed: {len(app.openapi()['paths'])}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
