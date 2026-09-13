"""The Melamchi scenario, end to end, against the real agent.

    python scripts/scenario_melamchi.py
    python scripts/scenario_melamchi.py --operator sunita.rc
    python scripts/scenario_melamchi.py --text "..." --report-id rep_...
    python scripts/scenario_melamchi.py --cleanup

Nothing in here is mocked or replayed. It calls the same `workflows.respond` that
`POST /api/agent/respond` calls, against the same database the Response Center reads, and
prints the activity timeline that run recorded plus one pass/fail line for each of the
phase's eight completion criteria. The exit code is 0 only when all eight pass.

If Gemini is not configured the run still files the case from the fixed rules - a person
asking for help does not wait on an API key - and every criterion that needs a model is
reported as failed with the provider's own reason. The deterministic answer is never dressed
up as a model run, which is the whole point of printing the mode and the call count.

By default the case stays in the database so it can be opened in the Response Center; pass
`--cleanup` to remove everything this run wrote (the request, its updates, the notification,
the audit rows and the stored run), which is what a repeated check wants.
"""

from __future__ import annotations

import argparse
import sys

from _bootstrap import prepare

prepare()

from sqlalchemy import delete, func, select  # noqa: E402

from agent import model as model_module  # noqa: E402
from backend.app.db import SessionLocal  # noqa: E402
from backend.app.deps import granted_permissions  # noqa: E402
from backend.app.models.core import (  # noqa: E402
    AgentInvestigation,
    AssistanceRequest,
    AssistanceUpdate,
    AuditEvent,
    Notification,
    User,
)
from backend.app.services import agent as agent_service  # noqa: E402
from backend.app.services import response_center  # noqa: E402

REPORT = (
    "My father is injured and we are trapped near Melamchi. "
    "The road is blocked and we need help."
)

# The tools that investigate rather than act. A run whose only tool step is the filing chose to
# check nothing - the rules filed it - so criteria 3 and 4 count these names and ignore the four
# that write. The list is the spec's own eleven.
INVESTIGATION_TOOLS = {
    "GET_RECENT_EARTHQUAKES",
    "GET_OFFICIAL_DISASTER_INCIDENTS",
    "GET_RIVER_STATUS",
    "GET_RAINFALL_STATUS",
    "GET_ROAD_STATUS",
    "GET_COMMUNITY_REPORTS",
    "FIND_RELATED_REPORTS",
    "FIND_NEARBY_SHELTERS",
    "FIND_MEDICAL_RESOURCES",
    "FIND_RELIEF_RESOURCES",
    "GET_INCIDENT_DETAILS",
}

