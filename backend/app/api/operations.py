"""Sources, alerts, notifications and system status.

The data-availability panel lives here: if an official source is unreachable, this
is where the interface learns it, and the answer it gets is the failure, not a
cached or invented substitute.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.deps import current_user, get_db, require_permission, system_mode
from backend.app.models.core import IngestionRun, User
from backend.app.scheduler import report as worker_report
from backend.app.services import alerts as alert_service
from backend.app.services import ingestion, notifications
from backend.app.services import signals as signal_service
from shared.enums import Role, SourceStatus
from shared.timeutils import iso, utcnow

router = APIRouter(tags=["operations"])


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Unauthenticated on purpose: a probe that needs a token is useless."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "time": iso(utcnow()),
        "mode": system_mode(db),
    }


@router.get("/system/status")
def system_status(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The honesty panel: what is live, what is failing, what is demo."""
    health_rows = ingestion.source_health(db)
    mode = system_mode(db)
    payload: dict[str, Any] = {
        "time": iso(utcnow()),
        "mode": mode,
        "ingestion_enabled": settings.ingestion_enabled,
        # `ingestion_enabled` is the setting, which is not the same fact as the thread being alive.
        # Reporting both is what lets "the feed stopped" be answered without reading a log.
        "ingestion_worker": worker_report(getattr(request.app.state, "worker", None)),
        "sources_total": len(health_rows),
        # `Source.status` is healthy/degraded/failing/never_fetched. A *run* result
        # says "ok"; the source row does not, and conflating them reported every
        # healthy source as unhealthy.
        "sources_healthy": sum(
            1 for row in health_rows if row.get("status") == SourceStatus.HEALTHY.value
        ),
        "sources_failing": [
            {"code": row.get("code"), "status": row.get("status"), "last_error": row.get("last_error")}
            for row in health_rows
            if row.get("status") in {"failing", "degraded"}
        ],
        "llm": {
            "configured": settings.has_model_credentials,
            "provider": settings.model_provider,
            "model": settings.strands_model if settings.has_model_credentials else None,
            "note": (
                None
                if settings.has_model_credentials
                else "No model credentials found - language understanding runs in the deterministic "
                "fallback, which answers with retrieved data only and never invents text."
            ),
        },
    }
    if user.role == Role.RESPONSE_CENTER.value:
        # Operators additionally see which sources are repeatedly failing.
        payload["recent_failures"] = [
            row for row in health_rows if (row.get("last_error") and row.get("consecutive_failures", 0) > 0)
        ][:10]
    return payload


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
@router.get("/sources")
def list_sources(
    request: Request,
    _user: User = Depends(require_permission("sources:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-source health, plus the one fact the table cannot show: whether the worker that is
    supposed to be filling it is running. Every row can read `healthy` with a check from an hour
    ago because nothing polled - which is indistinguishable from a stalled feed by table alone."""
    return {
        "items": ingestion.source_health(db),
        "worker": worker_report(getattr(request.app.state, "worker", None)),
        "generated_at": iso(utcnow()),
    }


@router.post("/sources/{code}/run")
def run_source(
    code: str,
    _user: User = Depends(require_permission("sources:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    report = ingestion.run_source(db, code)
    if report.get("status") == "skipped":
        raise HTTPException(status.HTTP_404_NOT_FOUND, report.get("error") or "Unknown source")
    return report


@router.post("/sources/run-due")
def run_due(
    request: Request,
    now: bool = Query(
        default=False,
        description="Hand the poll to the ingestion worker instead of fetching in this request",
    ),
    _user: User = Depends(require_permission("sources:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Poll the sources whose interval has elapsed, and report what each one answered.

    `?now=true` is a different promise, so it does a different thing: it asks the worker for a pass
    over every enabled source and returns immediately, before that pass has happened. Eight agency
    servers cannot be fetched inside a screen's wait, and a console that showed a spinner until they
    all answered would look broken while it was working. The `refresh` block says what was queued
    and the `worker` block carries the counter the caller watches to see the pass land.
    """
    if now:
        worker = getattr(request.app.state, "worker", None)
        ack = (
            worker.request_refresh()
            if worker is not None
            else {
                "triggered": False,
                "forced": False,
                "reason": "no ingestion worker in this process",
                "cycles": 0,
                "floor_seconds": None,
            }
        )
        return {"ran": {}, "due_now": ingestion.due_sources(db), "refresh": ack, "worker": worker_report(worker)}
    return {"ran": ingestion.run_due_sources(db) or {}, "due_now": ingestion.due_sources(db)}


@router.get("/sources/runs")
def recent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(require_permission("sources:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list(
        db.execute(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "source": row.source_code,
                "started_at": iso(row.started_at),
                "finished_at": iso(row.finished_at),
                "status": row.status,
                "records_found": row.records_found,
                "records_new": row.records_new,
                "records_updated": row.records_updated,
                "error": (row.error or "")[:400] or None,
            }
            for row in rows
        ]
    }


# --------------------------------------------------------------------------- #
# Signals / alerts
# --------------------------------------------------------------------------- #
@router.get("/signals")
def list_signals(
    district: str | None = None,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = [
        signal_service.signal_to_dict(row)
        for row in signal_service.active_signals(db)
        if district is None or row.district == district
    ]
    return {"items": rows}


@router.post("/signals/rebuild")
def rebuild_signals(
    _user: User = Depends(require_permission("sources:run")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return signal_service.rebuild_signals(db)


@router.get("/alerts")
def list_alerts(
    district: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    include_undated: bool = False,
    _user: User = Depends(require_permission("alerts:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Official alerts, quoted verbatim from the issuing agency."""
    return {
        "items": alert_service.list_alerts(
            db, district=district, limit=limit, include_undated=include_undated
        ),
        "generated_at": iso(utcnow()),
    }


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
@router.get("/notifications")
def my_notifications(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope = _inbox_scope(user)
    if scope["audience"] is not None:
        rows = notifications.for_response_center(db)
    else:
        rows = notifications.for_user(db, user.id, district=user.home_district)
    return {
        "items": [notifications.to_dict(row) for row in rows],
        "unread": notifications.unread_count(db, **scope),
    }


@router.get("/notifications/unread-count")
def notification_unread_count(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Just the badge number - the interface polls this, not the whole inbox."""
    return {"unread": notifications.unread_count(db, **_inbox_scope(user))}


def _inbox_scope(user: User) -> dict[str, Any]:
    """One place decides whose notifications a caller may see: an operator sees the
    Response Center audience, a resident sees their own plus their district."""
    if user.role == Role.RESPONSE_CENTER.value:
        return {"user_id": None, "audience": notifications.AUDIENCE_RESPONSE_CENTER}
    return {"user_id": user.id, "audience": None}


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ok = notifications.mark_read(db, notification_id, user.id if user.role == Role.COMMUNITY.value else None)
    db.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such notification for this account")
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if user.role == Role.RESPONSE_CENTER.value:
        count = notifications.mark_all_read(db, audience=notifications.AUDIENCE_RESPONSE_CENTER)
    else:
        count = notifications.mark_all_read(db, user_id=user.id)
    db.commit()
    return {"marked": count}
