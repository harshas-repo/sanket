"""Ingestion orchestration: run adapters, persist normalized observations, maintain
source health, and feed the incident/signal layers.

Failure policy is explicit: an unreachable source is recorded as failing and shown
as unavailable. It is never replaced by cached demo rows without the `stale`/
`unavailable` markers, and never by invented data at all.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db import JsonDict, as_stored_json
from backend.app.geo.boundaries import boundary_index, normalize_district
from backend.app.models.core import IngestionRun, Observation, Source
from backend.app.services import incidents as incident_service
from backend.app.services import signals as signal_service
from data_ingestion.http_fetch import SourceMalformed, SourceUnavailable
from data_ingestion.normalizers.observation import NormalizedObservation
from data_ingestion.sources import INTERNAL_SOURCES, SOURCE_CATALOG, build_adapter
from shared.enums import FreshnessState, SourceStatus
from shared.timeutils import age_seconds, iso, utcnow

logger = logging.getLogger("sanket.ingestion")


def ensure_sources(db: Session) -> int:
    """Register the catalogue so source health is queryable even before a fetch."""
    count = 0
    for code, spec in SOURCE_CATALOG.items():
        source, created = _register(db, code, spec)
        source.enabled = code in enabled_source_codes()
        count += int(created)
    # Internal provenance rows (community, demo) exist so that OBSERVATIONS.source_id
    # resolves, but they are never polled.
    for code, spec in INTERNAL_SOURCES.items():
        source, created = _register(db, code, spec)
        source.enabled = False
        count += int(created)
    db.commit()
    return count


def _register(db: Session, code: str, spec) -> tuple[Source, bool]:
    """Upsert one catalogue entry onto its source row; returns (row, was_created)."""
    source = db.execute(select(Source).where(Source.code == code)).scalar_one_or_none()
    created = source is None
    if source is None:
        source = Source(code=code)
        db.add(source)
    source.name = spec.name
    source.organization = spec.organization
    source.source_type = spec.source_type
    source.official = spec.official
    source.url = spec.url
    source.refresh_interval_seconds = spec.refresh_interval_seconds
    source.stale_after_seconds = spec.stale_after_seconds
    source.machine_readable = spec.machine_readable
    source.notes = spec.access_notes
    return source, created


def enabled_source_codes() -> set[str]:
    if not settings.ingestion_enabled:
        return set()
    return set(SOURCE_CATALOG)


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _enum_value(value: Any) -> Any:
    """Adapters hand over enums; the column stores the plain string."""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


# Read off the model rather than written out, so that adding a payload column to `Observation`
# cannot silently opt out of the comparison rule in `changed_fields`.
_PAYLOAD_COLUMNS = frozenset(
    column.key for column in Observation.__table__.columns if isinstance(column.type, JsonDict)
)


def observation_payload(record: NormalizedObservation) -> dict[str, Any]:
    """The columns one normalized record writes, exactly as `upsert_observations` writes them.

    A function rather than an inline dict because "did this poll change anything?" is a question
    worth asking without re-running the fetch - `probe/why_it_reupdates.py` reads the stored row and
    this same mapping, and a copy of the mapping there would drift from the one that matters here.
    """
    district = normalize_district(record.district)
    if district is None and record.latitude is not None and record.longitude is not None:
        resolved = boundary_index.resolve_point(record.latitude, record.longitude)
        if resolved.district:
            district = resolved.district
            if not record.province:
                record.province = resolved.province

    return {
        "kind": _enum_value(record.kind),
        "subtype": record.subtype,
        "incident_type": _enum_value(record.incident_type),
        "title": record.title[:512] if record.title else "",
        "summary": record.summary or "",
        "latitude": record.latitude,
        "longitude": record.longitude,
        "location_name": record.location_name,
        "district": district,
        "province": record.province,
        "local_municipality": record.local_municipality,
        "within_nepal": record.within_nepal,
        "event_time": record.event_time,
        "severity": record.severity,
        "magnitude": record.magnitude,
        "depth_km": record.depth_km,
        "value": record.value,
        "unit": record.unit,
        "threshold_state": record.threshold_state,
        "trend": record.trend,
        "deaths": record.deaths,
        "missing": record.missing,
        "injured": record.injured,
        "affected_people": record.affected_people,
        "houses_damaged": record.houses_damaged,
        "source_url": record.source_url,
        "provenance": record.provenance,
        "raw_data": record.raw_data,
        "normalized_data": record.normalized_data,
    }


def changed_fields(existing: Observation, payload: dict[str, Any]) -> list[str]:
    """Which columns this record would really rewrite, per the writer's own comparison.

    Split out for the same reason as `observation_payload`: "did this poll change anything?" is the
    question the whole churn problem turns on, and `probe/why_it_reupdates.py` has to be able to ask
    it of the real comparison rather than of a copy that could drift from it.
    """
    differs: list[str] = []
    for field, value in payload.items():
        stored = getattr(existing, field)
        # Never let a later poll blank out a field we already have.
        if value is None and stored is not None:
            continue
        # Only the payload columns need comparing against the shape the column stores; a `DateTime`
        # column hands back the datetime it was given, and normalising one turns it into a string and
        # finds a change in every poll - the opposite of the point.
        fresh = as_stored_json(value) if field in _PAYLOAD_COLUMNS else value
        # Why this line exists: `usgs` keeps a `datetime` under `normalized_data["source_recorded_utc"]`,
        # which `JsonDict` writes as an ISO string and hands back as a string, so a bare `!=` found a
        # difference that was not there - 166 "updates" in a day to one earthquake from 107 hours ago,
        # each one bumping `received_at` and re-stamping the incident's `last_updated_at`, which is
        # the field the dashboard prints as "last change". An unchanged feed now leaves the row, and
        # the incident, alone: `probe/poll_twice.py` is the measurement of that.
        if stored != fresh:
            differs.append(field)
    return differs


def upsert_observations(db: Session, records: list[NormalizedObservation]) -> tuple[int, int, list[Observation]]:
    created = 0
    updated = 0
    touched: list[Observation] = []
    for record in records:
        existing = db.execute(
            select(Observation).where(
                Observation.source_id == record.source_code,
                Observation.external_id == record.external_id,
            )
        ).scalar_one_or_none()

        payload = observation_payload(record)
        if existing is None:
            observation = Observation(
                source_id=record.source_code, external_id=record.external_id, **payload
            )
            db.add(observation)
            db.flush()
            touched.append(observation)
            created += 1
        else:
            differs = changed_fields(existing, payload)
            for field in differs:
                setattr(existing, field, payload[field])
            if differs:
                existing.received_at = utcnow()
                updated += 1
                touched.append(existing)
    db.flush()
    return created, updated, touched


def absorb(db: Session, observations: list[Observation]) -> int:
    affected: set[str] = set()
    for observation in observations:
        incident = incident_service.absorb_observation(db, observation)
        if incident is not None:
            affected.add(incident.id)
    for incident_id in affected:
        incident = db.get(incident_service.Incident, incident_id)
        if incident is not None:
            incident_service.recompute(db, incident)
    return len(affected)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def run_source(db: Session, code: str, persist_incidents: bool = True) -> dict[str, Any]:
    spec = SOURCE_CATALOG.get(code)
    if not spec:
        return {"source": code, "status": "skipped", "error": "unknown source"}

    source = db.execute(select(Source).where(Source.code == code)).scalar_one_or_none()
    if source is None:
        ensure_sources(db)
        source = db.execute(select(Source).where(Source.code == code)).scalar_one()
    if not source.enabled:
        return {"source": code, "status": "skipped", "error": "disabled"}

    run = IngestionRun(source_code=code, started_at=utcnow(), status="running")
    db.add(run)
    db.commit()

    adapter = build_adapter(code, settings)
    started = utcnow()
    try:
        records = adapter.fetch_observations()
    except SourceUnavailable as exc:
        _record_failure(db, source, run, started, f"unavailable: {exc.reason}")
        logger.warning("source %s unavailable: %s", code, exc.reason)
        return {"source": code, "status": "unavailable", "error": str(exc.reason)[:400]}
    except SourceMalformed as exc:
        _record_failure(db, source, run, started, f"malformed: {exc.reason}")
        logger.warning("source %s malformed: %s", code, exc.reason)
        return {"source": code, "status": "malformed", "error": str(exc.reason)[:400]}
    except Exception as exc:  # noqa: BLE001 - adapters must not break the scheduler
        _record_failure(db, source, run, started, f"{type(exc).__name__}: {exc}")
        logger.exception("source %s crashed", code)
        return {"source": code, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:400]}

    created, updated, touched = upsert_observations(db, records)
    incidents_touched = absorb(db, touched) if persist_incidents else 0
    newest = max((o.event_time for o in touched if o.event_time), default=None)
    source.status = SourceStatus.HEALTHY.value
    source.last_checked_at = started
    source.last_success_at = utcnow()
    source.last_error = None
    source.last_error_at = None
    source.last_fetch_count = len(records)
    source.consecutive_failures = 0
    if newest and (source.last_data_timestamp is None or newest > source.last_data_timestamp):
        source.last_data_timestamp = newest
    run.status = "ok"
    run.finished_at = utcnow()
    run.records_found = len(records)
    run.records_new = created
    run.records_updated = updated
    run.detail = {"incidents_touched": incidents_touched}
    db.commit()
    return {
        "source": code,
        "status": "ok",
        "records_found": len(records),
        "records_new": created,
        "records_updated": updated,
        "incidents_touched": incidents_touched,
        "last_data_timestamp": iso(newest),
    }


def _record_failure(db: Session, source: Source, run: IngestionRun, started, message: str) -> None:
    source.status = (
        SourceStatus.DEGRADED.value if source.consecutive_failures < 2 else SourceStatus.FAILING.value
    )
    source.last_checked_at = started
    source.last_error = message[:1000]
    source.last_error_at = utcnow()
    source.consecutive_failures = (source.consecutive_failures or 0) + 1
    run.status = "error"
    run.finished_at = utcnow()
    run.error = message[:1000]
    db.commit()


def run_all(db: Session, codes: list[str] | None = None) -> dict[str, Any]:
    if codes is None:
        codes = [
            source.code
            for source in db.execute(select(Source).where(Source.enabled.is_(True))).scalars()
        ] or list(SOURCE_CATALOG)
    reports = [run_source(db, code) for code in codes]
    signal_report = signal_service.rebuild_signals(db, commit=False)
    db.commit()
    return {
        "started_at": iso(utcnow()),
        "sources": reports,
        "signals": signal_report,
        "ok": sum(1 for r in reports if r["status"] == "ok"),
        "failed": sum(1 for r in reports if r["status"] not in {"ok", "skipped"}),
    }


def due_sources(db: Session) -> list[str]:
    """Sources whose refresh interval has elapsed. Keeps the government portals from
    being polled excessively."""
    now = utcnow()
    due: list[str] = []
    for source in db.execute(select(Source)).scalars():
        if not source.enabled:
            continue
        if source.last_checked_at is None:
            due.append(source.code)
            continue
        elapsed = (now - source.last_checked_at).total_seconds()
        if elapsed >= source.refresh_interval_seconds:
            due.append(source.code)
    return due


def enabled_sources(db: Session) -> list[str]:
    """Every polled source, due or not. The forced pass's list."""
    return [
        source.code for source in db.execute(select(Source).where(Source.enabled.is_(True))).scalars()
    ]