# A step that ran and found nothing still ran: an empty road-status query is a real result about
# a feed that has three rows in it, and it must not be counted as a failure to execute.
EXECUTED = {"ok", "empty"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text", default=REPORT, help="the victim report, in the caller's words")
    parser.add_argument("--operator", default="sunita.rc", help="who runs it (default: an RC operator)")
    parser.add_argument("--report-id", default=None, help="attach a community report, so the case has a reporter")
    parser.add_argument("--incident-id", default=None, help="link a tracked incident")
    parser.add_argument("--cleanup", action="store_true", help="delete everything this run wrote")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        operator = db.execute(
            select(User).where(User.username == args.operator)
        ).scalar_one_or_none()
        if operator is None:
            print(f"No account {args.operator!r}. Sign in with one that has agent:run.")
            return 2

        built = model_module.status()
        print("=" * 78)
        print("SANKET RESPONDER - one victim report through the agent")
        print("=" * 78)
        print(f"provider     : {built.provider or '-'}")
        print(f"model        : {built.model_id or '-'}")
        print(f"credentials  : {'yes' if built.credentials_present else 'NO'}")
        if not built.available:
            print(f"reason       : {built.reason}")
            print("               the fixed rules will still file the case, and the")
            print("               criteria that need a model will be reported as failed.")
        print()
        print(f"report       : {args.text}")
        print(f"operator     : {operator.username} ({operator.role})")
        print("-" * 78)

        # The service, not the workflow: this is the function `POST /api/agent/respond` calls, so
        # the run is stored, its audit row is written, and what is printed below is what the
        # Response Center's own history would show for the same report.
        outcome = agent_service.respond(
            db,
            args.text,
            permissions=granted_permissions(operator),
            operator=operator,
            report_id=args.report_id,
            incident_id=args.incident_id,
        )

        print(f"mode         : {outcome['mode']}")
        print(f"status       : {outcome['status']}")
        print(f"model calls  : {outcome['model_calls']}")
        print(f"duration     : {outcome['duration_ms']} ms")
        if outcome.get("error"):
            print(f"error        : {outcome['error']}")
        print()

        print("ACTIVITY")
        for step in outcome["tool_calls"]:
            mark = " " if step["status"] == "ok" else "*"
            print(
                f"  {mark} {step['at']}  {step['action']:<32} {step['kind']:<5} "
                f"{step['status']:<8} {step.get('detail') or ''}"
            )
        print("  (names, times, statuses and one line of result each - no reasoning, by design)")
        print()

        print("ANSWER")
        for line in (outcome["response_text"] or "").splitlines():
            print(f"  {line}")
        print()

        if outcome.get("rejected_numbers"):
            print(f"REJECTED WORDING - figures no record contains: {outcome['rejected_numbers']}")
            print()

        refs = list(outcome.get("created_requests") or [])
        request = None
        if refs:
            request = db.execute(
                select(AssistanceRequest).where(AssistanceRequest.ref_code == refs[0])
            ).scalar_one_or_none()
            print(f"FILED          : {refs[0]}")
            if request is not None:
                print(f"  urgency      : {request.urgency} ({'; '.join(request.urgency_reasons or [])})")
                print(f"  status       : {request.status}")
                print(f"  for          : {getattr(request.user, 'username', 'no account')}")
                print(f"  location     : {request.location_text} / {request.district}"
                      f" / confidence {request.location_confidence}")
                print(f"  coordinates  : {request.latitude}, {request.longitude} (gazetteer, not the model)")
                print(f"  facilities   : {len(request.matched_resource_ids or [])} matched")
                print(f"  filed by     : {(request.structured or {}).get('filing_route')}")
            print()

        verdict = _criteria(db, outcome, request)
        print("=" * 78)
        print("COMPLETION CRITERIA")
        print("=" * 78)
        failed = 0
        for name, passed, detail in verdict:
            failed += 0 if passed else 1
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            print(f"         {detail}")
        print()
        print(f"{len(verdict) - failed} of {len(verdict)} passed.")

        if args.cleanup:
            _cleanup(db, outcome.get("id"), refs)
            print("\ncleaned up: the request, its updates, notifications, audit rows and the run.")

        return 1 if failed else 0
    finally:
        db.close()


def _criteria(db, outcome: dict, request: AssistanceRequest | None) -> list[tuple[str, bool, str]]:
    steps = outcome["tool_calls"]
    chosen = [s for s in steps if s["kind"] == "tool" and s["action"] in INVESTIGATION_TOOLS]
    ran_model = outcome["mode"] == "strands"

    queue_refs: set[str] = set()
    queue = response_center.action_queue(db)
    for bucket in queue["buckets"].values():
        for entry in bucket:
            queue_refs.add(str(entry.get("ref_code")))

    notified = counted = 0
    filed_by_agent = False
    if request is not None:
        notified = db.execute(
            select(func.count(Notification.id)).where(Notification.request_id == request.id)
        ).scalar_one()
        counted = db.execute(
            select(func.count(AuditEvent.id)).where(AuditEvent.entity_id == request.id)
        ).scalar_one()
        # The case has to say who wrote it. `filing_route` distinguishes the model calling the
        # tool from the fixed rules filing it, which is the difference the criteria are about.
        filed_by_agent = (request.structured or {}).get("filed_by") == "agent"

    return [
        (
            "1. Gemini responds successfully",
            ran_model and not outcome.get("error"),
            f"model {outcome.get('model') or '-'} answered"
            if ran_model
            else f"the provider never answered: {outcome.get('error') or outcome.get('model') or 'no model configured'}",
        ),
        (
            "2. Strands runs the loop",
            ran_model and (outcome.get("model_calls") or 0) >= 1,
            # A counted call and a completed turn are different facts, and the failing case needs
            # to say which one is missing: an invalid key still proves the loop started.
            f"{outcome.get('model_calls')} model call(s) counted by a real hook on the model"
            + (
                ""
                if ran_model
                else "; the call never came back, so the loop did not complete a turn"
            ),
        ),
        (
            "3. The agent selects at least one tool",
            bool(chosen),
            ", ".join(s["action"] for s in chosen)
            or "no investigation tool was chosen; only the fixed rules acted",
        ),
        (
            "4. The tool executes successfully",
            any(s["status"] in EXECUTED for s in chosen),
            "; ".join(f"{s['action'].lower()} -> {s['status']}" for s in chosen) or "nothing ran",
        ),
        (
            "5. The agent uses the tool result",
            # Checked, not assumed: the wording was compared against the report plus every figure
            # this run's tools returned, and it survived. That is the observable form of "it used
            # what it was told" - the alternative is a run that says numbers out of nowhere.
            ran_model and outcome["status"] == "completed" and bool(chosen),
            f"status {outcome['status']}"
            + (
                f"; refused numbers: {outcome['rejected_numbers']}"
                if outcome.get("rejected_numbers")
                else "; every figure in the answer appears in the report or a tool result"
            ),
        ),
        (
            "6. An assistance request is created",
            request is not None and filed_by_agent,
            f"{request.ref_code} in the database, filed by "
            f"{(request.structured or {}).get('filing_route')}"
            if request is not None
            else "nothing was filed",
        ),
        (
            "7. The Response Center reflects the result",
            bool(request) and request.ref_code in queue_refs and notified > 0 and counted > 0,
            f"in the action queue, {notified} notification(s), {counted} audit row(s)"
            if request is not None
            else "no case to show",
        ),
        (
            "8. The scenario runs end to end",
            ran_model and bool(chosen) and request is not None,
            "one report in, tools chosen, one filed case out - in a single run"
            if ran_model and request is not None
            else "this run did not go through the model, so the end-to-end path is unverified",
        ),
    ]


def _cleanup(db, run_id: str | None, refs: list[str]) -> None:
    """Remove exactly what this run wrote, and nothing else. A verification script that deletes
    by subject type would take a real responder's case with it."""
    for ref in refs:
        request = db.execute(
            select(AssistanceRequest).where(AssistanceRequest.ref_code == ref)
        ).scalar_one_or_none()
        if request is None:
            continue
        db.execute(delete(AssistanceUpdate).where(AssistanceUpdate.request_id == request.id))
        db.execute(delete(Notification).where(Notification.request_id == request.id))
        db.execute(delete(AuditEvent).where(AuditEvent.entity_id == request.id))
        db.delete(request)
    if run_id:
        run = db.get(AgentInvestigation, run_id)
        if run is not None:
            db.execute(delete(AuditEvent).where(AuditEvent.entity_id == run_id))
            db.delete(run)
    db.commit()


if __name__ == "__main__":
    sys.exit(main())
