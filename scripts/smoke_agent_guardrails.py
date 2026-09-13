"""The responder's guardrails, called with the arguments a model is allowed to send.

    python scripts/smoke_agent_guardrails.py

`scripts/scenario_melamchi.py` proves the agent *runs*, and it cannot do that until a provider
is configured. This proves the other half of the phase's architecture rule - "the LLM is NOT
the source of truth" - and that half is testable now, with no model, because a model's entire
influence over a write tool is the arguments it passes to it. So these are the tools the model
calls, called directly, with arguments a model really can produce, asserting what comes back:

  - a risk flag the report's words do not carry is refused, however confidently it is asserted;
  - a flag the words do carry stands even when the model missed it;
  - a kind of help stands only on a quote copied verbatim out of the report;
  - no model argument can reach the urgency, the status, the description or a coordinate;
  - a note stays internal and moves no status, a notice notifies and dispatches nothing;
  - a message to the person in danger is refused when it states a figure nothing returned;
  - without a permission, nothing is written at all.

Nothing here is a simulated agent run: no `Agent` is built, no run row is stored, no answer is
composed, and no fake provider is wired in. The strongest check is the one that files the same
report twice - once with no proposal at all and once with a model's wrong proposal - and insists
the two cases come out with the same priority, which is what "not the source of truth" has to
mean if anyone can check it. Every row created here is deleted on the way out.
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import prepare

prepare()

from sqlalchemy import delete, func, select  # noqa: E402

from agent.numbers import ungrounded_numbers  # noqa: E402
from agent.tools import ResponderContext, build_respond_tools, file_request  # noqa: E402
from agent.trace import ActivityTrace  # noqa: E402
from agent.workflows.investigate import (  # noqa: E402
    _watch_tool_calls,
    check_numbers,
    gather_findings,
)
from backend.app.db import SessionLocal  # noqa: E402
from backend.app.deps import granted_permissions  # noqa: E402
from backend.app.models.core import (  # noqa: E402
    AssistanceRequest,
    AssistanceUpdate,
    AuditEvent,
    Incident,
    Notification,
    User,
)
from backend.app.services import assistance as assistance_service  # noqa: E402

WATER = "We are without water and the children are thirsty."
MELAMCHI = "My father is injured and we are trapped near Melamchi. The road is blocked and we need help."
MOBILE = "We have to move my mother but nothing is coming to take us."
# Its own text, so the permission check can count the cases *this* wording filed without
# tripping over whatever else the running API server happens to write in the same second.
CUT_OFF = "We are cut off below Kimatung with no food and no water."

# What no write tool may accept as an argument, because the platform decides it. `ref_code` and
# `severity` are absent on purpose: a writer may name the case it means and label its own notice.
FORBIDDEN = {
    "urgency", "priority", "score", "status", "description", "district", "province",
    "municipality", "ward_no", "latitude", "longitude", "location_confidence",
    "user_id", "victim", "victim_id", "contact_phone", "incident_id", "matched_resource_ids",
    "assigned_to", "team", "dispatch", "resolution_note", "acknowledged", "resolved_at",
    "sla_minutes", "channel", "phone", "email", "sms", "to",
}

OK: list[str] = []
ISSUES: list[str] = []


def ok(text: str) -> None:
    OK.append(text)
    print(f"  ok  {text}")


def issue(text: str) -> None:
    ISSUES.append(text)
    print(f"  !! {text}")


def note(text: str) -> None:
    """Print a fact this gate neither passes nor fails - used for behaviour that is already
    written down in `docs/known-issues.md`, so the gate reminds rather than re-reports."""
    print(f"  --  {text}")


def check(label: str, passed: bool, detail: str) -> bool:
    (ok if passed else issue)(f"{label} - {detail}")
    return passed


def run(label: str, section, *args) -> None:
    """One section of the gate, with a crash turned into a report.

    Learned the hard way: an assertion written against the wrong field ended the whole run at the
    first section, so every check after it silently did not happen and the exit code said only
    "crashed". A gate is worth what it covers, so a broken section is one failed line and the
    rest still run.
    """
    try:
        section(*args)
    except Exception as exc:  # noqa: BLE001 - reporting is the point, propagating is not
        issue(f"{label} raised {type(exc).__name__}: {exc} - the checks in it after that line did not run")


def ctx_for(
    db,
    report: str,
    operator,
    permissions,
    *,
    subject: str = "guardrail-check",
):
    """A fresh context and its tools, the way the workflow builds them.

    A new `ResponderContext` per check matters: it holds the run's evidence corpus and the refs
    it filed, and sharing one between checks would let a message pass the number guardrail
    because a *different* check had retrieved the number.
    """
    ctx = ResponderContext(
        db=db,
        permissions=permissions,
        report_text=report,
        victim=None,
        operator=operator,
        language="en",
        trace=ActivityTrace(subject=subject),
    )
    tools = {item.tool_name: item for item in build_respond_tools(ctx)}
    return ctx, tools


def call(tool, **arguments) -> dict:
    """Invoke a tool the way the agent runtime does and read its JSON reply."""
    return json.loads(tool(**arguments))


def request_for(db, ref_code: str) -> AssistanceRequest:
    return db.execute(
        select(AssistanceRequest).where(AssistanceRequest.ref_code == ref_code)
    ).scalar_one()


def stored_flags(request: AssistanceRequest) -> dict[str, bool]:
    """The five risk flags as the case file holds them.

    `medical_need` and `immediate_danger` are columns; `trapped`, `minors_involved` and
    `elderly_or_disabled_involved` live inside `structured`. That asymmetry is read off
    `assistance.create`, which takes all five and persists two of them as columns - and it is
    why the gate looks its flags up through here. Written against `request.trapped` an assertion
    is an AttributeError; written against the wrong column it silently reads a False that never
    happened, which is the worse of the two.
    """
    extra = request.structured or {}
    return {
        "medical_need": bool(request.medical_need),
        "immediate_danger": bool(request.immediate_danger),
        "trapped": bool(extra.get("trapped")),
        "minors_involved": bool(extra.get("minors_involved")),
        "elderly_or_disabled_involved": bool(extra.get("elderly_or_disabled_involved")),
    }


# --------------------------------------------------------------------------- #
# 1. priority
# --------------------------------------------------------------------------- #
def flags_come_from_the_words(db, operator, perms, created):
    """A flag is true when the report says so. Asserting one is not saying so."""
    ctx, tools = ctx_for(db, WATER, operator, perms, subject="flags")
    out = call(
        tools["create_assistance_request"],
        request_type="medical",
        assistance_types=["medical"],
        medical_need=True,
        trapped=True,
    )
    created.append(out["ref_code"])
    stored = request_for(db, out["ref_code"])

    used = {name for name, value in out["flags_used"].items() if value}
    over = set(out["flags_the_model_overreached"])
    missed = set(out["flags_the_model_missed"])
    check(
        "an asserted flag the words do not carry is refused",
        not {"medical_need", "trapped"} & used and {"medical_need", "trapped"} <= over,
        f"words carry {sorted(used)}; refused {sorted(over)}",
    )
    check(
        "a flag the model missed is still applied",
        "minors_involved" in missed and "minors_involved" in used,
        "children in the report set minors_involved although the proposal never mentioned it",
    )
    check(
        "a kind of help the words do not carry is dropped from the proposal",
        "medical" in out["types_dropped_as_unsupported"],
        f"'thirsty' is not a medical need: asked for "
        f"{sorted({'medical'} | set(out['types_dropped_as_unsupported']))}, stored {out['assistance_types']}",
    )
    check(
        "the disagreement is written on the case, not just returned",
        {"medical_need", "trapped"} <= set((stored.structured or {}).get("flags_model_overreached", [])),
        f"{stored.ref_code} records what the model asserted and what stood",
    )

    # The same words, filed with no proposal at all: an identical priority is the proof that
    # the assertions changed nothing. Two routes, one outcome, is the whole architecture rule.
    rules_ctx, _ = ctx_for(db, WATER, operator, perms, subject="flags-rules-baseline")
    baseline, _ = file_request(rules_ctx, {})
    created.append(baseline["ref_code"])
    same_urgency = baseline["urgency"] == stored.urgency
    same_reasons = list(baseline["urgency_reasons"] or []) == list(stored.urgency_reasons or [])
    check(
        "the model's wrong proposal changed neither the urgency nor its reasons",
        same_urgency and same_reasons,
        f"both {stored.urgency}: {'; '.join(stored.urgency_reasons or [])}",
    )
    check(
        "and the two routes are recorded as the two different routes they were",
        (baseline["ref_code"] != stored.ref_code)
        and (stored.structured or {}).get("filing_route") == "model_called_the_tool"
        and (request_for(db, baseline["ref_code"]).structured or {}).get("filing_route")
        == "deterministic_rules",
        "same outcome, different provenance - an audit can tell them apart",
    )


def missed_flags_still_score(db, operator, perms, created):
    """Missing 'trapped' is the worst failure available, so it cannot lower a priority."""
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="missed")
    out = call(
        tools["create_assistance_request"],
        request_type="information",
        assistance_types=["information"],
        medical_need=False,
        trapped=False,
    )
    created.append(out["ref_code"])
    stored = request_for(db, out["ref_code"])
    flags = stored_flags(stored)
    check(
        "a plea the rules read as critical stays critical when the model calls it information",
        stored.urgency == "critical" and flags["trapped"] and flags["medical_need"],
        f"{stored.ref_code} at {stored.urgency} with trapped={flags['trapped']}, "
        f"medical_need={flags['medical_need']}",
    )
    check(
        "every flag the rules set is on the case the responder opens",
        flags == {k: bool(v) for k, v in out["flags_used"].items()},
        f"the tool answered {out['flags_used']}; the row carries {flags}",
    )
    check(
        "a help type the report's own words carry survives what the model asked for",
        {"medical", "rescue", "transport"} <= set(stored.assistance_types or []),
        f"stored {stored.assistance_types} though only 'information' was proposed",
    )


# --------------------------------------------------------------------------- #
# 2. grounding
# --------------------------------------------------------------------------- #
def quotes_are_checked_character_by_character(db, operator, perms, created):
    """A composed quote must not buy a claim; a copied one may, because it is traceable.

    "Move my mother, nothing is coming" names no keyword in the help-type table, so both calls
    below ask for `transport` on the strength of the quote alone - the forged one is refused and
    the copied one is accepted, which is the only version of this that separates a real guardrail
    from a keyword list.
    """
    ctx, tools = ctx_for(db, MOBILE, operator, perms, subject="quote-forged")
    forged = call(
        tools["create_assistance_request"],
        request_type="transport",
        assistance_types=["transport"],
        evidence_quote="the ambulance was delayed for six hours",
    )
    created.append(forged["ref_code"])

    ctx2, tools2 = ctx_for(db, MOBILE, operator, perms, subject="quote-verbatim")
    copied = call(
        tools2["create_assistance_request"],
        request_type="transport",
        assistance_types=["transport"],
        evidence_quote="nothing is coming to take us",
    )
    created.append(copied["ref_code"])

    check(
        "a quote the report does not contain buys nothing, and says so",
        forged["evidence_quote_verified"] is False
        and "transport" in forged["types_dropped_as_unsupported"]
        and "transport" not in (request_for(db, forged["ref_code"]).assistance_types or []),
        f"composed wording refused; stored {forged['assistance_types']}",
    )
    check(
        "a quote copied out of the report is credited, and the claim stands on it",
        copied["evidence_quote_verified"] is True
        and "transport" in copied["assistance_types"]
        and not copied["types_dropped_as_unsupported"],
        f"verbatim words carried 'transport' onto the case: {copied['assistance_types']}",
    )
    check(
        "and the credited quote is named as such on the record",
        "transport" in (request_for(db, copied["ref_code"]).structured or {}).get(
            "types_from_verified_quote", []
        ),
        "structured.types_from_verified_quote says which part of the reading rests on the quote",
    )
    check(
        "the quote moved the kind of help and nothing else",
        forged["flags_used"] == copied["flags_used"]
        and set(copied["assistance_types"]) - set(forged["assistance_types"]) == {"transport"},
        f"urgency went {forged['urgency']} -> {copied['urgency']} only because the type did - "
        "a type is an input to the score, so a verified quote is allowed to move it",
    )


def the_model_cannot_even_ask(db, operator, perms, created):
    """The parameters that do not exist are the real guardrail.

    Read off the schemas strands would hand to the model, because that list is the whole surface
    a model can reach: a value with no parameter for it cannot be invented.
    """
    writers = {
        "create_assistance_request",
        "update_assistance_request",
        "notify_response_center",
        "send_victim_update",
    }
    ctx, tools = ctx_for(db, MOBILE, operator, perms, subject="schema")
    exposed = {
        name: set((tools[name].tool_spec["inputSchema"]["json"].get("properties") or {}).keys())
        for name in writers
    }
    leaked = {
        name: sorted(params & FORBIDDEN) for name, params in exposed.items() if params & FORBIDDEN
    }
    check(
        "no write tool takes a priority, a status, a description, a coordinate or an identity",
        not leaked,
        f"{sum(len(v) for v in exposed.values())} parameters across 4 writers, none of them a "
        f"decision code owns" if not leaked else f"these accept something only code may set: {leaked}",
    )
    check(
        "the filing tool takes no district, so a place cannot be labelled by hand",
        not exposed["create_assistance_request"] & {"district", "province", "municipality", "ward_no"},
        "it may pass `location_text`, a phrase the reporter said, and the gazetteer decides "
        f"what that is: {sorted(exposed['create_assistance_request'])}",
    )
    check(
        "the message tool cannot be aimed at a person or a channel",
        not {"phone", "to", "channel", "email", "sms"} & exposed["send_victim_update"],
        f"send_victim_update takes {sorted(exposed['send_victim_update'])} - a case reference and words",
    )
    for name, params in sorted(exposed.items()):
        note(f"{name} accepts: {', '.join(sorted(params))}")


def description_is_the_reporter(db, operator, perms, created):
    report = "Please bring my brother out, he is not answering. Kalai pulgari."
    ctx, tools = ctx_for(db, report, operator, perms, subject="verbatim")
    out = call(
        tools["create_assistance_request"],
        request_type="rescue",
        assistance_types=["rescue"],
        trapped=True,
        evidence_quote="he is not answering",
    )
    created.append(out["ref_code"])
    stored = request_for(db, out["ref_code"])
    check(
        "the description stored is the caller's words, unchanged",
        stored.description == report and out["description_stored"].startswith("the reporter's own"),
        "no summarisation between the phone and the case file",
    )
    check(
        "the case waits for a person: filed, not acknowledged, not worked",
        stored.status == "received" and stored.acknowledged_at is None,
        f"{stored.ref_code} at status {stored.status}",
    )
    check(
        "the tool that was called says it was called",
        (stored.structured or {}).get("filing_route") == "model_called_the_tool",
        f"filing_route={(stored.structured or {}).get('filing_route')}, set by the tool path and "
        "not by the caller - a script calling it looks exactly like a model calling it, which is "
        "why this gate is valid at all",
    )


# --------------------------------------------------------------------------- #
# 3. what the writes may do
# --------------------------------------------------------------------------- #
def a_note_is_internal(db, operator, perms, created):
    NOTE = "Road bulletin checked; no entry for this road."
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="note")
    filed = call(tools["create_assistance_request"], request_type="medical", trapped=True)
    ref = filed["ref_code"]
    created.append(ref)
    rid = request_for(db, ref).id
    before_victim_visible = db.execute(
        select(func.count()).select_from(AssistanceUpdate).where(
            AssistanceUpdate.request_id == rid, AssistanceUpdate.visible_to_victim.is_(True)
        )
    ).scalar_one()

    noted = call(tools["update_assistance_request"], ref_code=ref, note=NOTE)
    after = request_for(db, ref)
    # Found by the row's own text, not by "newest": the filing writes an update in the same
    # second, and a tie on a second-resolution timestamp would make the newest row a coin flip.
    row = db.execute(
        select(AssistanceUpdate).where(
            AssistanceUpdate.request_id == rid, AssistanceUpdate.message == NOTE
        )
    ).scalar_one_or_none()

    check(
        "a note appends without moving the status",
        noted.get("status_changed") is False
        and after.status == "received" and after.acknowledged_at is None,
        f"reply says status_changed={noted.get('status_changed', noted.get('error'))}; "
        f"{ref} still {after.status}",
    )
    check(
        "a note is not visible to the person who asked for help",
        row is not None and row.visible_to_victim is False and row.actor_type == "agent",
        f"the stored note is actor_type={row.actor_type if row else '-'}, "
        f"visible_to_victim={row.visible_to_victim if row else '-'} "
        f"under the label {row.actor_label if row else '-'!r}",
    )
    check(
        "and it added nothing to what the victim can see",
        db.execute(
            select(func.count()).select_from(AssistanceUpdate).where(
                AssistanceUpdate.request_id == rid, AssistanceUpdate.visible_to_victim.is_(True)
            )
        ).scalar_one()
        == before_victim_visible,
        "the victim-visible count is unchanged by an internal note",
    )

    missing = call(tools["update_assistance_request"], ref_code="REQ-19990101-0000-ffff", note="x")
    empty = call(tools["update_assistance_request"], ref_code=ref, note="   ")
    check(
        "a note onto a case that does not exist, or with nothing in it, writes nothing",
        missing.get("error") == "not_found" and empty.get("error") == "empty_note",
        "both refused with a reason rather than failing quietly",
    )


def a_notice_notifies(db, operator, perms, created):
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="notice")
    filed = call(tools["create_assistance_request"], request_type="rescue", trapped=True)
    ref = filed["ref_code"]
    created.append(ref)
    out = call(
        tools["notify_response_center"],
        title="Two households report being cut off above Melamchi",
        body="From the reports themselves; no official road status exists.",
        severity="high",
        request_ref=ref,
    )
    row = db.get(Notification, out["notification_id"])
    after = request_for(db, ref)
    check(
        "a notice reaches the Response Center with a human-readable claim",
        row is not None and "cut off" in (row.title or "") and row.audience == "response_center",
        f"notification {row.kind if row else '-'} for {row.audience if row else '-'}",
    )
    check(
        "a notice changes no case and dispatches nobody",
        after.status == "received" and out["note"].startswith("a notice asks a human to look"),
        "the tool's own reply states the limit of what it did",
    )
    bogus = call(tools["notify_response_center"], title="x", severity="apocalyptic")
    check(
        "a severity outside the platform's own levels is demoted, not stored",
        bogus["severity"] == "information",
        f"'apocalyptic' became {bogus['severity']!r}",
    )
    db.execute(delete(Notification).where(Notification.id == bogus.get("notification_id")))
    db.commit()


def a_victim_message_is_the_hardest_gate(db, operator, perms, created):
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="victim")
    filed = call(tools["create_assistance_request"], request_type="medical", trapped=True)
    ref = filed["ref_code"]
    created.append(ref)
    rid = request_for(db, ref).id

    def visible_count() -> int:
        return db.execute(
            select(func.count()).select_from(AssistanceUpdate).where(
                AssistanceUpdate.request_id == rid, AssistanceUpdate.visible_to_victim.is_(True)
            )
        ).scalar_one()

    before = visible_count()
    # Deliberately unlikely figures: a check that failed whenever the minute of a timestamp
    # happened to be 12 would be a flaky gate, not a guardrail.
    invented = call(
        tools["send_victim_update"],
        ref_code=ref,
        message="An ambulance is 347 km away and will reach you in 92 minutes.",
    )
    check(
        "a message promising a time and a distance nothing returned is refused",
        invented.get("error") == "unverified_numbers" and visible_count() == before,
        f"refused {invented.get('numbers')}; nothing was sent",
    )
    check(
        "and the refusal names the figures, so the model could correct itself",
        {"347", "92"} <= set(invented.get("numbers") or []),
        f"reply said: {(invented.get('detail') or '')[:80]}",
    )

    grounded = call(
        tools["send_victim_update"],
        ref_code=ref,
        message=f"Your request {ref} is with the Response Center. No arrival time has been set.",
    )
    check(
        "a message made only of what this run established is sent",
        grounded.get("sent") is True and visible_count() > before,
        f"went out under {grounded.get('sent_by')} as an agent draft",
    )
    # Again by content rather than by "newest" - the send and the filing land in one second.
    last = db.execute(
        select(AssistanceUpdate).where(
            AssistanceUpdate.request_id == rid,
            AssistanceUpdate.message.like("%No arrival time has been set."),
        )
    ).scalars().first()
    check(
        "and it is visible to the person who asked, unlike a note",
        last is not None and last.visible_to_victim is True,
        f"stored as actor_type={last.actor_type if last else '-'}, "
        f"labelled {last.actor_label if last else '-'} - the person, not the agent, is the sender",
    )

    noref = call(tools["send_victim_update"], ref_code="REQ-19990101-0000-ffff", message="Hello.")
    check("a message to a case that does not exist is refused", noref.get("error") == "not_found", "no silent send into nowhere")

    anonymous_ctx, anonymous_tools = ctx_for(db, MELAMCHI, None, perms, subject="no-operator")
    anonymous = call(anonymous_tools["send_victim_update"], ref_code=ref, message="A request exists.")
    check(
        "with no named operator, nothing goes out to someone in danger",
        anonymous.get("error") == "no_named_operator" and visible_count() == before + 1,
        "a message must be signed by a person, and the count of visible updates did not move",
    )
    check(
        "and that refusal is itself on the timeline, because a refusal is something that happened",
        any(
            step["action"] == "SEND_VICTIM_UPDATE" and step["status"] == "refused"
            for step in anonymous_ctx.trace.steps
        ),
        f"{len(anonymous_ctx.trace.steps)} step(s) recorded for the anonymous run",
    )


# --------------------------------------------------------------------------- #
# 4. permissions
# --------------------------------------------------------------------------- #
def without_permission(db, operator, created):
    """An empty permission set is what a caller without the rights gets.

    The point is not that four dictionaries come back saying no - it is that the four refusals
    write no row anywhere, including the two tables a refusal could quietly dirty: a case filed
    without permission would reach a responder, and a notification would reach a queue.
    """
    ctx, tools = ctx_for(db, CUT_OFF, operator, set(), subject="no-perms")
    def filed() -> int:
        return db.execute(
            select(func.count()).select_from(AssistanceRequest).where(
                AssistanceRequest.description == CUT_OFF
            )
        ).scalar_one()

    before = filed()
    replies = {
        "create": call(tools["create_assistance_request"], request_type="medical", trapped=True),
        "notify": call(tools["notify_response_center"], title="anything"),
        "update": call(tools["update_assistance_request"], ref_code="REQ-19990101-0000-ffff", note="x"),
        "send": call(tools["send_victim_update"], ref_code="REQ-19990101-0000-ffff", message="x"),
    }
    check(
        "every write the caller may not do answers not_permitted",
        all(r.get("error") == "not_permitted" for r in replies.values()),
        "4 tools, 4 refusals: "
        + ", ".join(f"{name}={r.get('error', '?')}" for name, r in sorted(replies.items())),
    )
    check("and a refused run files no case", filed() == before and not ctx.created_refs, f"{before} -> {filed()} cases, 0 refs claimed")
    check(
        "and it leaves no notification and no note behind",
        db.execute(
            select(func.count()).select_from(Notification).where(Notification.title == "anything")
        ).scalar_one()
        == 0,
        "a refusal is an answer, not a partial write",
    )
    if ctx.trace.steps:
        issue(
            f"a permission refusal left {len(ctx.trace.steps)} step(s) in the timeline; "
            "expected none"
        )
    else:
        note(
            "a refusal by permission records no timeline step at all - the gap written up as "
            "issue 71 in docs/known-issues.md: an operator watching the timeline sees no trace "
            "of an attempt, which is the one place this gate cannot decide it for them"
        )


def with_no_permission_list_at_all(db, operator, created):
    """`permissions=None` means the caller named nobody, which is a different thing from naming
    nobody allowed. Pinned so the default cannot quietly flip into a lock-out."""
    ctx, tools = ctx_for(db, CUT_OFF, operator, None, subject="no-perm-list")
    out = call(tools["create_assistance_request"], request_type="medical", trapped=True)
    if out.get("created"):
        created.append(out["ref_code"])
        ok("a context built with permissions=None lets the tools through (documented default)")
    else:
        issue(f"permissions=None now refuses writes: {out.get('error')} - check ResponderContext.allowed")


def a_forged_incident_reference(db, operator, perms, created):
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="forged-ref")
    out = call(
        tools["create_assistance_request"],
        request_type="rescue",
        trapped=True,
        incident_ref="INC-19990101-9999-ffff",
    )
    created.append(out["ref_code"])
    stored = request_for(db, out["ref_code"])
    check(
        "an incident reference that does not exist attaches nothing",
        stored.incident_id is None,
        "the case is filed with no incident rather than a guessed one",
    )
    check(
        "but the filing says the link did not happen, instead of filing quietly unlinked",
        out.get("incident_not_attached") == "INC-19990101-9999-FFFF"
        or "INC-19990101-9999-ffff" in str(out.get("incident_not_attached")),
        f"reply: {out.get('detail') or 'no mention of the reference'}",
    )
    orphan = call(
        tools["notify_response_center"],
        title="Notice about a case",
        request_ref="REQ-19990101-0000-ffff",
    )
    check(
        "a notice aimed at a case that does not exist is not queued at all",
        orphan.get("error") == "not_found",
        "an unattached notice would still reach the queue looking real, so the reference is "
        "checked before the row is written",
    )


def a_reference_survives_being_typed_back(db, operator, perms, created):
    """The bug this check exists for, found by running the write tools for the first time.

    A reference code ends in four lowercase hex characters, and `_request_by_ref` used to
    uppercase the argument before an exact match - so a case the filing tool had just named was
    `not_found` for the other three writers about 6 times in 7. A model copies what it was given,
    and often capitalises it; an operator reads it off a screen. Both are the same lookup.
    """
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="ref-case")
    # File until the reference has a letter in its hex suffix, because a suffix of all digits is
    # identical when upper-cased and would let the check pass against the broken lookup. Six
    # filings leaves a one-in-a-hundred-million chance of still not discriminating, and every
    # case filed on the way is cleaned up like the rest.
    ref = ""
    for _ in range(6):
        filed = call(tools["create_assistance_request"], request_type="rescue", trapped=True)
        created.append(filed["ref_code"])
        if any(char.isalpha() for char in filed["ref_code"].rsplit("-", 1)[-1]):
            ref = filed["ref_code"]
            break
    if not ref:
        issue("no reference with a letter in its suffix in six filings - the case check below is not discriminating")
        return
    check(
        "a reference that can distinguish the two lookups was filed",
        ref != ref.upper(),
        f"{ref} - upper-casing it changes the string, so a forced .upper() cannot find it",
    )
    exact = call(tools["update_assistance_request"], ref_code=ref, note="Exact reference.")
    check(
        "the reference the tool returned is the one that finds the case",
        exact.get("updated") is True,
        f"{ref} -> {exact.get('error') or 'updated'}",
    )
    upper = call(tools["update_assistance_request"], ref_code=ref.upper(), note="Typed in capitals.")
    lower = call(tools["update_assistance_request"], ref_code=ref.lower(), note="Typed in small letters.")
    check(
        "and so is the same reference in either case, because the suffix is lowercase hex",
        upper.get("updated") is True and lower.get("updated") is True,
        f"upper={upper.get('error') or 'updated'}, lower={lower.get('error') or 'updated'}",
    )
    message = call(
        tools["send_victim_update"],
        ref_code=ref.upper(),
        message=f"Your request {ref} is with the Response Center.",
    )
    check(
        "a victim message addressed by the capitalised reference is sent",
        message.get("sent") is True,
        "the same lookup guards the hardest write, so one bug would have silenced all three",
    )
    notice = call(
        tools["notify_response_center"],
        title="Notice tied to a case",
        request_ref=ref.upper(),
    )
    row = db.get(Notification, notice["notification_id"]) if notice.get("notification_id") else None
    check(
        "and a notice addressed the same way stays attached to the case",
        notice.get("attached_to") == ref and row is not None and row.request_id == request_for(db, ref).id,
        f"attached_to={notice.get('attached_to')}, notification.request_id "
        f"{'set' if row and row.request_id else 'MISSING'}",
    )


def an_incident_reference_resolves(db, operator, perms, created):
    """The other half of the same lookup, tested against a reference that really exists.

    `_incident_by_ref` upper-cased its argument too, so a model quoting an incident from
    `get_official_disaster_incidents` would have been told no such incident exists, and the filing
    tool would have filed the case unlinked - silently, since attaching an incident is optional.
    """
    incidents = db.execute(
        select(Incident).order_by(Incident.created_at.desc()).limit(25)
    ).scalars().all()
    # One whose suffix has a letter, for the same reason the case check above files until it gets
    # one: an all-digit reference upper-cases to itself and would pass either way.
    incident = next(
        (
            row
            for row in incidents
            if any(char.isalpha() for char in row.ref_code.rsplit("-", 1)[-1])
        ),
        None,
    )
    if incident is None:
        note(
            f"no incident reference with a letter in its suffix among the newest {len(incidents)} - "
            "the case below is filed against an exact reference and proves less"
        )
        if not incidents:
            note("no incident in the database at all - the incident reference path went untested")
            return
        incident = incidents[0]
    wanted = incident.ref_code.upper()
    ctx, tools = ctx_for(db, MELAMCHI, operator, perms, subject="incident-ref")
    looked = call(tools["get_incident_details"], ref_code=wanted)
    check(
        f"an incident reference typed in capitals still names the incident ({incident.ref_code})",
        not looked.get("error")
        and (looked.get("incident") or {}).get("ref_code") == incident.ref_code,
        f"read back {(looked.get('incident') or {}).get('ref_code') or looked.get('error')}",
    )
    filed = call(
        tools["create_assistance_request"],
        request_type="rescue",
        trapped=True,
        incident_ref=wanted,
    )
    created.append(filed["ref_code"])
    stored = request_for(db, filed["ref_code"])
    check(
        "and a case filed against it is actually attached to that incident",
        stored.incident_id == incident.id,
        f"{filed['ref_code']} carries incident_id "
        f"{'the real one' if stored.incident_id == incident.id else stored.incident_id or 'nothing'}",
    )


# --------------------------------------------------------------------------- #
def digits_are_read_the_same_way_on_both_sides() -> None:
    """The guard reads digit runs, not number-words - and it challenges what it used to pardon.

    `2026-09-12T13:26:59Z` and `4h 45m` are how the evidence writes a moment: the digits are
    glued to letters. Extracting them with word boundaries - which is what the guard used to do -
    hides 12, 13, 59, 4 and 45 from the corpus, while the sentence that restates them shows every
    one, so an answer was refused for quoting its own evidence. The other half of the change is
    in the opposite direction: 19 to 26 used to be accepted wherever they came from.
    """
    evidence = '{"at": "2026-09-12T13:26:59Z", "age": "4h 45m ago", "value": 3.2, "count": 7}'

    restated = ungrounded_numbers(
        evidence, "The reading arrived at 13:26, about 4 hours ago (45m by the clock), at 3.2 mm."
    )
    check(
        "an answer that restates a timestamp or a humanised age is believed",
        restated == [],
        f"13, 4, 45 and 3.2 all come out of the evidence line, glued to letters or not - "
        f"refused: {restated or 'nothing'}",
    )

    invented = ungrounded_numbers(evidence, "19 shelters and 347 people were counted.")
    check(
        "a number the evidence does not hold is refused, in the 19-26 range included",
        invented == ["19", "347"],
        f"the blanket two-digit pardon is gone; refused {invented} - if 19 drops out of that "
        "list the range has been re-exempted somewhere",
    )

    padded = ungrounded_numbers(evidence, "at 09:12 ward-07 logged 0.7 mm")
    check(
        "zero padding is spelling, and a decimal is still its own figure",
        padded == ["0.7"],
        f"09 and 07 are grounded by the 9 and the 7 in the evidence; 0.7 is not the 3.2 that is "
        f"there, so only it is refused: {padded}",
    )


# --------------------------------------------------------------------------- #
class _StubAgent:
    """Just enough of a strands `Agent` to reach the callback `_watch_tool_calls` registers.

    The investigation path's guard fix is entirely in that callback - which payload text counts
    as evidence, and what the stored timeline says about a lookup - and none of it needs a
    provider. A free-tier key caps at ~20 requests a minute, so the behaviour is checked here
    against stub events shaped like `AfterToolCallEvent`, and the live run stays a demonstration.
    """

    def __init__(self) -> None:
        self.hooks = self
        self.callback = None

    def add_callback(self, _event, callback) -> None:  # noqa: ANN001 - strands event class
        self.callback = callback


class _StubEvent:
    """An `AfterToolCallEvent`-shaped record of one tool returning one JSON string."""

    def __init__(self, name: str, body: str, status: str = "success") -> None:
        self.result = {"status": status, "content": [{"text": body}]}
        self.tool_use = {"name": name, "input": {"district": "Dhanusha"}}
        self.selected_tool = type("_Tool", (), {"tool_name": name})()


def retrieved_numbers_are_credited(db, operator, perms, created) -> None:  # noqa: ARG001
    """A figure the model fetched with a tool is evidence, not invention.

    The guard used to compare the answer against the findings the run started with, so the first
    live investigation was rejected for quoting the incident's own coordinate - out of a tool
    result it had just been handed. The check needs a figure the starting bundle genuinely does
    not mention, so it looks for one instead of assuming it, and says so if the bundle ever
    starts carrying every number an incident has.
    """
    candidates = db.execute(
        select(Incident).where(Incident.latitude.is_not(None)).order_by(Incident.id).limit(8)
    ).scalars().all()
    incident = None
    findings: dict = {}
    latitude = ""
    for row in candidates:
        gathered = gather_findings(db, row)
        value = str(row.latitude)
        if value not in json.dumps(gathered, ensure_ascii=False, default=str):
            incident, findings, latitude = row, gathered, value
            break
    if incident is None:
        # Not a product fault, and not something to shrug at either: a check that can no longer
        # tell the two corpora apart is checking nothing, and whoever changed the bundle should
        # point it at a figure that is still absent.
        issue(
            "every incident tried now carries its coordinate in the starting findings, so this "
            "check has no way to tell the widened corpus from the old one - aim it at another "
            "figure a tool returns and the findings do not"
        )
        return
    check(
        f"the premise: {incident.ref_code} sits at {latitude}, which the starting findings omit",
        True,
        f"gathered from {len(findings)} finding group(s); the coordinate is only in the record",
    )

    agent = _StubAgent()
    trace = ActivityTrace(subject=incident.ref_code)
    retrieved: list[str] = []
    _watch_tool_calls(agent, trace, retrieved)
    if agent.callback is None:
        issue("the investigation run attached no tool callback, so nothing it fetches is credited")
        return

    answer = f"The event sits at {latitude} degrees north, which the record supplies."
    check(
        "before the fix, an answer quoting a fetched coordinate was refused",
        check_numbers(findings, answer) == [latitude],
        f"the old corpus (findings only) rejected {latitude!r} - that is the bug this check "
        "pins down, so a green run here with a red line means the guard has stopped working",
    )

    agent.callback(_StubEvent("get_incident", json.dumps({"latitude": incident.latitude})))
    check(
        "after it, the same answer passes once the tool that returned it is in the record",
        check_numbers(findings, answer, retrieved) == [],
        f"the run's own lookup is now part of the corpus ({len(retrieved)} payload(s) collected)",
    )
    check(
        "and the coordinate still has to appear in a payload for that to work",
        check_numbers(findings, "Everyone was 411 km away.", retrieved) == ["411"],
        "a number in no finding and no tool result is still refused: widening the corpus is not "
        "the same as dropping the check",
    )

    steps = trace.to_list()
    check(
        "the run records which tools the model called, which it used to record nothing",
        [s["action"] for s in steps] == ["GET_INCIDENT"] and steps[0]["kind"] == "tool",
        f"{[(s['action'], s['status']) for s in steps]} with the arguments it passed: "
        f"{steps[0].get('asked')}",
    )
    agent.callback(_StubEvent("find_relief_resources", json.dumps({"count": 3})))
    agent.callback(_StubEvent("get_river_status", json.dumps({"error": "not_permitted"})))
    agent.callback(_StubEvent("search_incidents", "", status="error"))
    kinds = {s["action"]: s["status"] for s in trace.to_list()}
    check(
        "a lookup the viewer could not make is recorded as refused, not as a success",
        kinds.get("GET_RIVER_STATUS") == "refused"
        and kinds.get("SEARCH_INCIDENTS") == "error"
        and kinds.get("FIND_RELIEF_RESOURCES") == "ok",
        f"{kinds}",
    )
    check(
        "and the timeline still carries no free text a model could have written into",
        all(set(s) <= {"at", "action", "kind", "status", "detail", "asked"} for s in trace.to_list())
        and not any(s.get("detail") for s in trace.to_list()),
        "the payload text went to the corpus and nowhere near the stored steps",
    )


# --------------------------------------------------------------------------- #
def cleanup(db, refs: list[str]) -> None:
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
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--operator", default="sunita.rc")
    parser.add_argument(
        "--keep", action="store_true", help="leave the rows this check wrote in the database"
    )
    args = parser.parse_args()

    db = SessionLocal()
    created: list[str] = []
    try:
        operator = db.execute(
            select(User).where(User.username == args.operator)
        ).scalar_one_or_none()
        if operator is None:
            print(f"No account {args.operator!r}; seed the demo accounts first.")
            return 2
        perms = granted_permissions(operator)
        needed = {"assistance:read", "assistance:message_victim", "incidents:read"}
        missing = sorted(needed - set(perms))
        print("=" * 78)
        print("SANKET GUARDRAILS - the write tools, with a model's arguments")
        print("=" * 78)
        print(f"operator     : {operator.username} ({operator.role}), {len(perms)} permission(s)")
        if missing:
            print(f"             {operator.username} lacks {missing}; the write tools would refuse")
            print("             every check below and the gate would prove nothing. Point")
            print("             --operator at an account that holds them (sunita.rc does).")
            return 2
        print("-" * 78)

        print("\npriority comes from the report, not from what the model asserts")
        run("priority", flags_come_from_the_words, db, operator, perms, created)
        run("priority", missed_flags_still_score, db, operator, perms, created)

        print("\nwhat a model may claim is checked against the caller's own words")
        run("grounding", quotes_are_checked_character_by_character, db, operator, perms, created)
        run("grounding", the_model_cannot_even_ask, db, operator, perms, created)
        run("grounding", description_is_the_reporter, db, operator, perms, created)

        print("\nwhat the write tools may do, and may not")
        run("references", a_reference_survives_being_typed_back, db, operator, perms, created)
        run("note", a_note_is_internal, db, operator, perms, created)
        run("notice", a_notice_notifies, db, operator, perms, created)
        run("victim message", a_victim_message_is_the_hardest_gate, db, operator, perms, created)
        run("forged reference", a_forged_incident_reference, db, operator, perms, created)
        run("incident reference", an_incident_reference_resolves, db, operator, perms, created)

        print("\npermissions")
        run("permissions", without_permission, db, operator, created)
        run("permissions", with_no_permission_list_at_all, db, operator, created)

        print("\nwhat the model fetched for itself is evidence too")
        run("retrieved", retrieved_numbers_are_credited, db, operator, perms, created)

        print("\nthe guard that decides what an answer may assert")
        run("digits", digits_are_read_the_same_way_on_both_sides)

        print()
        print("=" * 78)
        print(f"passed checks: {len(OK)}")
        print(f"ISSUES: {len(ISSUES)}")
        print("=" * 78)
        return 0 if not ISSUES else 1
    finally:
        if created:
            if args.keep:
                print(f"\nleft in the database: {', '.join(created)}")
            else:
                cleanup(db, created)
                print(f"\ncleaned up: {len(created)} case(s) this check filed, with their updates, "
                      "notifications and audit rows.")
        db.close()


if __name__ == "__main__":
    sys.exit(main())