def run_due_sources(db: Session, *, force: bool = False) -> dict[str, Any] | None:
    """One pass over the sources whose interval has elapsed.

    `force` polls every enabled source regardless of it, which is what an operator asking "show me
    the newest official records" means: waiting for a source's own interval would answer a request
    for fresh data with whatever the last poll happened to store. Nothing calls it without the
    worker's floor (`scheduler.FORCE_FLOOR_SECONDS`) - a forced pass puts a live request on every
    agency server at once, and those portals already answer HTTP 500 when pushed.
    """
    due = enabled_sources(db) if force else due_sources(db)
    if not due:
        return None
    return run_all(db, due)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def source_health(db: Session) -> list[dict[str, Any]]:
    now = utcnow()
    out: list[dict[str, Any]] = []
    for source in db.execute(select(Source).order_by(Source.name)).scalars():
        freshness_age = age_seconds(source.last_success_at, now)
        data_age = age_seconds(source.last_data_timestamp, now)
        state = _source_freshness(source, freshness_age)
        out.append(
            {
                "code": source.code,
                "name": source.name,
                "organization": source.organization,
                "source_type": source.source_type,
                "official": source.official,
                "machine_readable": source.machine_readable,
                "enabled": source.enabled,
                "status": source.status,
                "url": source.url,
                "refresh_interval_seconds": source.refresh_interval_seconds,
                "last_checked_at": iso(source.last_checked_at),
                "last_successful_fetch": iso(source.last_success_at),
                "last_error": source.last_error,
                "last_error_at": iso(source.last_error_at),
                "last_data_timestamp": iso(source.last_data_timestamp),
                "last_fetch_count": source.last_fetch_count,
                "consecutive_failures": source.consecutive_failures,
                "freshness_state": state.value,
                "fetch_age_seconds": None if freshness_age is None else int(freshness_age),
                "data_age_seconds": None if data_age is None else int(data_age),
                "updated_label": _label(source, freshness_age),
                "notes": source.notes,
            }
        )
    return out


