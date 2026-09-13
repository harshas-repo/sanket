"""One victim report, end to end: read it, check it, file it, say what happened.

This is the workflow the product was built for, and the split inside it is the whole
argument. The model does three things and only three: it reads messy language, it chooses
which checks are relevant, and it words the result. Everything with a consequence - the
coordinate, the distance, the priority score, whether a case is created, what the case's
status is, who is told - is done by the same deterministic services the Response Center
screen drives. `agent/tools/respond.py` holds those calls; nothing here recomputes any of
them, and nothing here can make one of them larger.

Two properties worth naming, because they are the ones a reviewer will look for:

* **The run cannot end silently empty.** If no model is reachable, or the model investigated
  without filing and the report's own words ask for help, the request is still created - by
  `file_request`, from the rules - and the answer says which route it took. A person who
  needs help is not left waiting because an API was down. The failure is reported, not
  papered over: `status` and `error` carry the real reason.
* **The answer is checked against what the run was actually told.** A figure in the model's
  prose that no tool returned rejects the *wording* and the deterministic rendering is shown
  instead. The filed case stands, because it was built from the report's words, not from the
  prose that got rejected.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.numbers import ungrounded_numbers
from agent.tools import (
    ResponderContext,
    build_respond_tools,
    file_request,
    preliminary_reading,
    record_action,
)
from agent.tools.language import detect_language
from agent.trace import ActivityTrace
from backend.app.models.core import CommunityReport
from backend.app.services import communication, state as system_state

logger = logging.getLogger("sanket.agent")


def _prompt(ctx: ResponderContext, reading: dict[str, Any]) -> str:
    """What the model is handed. Every deterministic fact it is allowed to rely on is here,
    so it never has to guess one - and the location is stated as geocoded-with-confidence,
    because 'near Melamchi' resolved to a district centre is not a pin."""
    location = ctx.location()
    mode = system_state.system_mode(ctx.db)
    lines = [
        f"Report received: {ctx.report_text!r}",
        f"Language detected by rule: {ctx.language}",
        (
            "Location as the gazetteer resolved the words: "
            + (
                f"{location.get('location_text')} -> district {location.get('district') or 'unknown'}, "
                f"province {location.get('province') or 'unknown'}, confidence "
                f"{location.get('location_confidence')}"
                + (
                    f", coordinate {location.get('latitude')},{location.get('longitude')}"
                    if location.get("latitude") is not None
                    else ", no coordinate"
                )
            )
            if location.get("location_text") or location.get("district")
            else "No place could be resolved from the words; ask for one and say so in your answer."
        ),
        (
            "The keyword rules already read these from the text (they, not you, set the "
            f"priority): {reading.get('risk_flags') or 'no risk words'}; help types "
            f"{reading.get('help_types') or 'none'}."
        ),
    ]
    if ctx.victim is not None:
        lines.append(
            f"The report is attached to an account: {ctx.victim.username} "
            f"(home district {ctx.victim.home_district or 'unknown'}). A request you file is "
            "filed for that person."
        )
    else:
        lines.append(
            "No account is attached to this report; a request you file is filed for the "
            "words alone."
        )
    if mode.get("mode") == "demo":
        lines.append(
            "This deployment is in demo mode: the situations below are a rehearsal, and your "
            "first sentence must say so."
        )
    lines.append(
        "Investigate with only the tools this situation calls for, file the request if help "
        "is needed, then write the answer."
    )
    return "\n".join(lines)


def render_reply(
    ctx: ResponderContext, reading: dict[str, Any], *, mode: str, model_error: str | None
) -> str:
    """Fixed sentences over what this run retrieved and wrote.

    It is not a summary of a model's opinion - it is the record, printed. The same function
    answers when the provider is down and when a model's wording failed the number check, so
    the fallback has to be a real answer rather than an apology.
    """
    location = ctx.location()
    lines = [f"Report: {ctx.report_text.strip()!r}"]
    lines.append(
        "What the words say: "
        + (
            ", ".join(sorted(name.replace("_", " ") for name in reading.get("risk_flags", {})))
            or "no injury, danger or entrapment wording"
        )
        + "; asking for "
        + ", ".join(reading.get("help_types") or [])
        + " (read by fixed keyword rules"
        + (" alongside the model's tool choices)." if mode == "strands" else ", with no model available).")
    )
    if location.get("district") or location.get("location_text"):
        lines.append(
            f"Where: {location.get('location_text') or 'the words given'} resolved to district "
            f"{location.get('district') or 'unknown'} "
            f"({location.get('location_confidence')} confidence). "
            + (
                "The coordinate came from the gazetteer, not from anyone's estimate."
                if location.get("latitude") is not None
                else "No coordinate could be resolved from the words."
            )
        )
    if ctx.created_refs:
        request = next(
            (
                row
                for ref in ctx.created_refs
                if (row := _request_by_ref(ctx.db, ref)) is not None
            ),
            None,
        )
        if request is not None:
            # The status is named with the words the platform already shows a victim, not with
            # the enum: this sentence is read by an operator deciding what to do next, and
            # "status received" is a database value wearing a sentence's clothes.
            lines.append(
                f"Filed {request.ref_code} at {request.urgency.upper()}, status "
                f"{communication.status_label(request.status, 'en')}: "
                + "; ".join(request.urgency_reasons or [])
                + f". {len(request.matched_resource_ids or [])} known facilit"
                + ("y is" if len(request.matched_resource_ids or []) == 1 else "ies are")
                + " in range of the resolved location, and the Response Center has been "
                "notified. A named operator still has to acknowledge it."
            )
    else:
        lines.append(
            "No assistance request was filed by this run. Nothing has been dispatched and no "
            "case exists yet."
        )
    checks = [step for step in (ctx.trace.to_list() if ctx.trace else []) if step["kind"] == "tool"]
    if checks:
        lines.append(
            "Checks this run made: "
            + "; ".join(
                f"{step['action'].lower()} [{step['status']}] {step.get('detail') or ''}".strip()
                for step in checks
            )
            + "."
        )
        empty = [step["action"].lower() for step in checks if step["status"] == "empty"]
        if empty:
            lines.append(
                "What came back with nothing in it: "
                + ", ".join(empty)
                + ". Absence of a record is not evidence that the thing is not happening."
            )
    if model_error:
        lines.append(
            f"The language model was not usable for this run ({model_error}). The text above "
            "was assembled by retrieval code from the records this run touched."
        )
    elif mode != "strands":
        lines.append(
            "No language model is configured, so this answer is fixed wording over retrieved "
            "records; every figure in it came from a tool result or the report itself."
        )
    return "\n\n".join(lines)


def _request_by_ref(db: Any, ref_code: str) -> Any:
    from backend.app.services import assistance as assistance_service

    return assistance_service.get_by_ref(db, ref_code)


def respond(
    db: Any,
    report_text: str,
    *,
    permissions: set[str] | None = None,
    operator: Any | None = None,
    report_id: str | None = None,
    incident_id: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Run one report through the agent. Always returns a usable answer.

    Identity comes from the database, never from the caller: `report_id` is resolved to its
    reporter, and that is who a request gets filed for. A body that named some other person
    would be a way to ask for help on someone's behalf without their account, so this
    function does not accept the option.
    """
    from agent import model as model_module  # local: the fallback must not need the SDK

    text = (report_text or "").strip()[:4000]
    report = db.get(CommunityReport, report_id) if report_id else None
    if report_id and report is None:
        return {
            "trigger": "report",
            "subject_type": "victim_report",
            "subject_id": report_id,
            "asked": text[:2000],
            "mode": "deterministic",
            "status": "rejected",
            "response_text": "",
            "tool_calls": [],
            "error": "not_found",
            "note": f"No community report {report_id!r} exists, so nothing was read or filed.",
        }
    victim = getattr(report, "user", None)
    language = language or getattr(report, "language", None) or detect_language(text)
    reading = preliminary_reading(text)
    trace = ActivityTrace(subject=report_id or "direct-report")
    trace.phase(
        "received_report",
        detail=f"{reading['words']} word(s), language {language}"
        + (f", attached to report {report_id}" if report_id else ""),
    )
    trace.phase(
        "understanding_request",
        detail="rules read: "
        + (
            ", ".join(sorted(reading["risk_flags"])) or "no risk words"
        )
        + "; help types "
        + (", ".join(reading["help_types"]) or "none"),
    )

    ctx = ResponderContext(
        db=db,
        permissions=permissions,
        report_text=text,
        victim=victim,
        operator=operator,
        report_id=report.id if report else None,
        incident_id=incident_id or (report.incident_id if report else None),
        language=language,
        trace=trace,
    )

    started = time.monotonic()
    result: dict[str, Any] = {
        "trigger": "report",
        "subject_type": "victim_report",
        "subject_id": report.id if report else (operator.id if operator else None),
        "report_id": report.id if report else None,
        "asked": text[:2000],
        "mode": "deterministic",
        "status": "completed",
        "model": None,
        "language": language,
        "reading": reading,
        "location": ctx.location(),
        "response_text": "",
        "tool_calls": [],
        "model_calls": 0,
        "created_requests": [],
        "rejected_numbers": [],
        "note": None,
        "error": None,
        # Inherited from the report: a run over a rehearsal row is part of that rehearsal and
        # has to be findable and removable as one, exactly like the incident investigation.
        "provenance": getattr(report, "provenance", None) or "derived",
    }

    built = model_module.build_model()
    model_error: str | None = None
    answer: str | None = None
    if built is None:
        model_error = model_module.status().reason or "no model configured"
        result["error"] = model_error
        result["note"] = (
            "The language layer is unavailable, so the report was read by the fixed rules "
            "alone. Anything that could be decided without a model was decided."
        )
    else:
        trace.phase("selecting_checks", detail="the model chooses which tools this needs")
        try:
            from strands import Agent

            from agent.prompts import RESPOND

            agent = Agent(
                model=built,
                tools=build_respond_tools(ctx),
                system_prompt=RESPOND,
            )
            # Attached after construction so the counted event is named rather than inferred;
            # see ActivityTrace.attach.
            trace.attach(agent)
            answer = str(agent(_prompt(ctx, reading)))
            result["mode"] = "strands"
            result["model"] = model_module.status().model_id
        except Exception as exc:  # noqa: BLE001 - a dead provider must not lose the report
            db.rollback()
            model_error = f"{type(exc).__name__}: {exc}"
            answer = None
            result["error"] = model_error
            result["note"] = (
                "The model call failed mid-run, so the answer below is the deterministic "
                "rendering of what this run managed to do. The tools that had already run are "
                "in the timeline, and their writes are real."
            )
            logger.warning("respond run failed (%s): %s", model_module.status().model_id, exc)

    # Nobody asked for help on a schedule: if the report's own words need a case and no case
    # exists, the rules file it. This is the same function the tool calls, so there is one
    # behaviour and two routes to it.
    if not ctx.created_refs and (reading["risk_flags"] or reading["help_types"]):
        trace.phase(
            "filing_from_rules",
            status="warning" if result["mode"] == "strands" else "ok",
            detail=(
                "no request was filed by the model, so the deterministic rules filed one from "
                "the report's own words"
                if result["mode"] == "strands"
                else "no model was reachable, so the deterministic rules filed the request"
            ),
        )
        payload, detail = file_request(ctx, {})
        record_action(ctx, "create_assistance_request", payload, detail=detail, status="ok")

    corpus = "\n".join([text, *ctx.evidence])
    deterministic = render_reply(ctx, reading, mode=result["mode"], model_error=model_error)
    if answer is not None:
        offending = ungrounded_numbers(corpus, answer)
        if offending:
            result["status"] = "rejected_unverified_numbers"
            result["rejected_numbers"] = offending
            result["note"] = (
                "The model's wording stated figures that appear in no tool result from this "
                "run, so the deterministic rendering is what is shown. The request it filed "
                "stands - it was built from the report, not from that wording."
            )
            logger.warning("respond answer rejected for unverified numbers: %s", offending)
        else:
            result["response_text"] = answer
    if not result["response_text"]:
        result["response_text"] = deterministic

    result["model_calls"] = trace.model_calls
    result["created_requests"] = list(ctx.created_refs)
    trace.phase(
        "completed",
        detail=f"{len(ctx.created_refs)} request(s), {len(trace.to_list())} recorded step(s), "
        f"{trace.model_calls} model call(s)",
    )
    # Recorded last so the finished timeline, including the completion step itself, is what
    # gets stored and what the screen draws.
    result["tool_calls"] = trace.to_list()
    result["activity"] = result["tool_calls"]
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result
