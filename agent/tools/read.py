"""Read-only investigation tools the language model may call.

Three rules, enforced in code rather than in a prompt:

1. **Nothing here writes.** Not one of these functions changes a row. An agent that can
   move a case forward is an agent that can move a case forward wrongly, and the spec
   reserves lifecycle decisions for named humans whose actions land in the audit log.
2. **Nothing here invents.** Every function ends in a call to a service that answers from
   the database. When there is no answer the result is an empty list or an explicit
   `count: 0`, never a plausible-looking fill-in.
3. **Nothing here sees more than the caller.** The router hands in a permission set;
   tools that need one the viewer lacks return a refusal instead of the data. An agent
   run for an analyst must not be a way for an analyst to read the staff audit log.

The tools are built per request because they close over a `Session` and a permission set.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from strands import tool

from backend.app.models.core import Incident, Observation
from backend.app.services import alerts as alert_service
from backend.app.services import assistance as assistance_service
from backend.app.services import audit as audit_service
from backend.app.services import community as community_service
from backend.app.services import incidents as incident_service
from backend.app.services import ingestion
from backend.app.services import notifications as notification_service
from backend.app.services import resources as resource_service
from backend.app.services import response_center as rc_service
from backend.app.services import signals as signal_service
from backend.app.services import state as system_state
from shared.timeutils import iso

# A refusal the model can read. Telling it "no" without a reason produces an agent that
# invents a reason of its own.
_NO_PERMISSION = {"error": "not_permitted", "detail": "The requesting user may not read this."}


def _dump(value: Any) -> str:
    """Tool returns are strings - the model reads text, and a dict it cannot serialize
    would kill the run mid-answer."""
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _incident_by_ref(db: Any, ref: str) -> dict[str, Any]:
    incident = db.execute(select(Incident).where(Incident.ref_code == ref)).scalar_one_or_none()
    if incident is None:
        return {"error": "not_found", "detail": f"No incident with ref_code {ref!r}"}
    return {"found": True, "incident_id": incident.id}


def build_read_tools(db: Any, permissions: set[str] | None) -> list[Any]:
    """Bind every tool to this request's session and permission set.

    `permissions=None` means "the whole system, no viewer" - used by the deterministic
    background paths that are not answering a person.
    """

    def allowed(permission: str) -> bool:
        return permissions is None or permission in permissions

    # ------------------------------------------------------------------ incidents
    @tool
    def search_incidents(
        query: str = "",
        district: str = "",
        incident_type: str = "",
        urgency: str = "",
        limit: int = 10,
    ) -> str:
        """Find incidents. Empty arguments mean 'do not filter'. Returns the ranked list
        with impact score, evidence state, freshness and provenance for each."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        rows = rc_service.list_incidents(
            db,
            incident_type=incident_type or None,
            district=district or None,
            urgency=urgency or None,
            q=query or None,
            limit=min(max(limit, 1), 50),
        )
        # ORM rows, ordered by impact score as the queue is. `incident_summary` is the same
        # projection the operator's list uses, so an agent cannot describe an incident in
        # words the screen does not have.
        return _dump(
            {"count": len(rows), "items": [rc_service.incident_summary(db, row) for row in rows]}
        )

    @tool
    def get_incident(incident_id: str = "", ref_code: str = "") -> str:
        """Everything the Response Center shows for one incident: headline, numbers,
        score breakdown, evidence state, freshness, and the actions a human may take."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        wanted = incident_id or ref_code
        incident = db.get(Incident, wanted) if wanted else None
        if incident is None and ref_code:
            incident = db.execute(
                select(Incident).where(Incident.ref_code == ref_code)
            ).scalar_one_or_none()
        if incident is None:
            return _dump({"error": "not_found", "detail": f"No incident matches {wanted!r}"})
        return _dump(rc_service.incident_detail(db, incident, permissions))

    @tool
    def get_incident_evidence(ref_code: str) -> str:
        """The records an incident actually rests on - source, when it was published,
        when we received it, and what each one asserts."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        found = _incident_by_ref(db, ref_code)
        if "error" in found:
            return _dump(found)
        detail = rc_service.incident_detail(db, db.get(Incident, found["incident_id"]), permissions)
        # `evidence` is a block with a state, a plain-language meaning and the record list;
        # flattening it to just the records loses "how sure is the system".
        return _dump(
            {
                "ref_code": ref_code,
                "evidence": detail.get("evidence", {}),
                "why_prioritized": detail.get("why_prioritized", {}),
            }
        )

    @tool
    def get_incident_timeline(ref_code: str) -> str:
        """Every observation and report that joined this incident, in order, so the
        growth of a situation is visible."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        found = _incident_by_ref(db, ref_code)
        if "error" in found:
            return _dump(found)
        incident = db.get(Incident, found["incident_id"])
        rows = incident_service.timeline(db, incident)
        return _dump({"ref_code": ref_code, "count": len(rows), "events": rows[:60]})

    @tool
    def get_incident_reports(ref_code: str, limit: int = 20) -> str:
        """Community reports attached to an incident, with location confidence and
        whether each one was verified."""
        if not allowed("reports:read"):
            return _dump(_NO_PERMISSION)
        found = _incident_by_ref(db, ref_code)
        if "error" in found:
            return _dump(found)
        incident = db.get(Incident, found["incident_id"])
        rows = incident_service.related_reports(db, incident, limit=min(max(limit, 1), 50))
        return _dump(
            {
                "count": len(rows),
                "items": [community_service.report_to_dict(db, row) for row in rows],
            }
        )

    # ------------------------------------------------------------------ observations
    @tool
    def search_observations(
        district: str = "",
        kind: str = "",
        source_code: str = "",
        since_hours: int = 48,
        limit: int = 20,
    ) -> str:
        """Raw source records, before they became an incident. Use this to check what a
        bulletin actually said rather than what an incident summary claims."""
        if not allowed("sources:read"):
            return _dump(_NO_PERMISSION)
        stmt = select(Observation).order_by(Observation.received_at.desc())
        if district:
            stmt = stmt.where(Observation.district == district)
        if kind:
            stmt = stmt.where(Observation.kind == kind)
        if source_code:
            stmt = stmt.where(Observation.source_id == source_code)
        rows = list(db.execute(stmt.limit(min(max(limit, 1), 50))).scalars())
        return _dump(
            {
                "count": len(rows),
                "items": [
                    {
                        "source": row.source_id,
                        "kind": row.kind,
                        "title": row.title,
                        "district": row.district,
                        "event_time": iso(row.event_time),
                        "received_at": iso(row.received_at),
                        "severity": row.severity,
                        "provenance": row.provenance,
                        "has_location": row.latitude is not None,
                    }
                    for row in rows
                ],
            }
        )

    @tool
    def get_source_health() -> str:
        """Each official source, whether it answered, when it last did, and its failure."""
        if not allowed("sources:read"):
            return _dump(_NO_PERMISSION)
        rows = ingestion.source_health(db)
        return _dump(
            {
                "count": len(rows),
                "items": [
                    {
                        "code": row.get("code"),
                        "name": row.get("name"),
                        "status": row.get("status"),
                        "last_success_at": row.get("last_success_at"),
                        "freshness_state": row.get("freshness_state"),
                        "last_error": row.get("last_error"),
                    }
                    for row in rows
                ],
            }
        )

    @tool
    def get_ingestion_summary() -> str:
        """Recent ingestion runs and how many observations each kind produced."""
        if not allowed("sources:read"):
            return _dump(_NO_PERMISSION)
        summary = ingestion.ingestion_summary(db, limit=15)
        summary["observation_counts"] = ingestion.observation_stats(db)
        return _dump(summary)

    # ------------------------------------------------------------------ signals, alerts
    @tool
    def get_risk_signals(district: str = "") -> str:
        """District-level risk signals: which conditions raised them and how fresh."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        rows = signal_service.active_signals(db)
        out = [signal_service.signal_to_dict(row) for row in rows]
        if district:
            out = [row for row in out if row.get("district") == district]
        return _dump({"count": len(out), "items": out[:30]})

    @tool
    def get_official_alerts(district: str = "", limit: int = 15) -> str:
        """Alerts published by official bodies, with the source that published each."""
        if not allowed("alerts:read"):
            return _dump(_NO_PERMISSION)
        rows = alert_service.list_alerts(
            db, district=district or None, limit=min(max(limit, 1), 40)
        )
        return _dump({"count": len(rows), "items": rows})

    @tool
    def get_latest_alert(district: str) -> str:
        """The most recent official alert for one district, or an explicit none."""
        if not allowed("alerts:read"):
            return _dump(_NO_PERMISSION)
        row = alert_service.latest_for_district(db, district)
        return _dump(row or {"found": False, "detail": f"No official alert for {district!r}"})

    # ------------------------------------------------------------------ resources
    @tool
    def search_resources(
        resource_type: str = "",
        district: str = "",
        availability: str = "",
        limit: int = 20,
    ) -> str:
        """The facility catalogue - hospitals, health posts, police posts, helipads and
        more. Each row says where it came from and when its availability was last known."""
        if not allowed("resources:read"):
            return _dump(_NO_PERMISSION)
        rows = resource_service.list_resources(
            db,
            resource_type=resource_type or None,
            district=district or None,
            availability=availability or None,
            limit=min(max(limit, 1), 50),
        )
        return _dump(
            {
                "count": len(rows),
                "items": [resource_service.to_dict(row) for row in rows],
                "note": "availability 'unknown' means nobody has confirmed it recently, not that the facility is shut",
            }
        )

    @tool
    def get_resource_coverage() -> str:
        """How many facilities are known per type and per availability, plus how the
        OpenStreetMap seed went. Answers 'is this catalogue real or nearly empty?'."""
        if not allowed("resources:read"):
            return _dump(_NO_PERMISSION)
        counts = resource_service.counts(db)
        counts["seed"] = resource_service.seed_status()
        return _dump(counts)

    @tool
    def get_nearby_resources(ref_code: str, limit: int = 8) -> str:
        """Facilities that could actually serve one help request, ordered by distance."""
        if not allowed("resources:read"):
            return _dump(_NO_PERMISSION)
        request = assistance_service.get_by_ref(db, ref_code)
        if request is None:
            return _dump({"error": "not_found", "detail": f"No request {ref_code!r}"})
        matched = assistance_service.match_resources(db, request, limit=min(max(limit, 1), 20))
        return _dump({"request": ref_code, "count": len(matched), "items": matched})

    # ------------------------------------------------------------------ requests
    @tool
    def search_requests(
        status: str = "",
        urgency: str = "",
        district: str = "",
        unassigned_only: bool = False,
        limit: int = 25,
    ) -> str:
        """Help requests people have made, with their lifecycle state."""
        if not allowed("assistance:read"):
            return _dump(_NO_PERMISSION)
        rows = rc_service.list_requests(
            db,
            status=status or None,
            urgency=urgency or None,
            district=district or None,
            unassigned_only=unassigned_only,
            limit=min(max(limit, 1), 100),
        )
        # These are ORM rows; handing them to the model raw would serialize to a memory
        # address, so each one goes through the same serializer the screen uses.
        return _dump(
            {
                "count": len(rows),
                "items": [assistance_service.to_dict(db, row) for row in rows],
            }
        )

    @tool
    def get_request(ref_code: str) -> str:
        """One request in full: what was asked, who asked, what the plan is, which
        facilities matched, and the SLA clock."""
        if not allowed("assistance:read"):
            return _dump(_NO_PERMISSION)
        request = assistance_service.get_by_ref(db, ref_code)
        if request is None:
            return _dump({"error": "not_found", "detail": f"No request {ref_code!r}"})
        payload = assistance_service.to_dict(db, request)
        payload["sla"] = assistance_service.sla_info(request)
        payload["timeline"] = assistance_service.timeline(db, request)
        return _dump(payload)

    @tool
    def get_breached_slas() -> str:
        """Open requests whose response deadline has passed unacknowledged."""
        if not allowed("assistance:read"):
            return _dump(_NO_PERMISSION)
        queue = rc_service.action_queue(db, limit_per_bucket=50)
        breached: list[Any] = []
        for urgency, rows in queue.get("buckets", {}).items():
            for row in rows:
                if (row.get("sla") or {}).get("breached"):
                    breached.append({"urgency": urgency, **row})
        return _dump({"count": len(breached), "items": breached[:40]})

    # ------------------------------------------------------------------ the whole board
    @tool
    def get_action_queue() -> str:
        """The Response Center queue as an operator sees it, bucketed by urgency."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        queue = rc_service.action_queue(db, limit_per_bucket=10)
        return _dump(
            {
                "buckets": [
                    {
                        "urgency": key,
                        "count": queue.get("counts", {}).get(key, len(rows)),
                        "top": [
                            {
                                "kind": row.get("kind"),
                                "ref_code": row.get("ref_code"),
                                "title": row.get("title"),
                                "district": row.get("district"),
                                "why": row.get("why"),
                                "age": row.get("age"),
                                "demo": row.get("demo"),
                            }
                            for row in rows[:5]
                        ],
                    }
                    for key, rows in queue.get("buckets", {}).items()
                    if rows
                ],
                "total_open_requests": queue.get("total_open_requests"),
                "sla_breaches": queue.get("sla_breaches"),
                "unacknowledged_critical": queue.get("unacknowledged_critical"),
            }
        )

    @tool
    def get_dashboard() -> str:
        """The counters on the front screen: incidents by state, requests by urgency,
        source health, community volume."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        return _dump(rc_service.dashboard(db))

    @tool
    def get_recent_reports(district: str = "", limit: int = 20) -> str:
        """What people are reporting right now, newest first."""
        if not allowed("reports:read"):
            return _dump(_NO_PERMISSION)
        rows = community_service.recent_reports(
            db, district=district or None, limit=min(max(limit, 1), 50)
        )
        return _dump(
            {
                "count": len(rows),
                "items": [community_service.report_to_dict(db, row) for row in rows],
            }
        )

    @tool
    def get_activity_feed(limit: int = 25) -> str:
        """What just happened across the system - the strip at the bottom of the screen."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        rows = rc_service.activity_feed(db, limit=min(max(limit, 1), 60))
        return _dump({"count": len(rows), "items": rows})

    @tool
    def get_response_centre_notifications(limit: int = 20) -> str:
        """Unread notices the Response Center holds, each naming what triggered it."""
        if not allowed("incidents:read"):
            return _dump(_NO_PERMISSION)
        rows = notification_service.for_response_center(db, limit=min(max(limit, 1), 50))
        return _dump(
            {
                "count": len(rows),
                "items": [notification_service.to_dict(row) for row in rows],
            }
        )

    # ------------------------------------------------------------------ audit
    @tool
    def get_audit_trail(ref_code: str = "", limit: int = 30, actor_kind: str = "") -> str:
        """Who changed what. With a ref_code, only that incident's history."""
        if not allowed("audit:read"):
            return _dump(_NO_PERMISSION)
        incident = None
        if ref_code:
            found = _incident_by_ref(db, ref_code)
            if "error" in found:
                return _dump(found)
            incident = found["incident_id"]
        rows = (
            audit_service.for_entity(db, audit_service.ENTITY_INCIDENT, incident, limit=limit)
            if incident
            else audit_service.recent(
                db, limit=min(max(limit, 1), 100), actor_kind=actor_kind or None
            )
        )
        return _dump(
            {
                "count": len(rows),
                "items": [audit_service.to_dict(row) for row in rows],
            }
        )

    # ------------------------------------------------------------------ local situation
    @tool
    def get_community_feed(district: str = "") -> str:
        """What a resident in a district would see: official alerts, nearby situations."""
        if not allowed("alerts:read"):
            return _dump(_NO_PERMISSION)
        feed = community_service.local_feed(db, user=None, district=district or None)
        return _dump(
            {
                "alerts": feed.get("alerts", [])[:10],
                "signals": feed.get("signals", [])[:10],
                "incidents": feed.get("incidents", [])[:10],
                "counts": feed.get("counts"),
                "empty_message": feed.get("empty_message"),
            }
        )

    @tool
    def get_system_mode() -> str:
        """Whether this deployment is on live data or a rehearsal, and what that means.
        Call it before saying anything is 'current'."""
        mode = system_state.system_mode(db)
        return _dump(
            {
                "mode": mode.get("mode", "live"),
                "scenario_id": mode.get("scenario_id"),
                "armed_at": mode.get("armed_at"),
                "sim_clock": mode.get("sim_clock"),
                "warning": (
                    "Demo mode is armed: situations, reports and requests labelled demo are "
                    "scripted, and live polling is paused while it is. Facilities are real."
                    if mode.get("mode") == "demo"
                    else None
                ),
            }
        )

    return [
        search_incidents,
        get_incident,
        get_incident_evidence,
        get_incident_timeline,
        get_incident_reports,
        search_observations,
        get_source_health,
        get_ingestion_summary,
        get_risk_signals,
        get_official_alerts,
        get_latest_alert,
        search_resources,
        get_resource_coverage,
        get_nearby_resources,
        search_requests,
        get_request,
        get_breached_slas,
        get_action_queue,
        get_dashboard,
        get_recent_reports,
        get_activity_feed,
        get_response_centre_notifications,
        get_audit_trail,
        get_community_feed,
        get_system_mode,
    ]
