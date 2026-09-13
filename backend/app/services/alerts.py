"""Official alert read-model.

Alerts are pulled straight from the OBSERVATION layer rather than being turned
into incidents: a flood bulletin or an early-warning notice is official
information about conditions, and the Community "Local Alerts" panel and the
Response Center alert strip both need it exactly as the agency worded it.

Two rules govern this module:
* the text is never rewritten - we quote the official title and attach the
  source, timestamp and freshness;
* a bulletin whose publication time the source does not give is reported with
  `event_time: null` and freshness UNKNOWN instead of defaulting to "just now".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.core import Observation
from backend.app.scoring import freshness as freshness_mod
from shared.enums import ObservationKind
from shared.timeutils import humanize_age, iso, utcnow

# How far back the alert feed reaches. Older bulletins stay in the database as
# historical evidence but do not crowd an "alerts" panel.
DEFAULT_WINDOW_DAYS = 21


def list_alerts(
    db: Session,
    *,
    district: str | None = None,
    limit: int = 30,
    window_days: int = DEFAULT_WINDOW_DAYS,
    include_undated: bool = False,
) -> list[dict[str, Any]]:
    cutoff = utcnow() - timedelta(days=window_days)
    stmt = (
        select(Observation)
        .where(Observation.kind == ObservationKind.OFFICIAL_ALERT.value)
        .order_by(Observation.event_time.desc().nullslast())
        .limit(limit * 4)
    )
    if district:
        stmt = stmt.where(Observation.district == district)
    out: list[dict[str, Any]] = []
    for obs in db.execute(stmt).scalars():
        moment = obs.event_time
        if moment is None and not include_undated:
            continue
        if moment and moment < cutoff:
            continue
        normalized = obs.normalized_data or {}
        state = freshness_mod.classify(moment, obs.source.stale_after_seconds if obs.source else 86_400)
        out.append(
            {
                "id": obs.id,
                "title": obs.title,
                "body": obs.summary,
                "district": obs.district,
                "province": obs.province,
                "latitude": obs.latitude,
                "longitude": obs.longitude,
                "severity": obs.severity,
                "kind": normalized.get("bulletin_type"),
                "published_at": iso(moment),
                "published_label": humanize_age(moment) if moment else "no published time",
                "expiry_at": normalized.get("expiry_date"),
                "is_pdf_bulletin": bool(normalized.get("is_pdf_bulletin")),
                "published_date_source": normalized.get("published_date_source"),
                "freshness_state": state.value,
                "source": obs.source_id,
                "source_name": obs.source.name if obs.source else obs.source_id,
                "source_url": obs.source_url,
                "provenance": obs.provenance,
                "demo": obs.provenance == "demo",
            }
        )
        if len(out) >= limit:
            break
    return out


def latest_for_district(db: Session, district: str | None) -> dict[str, Any] | None:
    rows = list_alerts(db, district=district, limit=1)
    return rows[0] if rows else None