def _source_freshness(source: Source, fetch_age: float | None) -> FreshnessState:
    if source.last_success_at is None:
        return FreshnessState.UNKNOWN
    # A source is stale when it has missed several of its own refresh intervals.
    budget = max(900, source.refresh_interval_seconds * 4)
    state = freshness_budget_state(fetch_age, budget)
    if state == FreshnessState.STALE and source.status == SourceStatus.FAILING.value:
        return FreshnessState.STALE
    return state


def freshness_budget_state(age_secs: float | None, budget: float) -> FreshnessState:
    if age_secs is None:
        return FreshnessState.UNKNOWN
    if age_secs <= budget * 0.5:
        return FreshnessState.FRESH
    if age_secs <= budget:
        return FreshnessState.RECENT
    if age_secs <= budget * 2:
        return FreshnessState.AGING
    return FreshnessState.STALE


def _label(source: Source, age: float | None) -> str:
    if source.last_success_at is None:
        return "never fetched"
    from shared.timeutils import humanize_age

    base = humanize_age(source.last_success_at)
    if source.status == SourceStatus.FAILING.value:
        return f"last successful update: {base}"
    del age
    return f"updated {base}"


def ingestion_summary(db: Session, limit: int = 40) -> dict[str, Any]:
    runs = list(
        db.execute(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        ).scalars()
    )
    failures = db.execute(
        select(func.count(IngestionRun.id)).where(IngestionRun.status == "error")
    ).scalar_one()
    last_ok = next((r for r in runs if r.status == "ok"), None)
    return {
        "recent_runs": [
            {
                "source": r.source_code,
                "status": r.status,
                "started_at": iso(r.started_at),
                "duration_ms": None
                if not r.finished_at
                else int((r.finished_at - r.started_at).total_seconds() * 1000),
                "records_found": r.records_found,
                "records_new": r.records_new,
                "records_updated": r.records_updated,
                "error": r.error,
            }
            for r in runs
        ],
        "failed_ingestion_count": failures,
        "last_successful_ingestion": iso(last_ok.started_at) if last_ok else None,
    }


def observation_stats(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Observation.kind, func.count(Observation.id)).group_by(Observation.kind)
    ).all()
    return {kind: count for kind, count in rows}


def prune_old_runs(db: Session, keep_days: int = 14) -> int:
    cutoff = utcnow() - timedelta(days=keep_days)
    deleted = db.query(IngestionRun).filter(IngestionRun.started_at < cutoff).delete()
    db.commit()
    return deleted
