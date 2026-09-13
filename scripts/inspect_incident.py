"""Why does this incident have the evidence state it has? Dumps the exact rows the
deterministic state machine is looking at."""

from __future__ import annotations

import sys

from _bootstrap import prepare

prepare()

from sqlalchemy import select  # noqa: E402

from backend.app.db import SessionLocal  # noqa: E402
from backend.app.models.core import Incident, IncidentObservation, Observation  # noqa: E402


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        stmt = select(Incident).where(Incident.duplicate_of.is_(None))
        if ref:
            stmt = stmt.where(Incident.ref_code.like(f"%{ref}%"))
        for incident in db.execute(stmt.order_by(Incident.impact_score.desc()).limit(5)).scalars():
            print(f"\n{incident.ref_code} [{incident.incident_type}] {incident.title[:70]}")
            print(f"  evidence={incident.evidence_state} confirmed_by={incident.confirmed_by_source}")
            print(f"  verified_by={incident.verified_by} official_confirmation={incident.official_confirmation}")
            print(f"  needs_review={incident.needs_review} reason={incident.review_reason}")
            print(f"  score={incident.impact_score} urgency={incident.urgency}")
            rows = db.execute(
                select(IncidentObservation, Observation)
                .join(Observation, Observation.id == IncidentObservation.observation_id)
                .where(IncidentObservation.incident_id == incident.id)
            ).all()
            for row, obs in rows:
                print(
                    f"    link role={row.role:<10} src={str(obs.source_id):<16} kind={str(obs.kind):<18}"
                    f" prov={str(obs.provenance):<10} {str(obs.title)[:50]}"
                )
            for reason in incident.prioritization_reasons[:6]:
                print(f"    reason: {reason}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
