"""Investigation: gather with code, word with a model, verify with code.

The split is the whole design. `gather_findings()` decides what is known by calling the
same services the Response Center screen calls - no model in that path, so the set of
facts cannot depend on a prompt. The model is then given those facts and asked for
phrasing. If no model is reachable, `render_findings()` writes the same content in fixed
sentences, which is why the product still answers on a laptop with no keys.

`check_numbers()` is the guardrail. Numbers are the expensive kind of hallucination in a
disaster system, so any figure in the model's answer that appears neither in the findings it
was given nor in what it retrieved during the run rejects the answer, and the deterministic text
is what the operator reads. The rejection is stored, not swallowed - an agent that quietly gets
overridden is an agent nobody can improve.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from typing import Any

from agent.numbers import ungrounded_numbers
from agent.trace import ActivityTrace
from backend.app.models.core import Incident
from backend.app.services import ingestion
from backend.app.services import resources as resource_service
from backend.app.services import response_center as rc_service
from backend.app.services import state as system_state
from shared.timeutils import humanize_age, iso

logger = logging.getLogger("sanket.agent")


# --------------------------------------------------------------------------- #
# What is known - decided by code
# --------------------------------------------------------------------------- #
def gather_findings(
    db: Any, incident: Incident, permissions: set[str] | None = None
) -> dict[str, Any]:
    """Everything an investigation may claim, as data.

    It is built on `incident_detail` rather than on fresh queries on purpose: that is the
    same projection the operator's screen reads, so the agent and the human cannot end up
    with two different pictures of one event, and it already respects the viewer's
    permissions.
    """
    detail = rc_service.incident_detail(db, incident, permissions)
    evidence_block = detail.get("evidence", {}) or {}
    records = evidence_block.get("records", []) or []
    official = [row for row in records if row.get("official")]
    impact = incident.impact or {}
    freshness = impact.get("freshness_state", "unknown")

    known: list[str] = [
        f"evidence state is {evidence_block.get('state', incident.evidence_state)}"
    ]
    unknown: list[str] = []

    for field, phrase in (
        ("deaths", "deaths"),
        ("injured", "injuries"),
        ("affected_people", "people affected"),
        ("houses_damaged", "houses damaged"),
    ):
        value = impact.get(field)
        if value is not None:
            source = incident.confirmed_by_source or "an official record"
            known.append(f"{value} {phrase} per {source}")
        else:
            unknown.append(f"no official figure for {phrase} has been published")

    if incident.latitude is None:
        unknown.append("the location is not pinned to a coordinate")
    elif incident.location_precision in {"district_centroid", None}:
        unknown.append(
            "the coordinate is a district centre, not the event - do not read a street from it"
        )
    if not official:
        unknown.append("no official source record backs this yet; it stands on community reports")

    known.append(f"the newest word is {humanize_age(incident.last_updated_at) or 'unrecorded'} old")
    known.append(f"freshness of that newest word: {freshness}")

    facilities: list[dict[str, Any]] = []
    if permissions is None or "resources:read" in permissions:
        facilities = [
            resource_service.to_dict(row)
            for row in resource_service.list_resources(db, district=incident.district, limit=8)
        ]
        if not facilities:
            unknown.append(
                f"the facility catalogue has no entry for {incident.district or 'this area'}"
            )

    failing = [
        row
        for row in ingestion.source_health(db)
        if row.get("status") in {"failing", "degraded"}
    ]

    return {
        "incident": {
            "ref_code": incident.ref_code,
            "title": incident.title,
            "type": incident.incident_type,
            "district": incident.district,
            "province": incident.province,
            "urgency": incident.urgency,
            "severity": incident.severity,
            "evidence_state": incident.evidence_state,
            "official_confirmation": incident.official_confirmation,
            "provenance": incident.provenance,
            "impact_score": incident.impact_score,
            "score_band": (detail.get("why_prioritized") or {}).get("score_band"),
            "score_components": (detail.get("why_prioritized") or {}).get("components"),
            "prioritization_reasons": incident.prioritization_reasons,
            "first_detected_at": iso(incident.first_detected_at),
            "last_updated_at": iso(incident.last_updated_at),
            "needs_review": incident.needs_review,
            "review_reason": incident.review_reason,
            "counts": {
                "community_reports": incident.community_report_count,
                "assistance_requests": incident.assistance_request_count,
                "open_requests": incident.open_assistance_count,
                "supporting_evidence": incident.supporting_signal_count,
                "conflicting_evidence": incident.conflicting_signal_count,
            },
        },
        "known": known,
        "unknown": unknown,
        "evidence": records[:12],
        "timeline": (detail.get("timeline") or [])[:20],
        "reports": (detail.get("reports") or [])[:10],
        "requests": (detail.get("requests") or [])[:10],
        "signals": (detail.get("signals") or [])[:5],
        "alerts": (detail.get("alerts") or [])[:5],
        "facilities": facilities,
        "sources_failing": [
            {"code": row.get("code"), "status": row.get("status"), "error": row.get("last_error")}
            for row in failing
        ],
        "mode": system_state.system_mode(db).get("mode", "live"),
    }


# --------------------------------------------------------------------------- #
# Wording - the deterministic half
# --------------------------------------------------------------------------- #
def render_findings(findings: dict[str, Any]) -> str:
    """Fixed sentences over the retrieved records. Not elegant, never wrong about what
    it is sure of and never quiet about what it is not."""
    head = findings["incident"]
    lines: list[str] = []
    if findings["mode"] == "demo":
        lines.append("Demo mode: the situation below is a scripted rehearsal, not a happening.")
    lines.append(
        f"{head['ref_code']} - {head['title']} "
        f"({'unknown location' if not head.get('district') else head['district']})."
    )
    lines.append(
        f"Evidence state is {head['evidence_state']}; impact score {head['impact_score']} "
        f"at {head['urgency']} urgency."
    )
    if findings["known"]:
        lines.append("What is known: " + "; ".join(findings["known"]) + ".")
    if findings["evidence"]:
        sources = ", ".join(
            sorted({str(row.get("source") or row.get("source_code") or "record") for row in findings["evidence"]})
        )
        lines.append(f"Records behind it: {sources}.")
    if findings["reports"]:
        lines.append(
            f"{len(findings['reports'])} community report(s) are attached, newest: "
            f"{str(findings['reports'][0].get('message') or '')[:160]}"
        )
    if findings["requests"]:
        refs = ", ".join(str(row.get("ref_code")) for row in findings["requests"] if row.get("ref_code"))
        lines.append(f"Open help requests tied to it: {refs}.")
    if findings["facilities"]:
        lines.append(
            "Facilities in the catalogue for that district: "
            + ", ".join(
                f"{row.get('name')} ({row.get('resource_type')}, availability {row.get('availability')})"
                for row in findings["facilities"][:5]
            )
            + "."
        )
    if findings["unknown"]:
        lines.append("What is not known: " + "; ".join(findings["unknown"]) + ".")
    if findings["sources_failing"]:
        lines.append(
            "Sources not answering: "
            + ", ".join(str(row.get("code")) for row in findings["sources_failing"])
            + " - the picture may be thinner than the event."
        )
    if head.get("needs_review"):
        lines.append(f"Flagged for review: {head.get('review_reason') or 'no reason recorded'}.")
    lines.append(
        "This was assembled by retrieval code with no language model; every figure above is "
        "quoted from a stored record."
    )
    return "\n\n".join(lines)


# --------------------------------------------------------------------------- #
# The guardrail
# --------------------------------------------------------------------------- #
def check_numbers(
    findings: dict[str, Any], text: str, retrieved: Iterable[str] = ()
) -> list[str]:
    """Numbers the answer asserts that the findings and this run's own lookups do not contain.

    The rule itself lives in `agent/numbers.py` so the responder path applies the identical
    one; this wrapper keeps the findings-shaped call the investigation reads as prose.

    `retrieved` is what the model pulled with a tool during the run. Without it the check
    measures the answer against the starting evidence only, and a figure the platform itself
    handed over reads as invented - which is what rejected the first live run, for quoting an
    incident's own coordinate straight out of a tool result it had just received.

    Dates and ages are not converted - the guard reads digits, not units - but they are no longer
    invisible: the evidence spells an age "4h 45m" inside a JSON string, and a sentence that says
    "4 hours" used to be refused for the 4. Everything else has to appear in the data the model
    was handed.
    """
    corpus = "\n".join(
        [json.dumps(findings, ensure_ascii=False, default=str), *retrieved]
    )
    return ungrounded_numbers(corpus, text)


def _watch_tool_calls(agent: Any, trace: ActivityTrace, retrieved: list[str]) -> None:
    """Record what the model looked up, so the guard can credit it and the run can show it.

    The prompt invites the model to widen the findings with tools, and until now it could do
    that with nothing the run kept: `tool_calls` stayed `[]` whether the model called six tools
    or none, and `check_numbers()` judged the answer against the starting evidence alone. The
    responder path has neither problem, because every one of its tools files its own payload in
    `ctx.evidence` and the guard reads that list. This is the same idea for this path.

    The payload text goes into `retrieved` - used for the check and never stored. The trace gets
    the name, the outcome and the scalars the model passed, and no summary line, because
    `agent/trace.py` keeps the model's wording and a generic digest of a result out of the
    timeline: a tool knows which of its numbers matter, this callback does not.

    Registered with the event named rather than through `Agent(hooks=[...])`, for the reason
    written up in `ActivityTrace.attach`.
    """
    from strands.hooks import AfterToolCallEvent

    def note(event: Any) -> None:
        result = getattr(event, "result", None) or {}
        blocks: list[str] = []
        for block in result.get("content") or []:
            if not isinstance(block, dict):
                blocks.append(str(block))
            elif "json" in block:
                blocks.append(json.dumps(block["json"], ensure_ascii=False, default=str))
            elif "text" in block:
                blocks.append(str(block["text"]))
        body = "\n".join(blocks)
        use = getattr(event, "tool_use", None) or {}
        name = str(
            getattr(getattr(event, "selected_tool", None), "tool_name", "")
            or use.get("name")
            or "unknown_tool"
        )
        retrieved.append(f"{name} -> {body}")
        trace.tool(
            name,
            status=(
                "error"
                if result.get("status") == "error"
                else "refused"
                if "not_permitted" in body
                else "ok"
            ),
            asked=use.get("input") if isinstance(use.get("input"), dict) else None,
        )

    agent.hooks.add_callback(AfterToolCallEvent, note)


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def investigate(
    db: Any, incident: Incident, *, permissions: set[str] | None = None, viewer: str = "system"
) -> dict[str, Any]:
    """One investigation, end to end. Always returns a usable answer; `mode` says which
    half of the system produced it, and `status` says whether the model's version survived
    the number check."""
    from agent import model as model_module  # local: the fallback must not need the SDK

    started = time.monotonic()
    findings = gather_findings(db, incident, permissions)
    deterministic = render_findings(findings)
    trace = ActivityTrace(subject=incident.ref_code)
    retrieved: list[str] = []
    result: dict[str, Any] = {
        "trigger": "incident",
        "subject_type": "incident",
        "subject_id": incident.id,
        "ref_code": incident.ref_code,
        "mode": "deterministic",
        "status": "completed",
        "model": None,
        "findings": findings,
        # Lifted out of `findings` because the caller renders these two lists as the
        # "known / not known" panels, and the stored record keeps them for the audit view.
        "known": findings.get("known") or [],
        "unknown": findings.get("unknown") or [],
        "response_text": deterministic,
        "tool_calls": [],
        "model_calls": 0,
        "rejected_numbers": [],
        "note": (
            "No language model is configured, so this answer is retrieved records rendered "
            "by fixed sentences."
        ),
    }

    built = model_module.build_model()
    if built is None:
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return result

    from agent.prompts import INVESTIGATE  # after the availability check
    from agent.tools import build_tools

    try:
        from strands import Agent

        agent = Agent(
            model=built,
            tools=build_tools(db, permissions),
            system_prompt=INVESTIGATE,
        )
        trace.attach(agent)
        _watch_tool_calls(agent, trace, retrieved)
        prompt = (
            f"Investigate {incident.ref_code} for {viewer}. The retrieved facts are below; "
            f"call tools to widen them if needed, then write the answer.\n\n"
            f"{json.dumps(findings, ensure_ascii=False, default=str)[:12000]}"
        )
        answer = str(agent(prompt))
        offending = check_numbers(findings, answer, retrieved)
        if offending:
            result["status"] = "rejected_unverified_numbers"
            result["rejected_numbers"] = offending
            result["note"] = (
                "The model's wording stated numbers that appear in no retrieved record, so the "
                "deterministic rendering is what is shown. The rejected values are listed."
            )
            logger.warning(
                "agent answer for %s rejected: invented numbers %s", incident.ref_code, offending
            )
        else:
            result["mode"] = "strands"
            result["response_text"] = answer
            result["note"] = None
        result["model"] = model_module.status().model_id
    except Exception as exc:  # noqa: BLE001 - a dead model must not fail the request
        db.rollback()
        result["status"] = "model_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("agent run failed for %s: %s", incident.ref_code, exc)

    # Set after the try/except so a run that died halfway still reports the tools it did call.
    result["tool_calls"] = trace.to_list()
    result["model_calls"] = trace.model_calls
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result
